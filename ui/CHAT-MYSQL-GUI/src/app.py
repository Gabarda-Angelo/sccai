import streamlit as st
import requests
import json
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

# Access secrets from Streamlit Cloud
API_URL = st.secrets["API_URL"]  # e.g., "https://bookstoreadmin.shop/bookstoreapi.php"
API_KEY = st.secrets["API_KEY"]  # e.g., "x7k9p2m4q8v3n6t1j5"
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# Model configuration
proposal_models = [
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "llama3-70b-8192",
    "gemma2-9b-it",
]
aggregator_model = "llama3-70b-8192"

# Function to fetch data from API
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
            st.error(f"API Error: {data.get('error', 'Unknown error')}")
            return None
    except requests.RequestException as e:
        st.error(f"API request failed: {str(e)}")
        return None

# Mixture of Agents: SQL query generation
def get_sql_chain():
    template = """
    You are an AI assistant helping a user retrieve data from the SCC School Store Database via an API.
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

    proposal_llms = [ChatGroq(model=model, temperature=0, api_key=GROQ_API_KEY) for model in proposal_models]

    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser() for i, llm in enumerate(proposal_llms)}
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
        | ChatGroq(model=aggregator_model, temperature=0, api_key=GROQ_API_KEY)
        | StrOutputParser()
    )

# Function to get response via API
def get_response(user_query: str, chat_history: list):
    sql_chain = get_sql_chain()
    query = sql_chain.invoke({"question": user_query, "chat_history": chat_history})
    st.write(f"Generated SQL Query: {query}")  # Debugging, remove in production

    # Send the generated query to the API
    data = fetch_data_from_api("execute_query", {"query": query})
    if data:
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
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | response_prompt
            | ChatGroq(model=aggregator_model, temperature=0.2, api_key=GROQ_API_KEY)
            | StrOutputParser()
        )

        return chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
        })
    return "Sorry, I couldn’t retrieve the data. Please try again."

# Streamlit UI
def main():
    st.set_page_config(page_title="SCC School Store", page_icon=":speech_balloon:", layout="wide")
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
                with st.spinner("Generating response..."):
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
        with st.spinner("Generating response..."):
            response = get_response(user_query, st.session_state.chat_history)
        st.session_state.chat_history.append(AIMessage(content=response))
        with st.chat_message("AI"):
            st.markdown(response)

if __name__ == "__main__":
    main()