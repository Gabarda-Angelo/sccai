import os
import json
import requests
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

# Load .env file for local development (optional, not needed in Streamlit Cloud)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Streamlit Cloud uses secrets management, so no need for dotenv

# Model configuration
proposal_models = [
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "llama3-70b-8192",
    "gemma2-9b-it",
]
aggregator_model = "llama3-70b-8192"

# Validate environment variables
def validate_env():
    required_vars = ["GROQ_API_KEY", "API_URL", "API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

validate_env()

# API configuration
API_URL = os.getenv("API_URL")  # e.g., https://bookstoreadmin.shop/bookstoreapi.php
API_KEY = os.getenv("API_KEY")  # e.g., x7k9p2m4q8v3n6t1j5

# Fetch data from API
def fetch_data_from_api(action, params=None):
    try:
        payload = {"action": action, "key": API_KEY}
        if params:
            payload.update(params)
        response = requests.get(API_URL, params=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            return data["data"]
        else:
            raise ValueError(data.get("error", "Unknown API error"))
    except requests.RequestException as e:
        st.error(f"API request failed: {e}")
        return None

def get_sql_chain():
    template = """
You are an AI assistant helping a user retrieve data from the SCC School Store Database.
Based on the provided table schema, generate an accurate SQL query to answer the user's question.
The schema includes the following tables:
- categories
- employees
- inventory_logs
- invoices
- invoice_details
- products
- user_logins

Ensure you use appropriate joins and conditions considering foreign key constraints and data integrity.

<SCHEMA>
{schema}
</SCHEMA>

Conversation History: {chat_history}

Provide only the SQL query as output—without any additional text or explanations.
"""
    prompt = ChatPromptTemplate.from_template(template)

    proposal_llms = [ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
                    for model in proposal_models]

    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser()
          for i, llm in enumerate(proposal_llms)}
    )

    aggregator_template = """
You are a senior SQL expert analyzing multiple query proposals. Synthesize the best SQL query from these options:

{proposals}

Original Question: {question}
Database Schema:
{schema}

Consider these criteria:
1. Accuracy – Does the query correctly address the question using the appropriate tables and joins?
2. Efficiency – Is it optimized for performance?
3. Security – Does it prevent SQL injection risks?
4. Standards – Does it follow SQL best practices?

Return ONLY the final SQL query without any explanations or formatting.
"""
    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)

    return (
        RunnablePassthrough.assign(schema=lambda _: json.dumps({
            "tables": ["categories", "employees", "inventory_logs", "invoices", "invoice_details", "products", "user_logins"]
        }, indent=2))
        | RunnablePassthrough.assign(
            proposals=proposal_chain,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | aggregator_prompt
        | ChatGroq(model=aggregator_model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
        | StrOutputParser()
    )

def get_response(user_query: str, chat_history: list):
    sql_chain = get_sql_chain()
    query = sql_chain.invoke({"question": user_query, "chat_history": chat_history})
    st.write(f"Generated SQL Query: {query}")  # For debugging, remove in production

    # Map user query to API action
    if "best-selling" in user_query.lower():
        data = fetch_data_from_api("get_best_selling_products")
    elif "sales data" in user_query.lower():
        data = fetch_data_from_api("get_sales_data", {"period": "last_month"})
    elif "out of stock" in user_query.lower():
        data = fetch_data_from_api("get_out_of_stock")
    elif "total revenue" in user_query.lower():
        data = fetch_data_from_api("get_total_revenue")
    elif "invoices" in user_query.lower():
        data = fetch_data_from_api("get_invoices", {"period": "last_week"})
    elif "highest revenue" in user_query.lower():
        data = fetch_data_from_api("get_highest_revenue_day")
    elif "how many products" in user_query.lower():
        data = fetch_data_from_api("get_product_count")
    elif "product categories" in user_query.lower():
        data = fetch_data_from_api("get_categories")
    else:
        data = fetch_data_from_api("get_data")  # Fallback

    response_template = """
You are an AI-powered data analyst. Generate a natural language response based on:
- User Question: {question}
- Query Results: {response}
- Chat History: {chat_history}

Guidelines:
1. Be clear and concise
2. Highlight key insights from the data
3. Use a professional yet friendly tone
4. Address any data limitations if applicable
"""
    response_prompt = ChatPromptTemplate.from_template(response_template)

    chain = (
        RunnablePassthrough.assign(response=lambda x: json.dumps(data if data else "No data available"))
        | response_prompt
        | ChatGroq(model=aggregator_model, temperature=0.2, api_key=os.getenv("GROQ_API_KEY"))
        | StrOutputParser()
    )

    return chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })

def main():
    st.set_page_config(page_title="SCC School Store",
                      page_icon=":speech_balloon:", layout="wide")
    st.title("Chat with SCC School Store AI")

    st.markdown(""" 
    <style>
    .stChatInput {
        position: fixed;
        bottom: 0;
        width: 100%;
        background-color: white;
        z-index: 1000;
    }
    .stChatMessage {
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            AIMessage(content="Hello! I'm a SCC School Store assistant. Ask me anything about your store."),
        ]

    with st.sidebar:
        st.image("ui/CHAT-MYSQL-GUI/src/img/SCC.png", use_container_width=True)

        questions = [
            "What are the best-selling products?",
            "Show me the sales data for last month.",
            "Which products are out of stock?",
            "What is the total revenue this year?",
            "List all invoices from last week.",
            "Which day generated the highest revenue?",
            "How many products do we have?",
            "What are the product categories we have?"
        ]

        st.markdown("### Quick Queries")
        for question in questions:
            if st.button(question):
                st.session_state.chat_history.append(HumanMessage(content=question))
                with st.chat_message("Human"):
                    st.markdown(question)
                response = get_response(question, st.session_state.chat_history)
                st.session_state.chat_history.append(AIMessage(content=response))
                with st.chat_message("AI"):
                    st.markdown(response)

    # Display chat history
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human"):
                st.markdown(message.content)

    # Handle user input
    user_query = st.chat_input("Type a message...")
    if user_query:
        st.session_state.chat_history.append(HumanMessage(content=user_query))
        with st.chat_message("Human"):
            st.markdown(user_query)
        response = get_response(user_query, st.session_state.chat_history)
        st.session_state.chat_history.append(AIMessage(content=response))
        with st.chat_message("AI"):
            st.markdown(response)

if __name__ == "__main__":
    main()