import streamlit as st
import requests
import json
from urllib.parse import quote
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

def main():
    # Initialize page config
    st.set_page_config(
        page_title="AcaSquad AI",
        page_icon=":speech_balloon:",
        layout="wide"
    )

    # UI Components
    st.title("Chat with our AcaSquad AI")
    st.markdown("""
    <style>
    .stChatInput {
        bottom: 20px;
        left: 10%;
        z-index: 1000;
    }
    .stChatMessage {
        margin-bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

    # Chat history initialization
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            AIMessage(content="Hello! I will be your assistant. Ask me anything about your store."),
        ]

    # Sidebar components
    with st.sidebar:
        st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)

        quick_queries = [
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
        for q in quick_queries:
            if st.button(q):
                handle_query(q)

    # Display chat history
    display_chat_history()

    # User input handling
    user_query = st.chat_input("Type a message...")
    if user_query:
        handle_query(user_query)

def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human"):
        st.markdown(query)

    with st.spinner("Analyzing your query..."):
        try:
            response = get_response(query, st.session_state.chat_history)
        except Exception as e:
            response = f"An error occurred: {str(e)}"

    st.session_state.chat_history.append(AIMessage(content=response))
    with st.chat_message("AI"):
        st.markdown(response)

def display_chat_history():
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human"):
                st.markdown(message.content)

def fetch_data_from_api(action: str, params: dict = None) -> dict:
    try:
        payload = {"action": action, "key": st.secrets["API_KEY"]}
        if params:
            if 'query' in params:
                st.session_state.last_query = params['query']
                params['query'] = quote(params['query'])
            payload.update(params)

        response = requests.get(
            st.secrets["API_URL"],
            params=payload,
            timeout=15
        )

        if not response.text.strip():
            st.error("Received empty response from API")
            return None

        try:
            data = response.json()
        except json.JSONDecodeError:
            st.error(f"Invalid JSON response: {response.text[:200]}...")
            return None

        if data.get("status") == "success":
            return data["data"]
        else:
            error_msg = data.get('error', 'Unknown error')
            st.error(f"API Error: {error_msg}")
            return None

    except requests.RequestException as e:
        st.error(f"Connection error: {str(e)}")
        return None

def get_sql_chain():
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at
    - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address
    """

    template = """
    You are an AI assistant helping a user retrieve data from the SCC School Store Database via an API.
    Based on the provided table schema, generate an accurate SQL query to answer the user's question.

    Database Schema:
    {schema}

    Conversation History: {chat_history}

    Instructions:
    - Use appropriate joins when data from multiple tables is needed.
    - Consider foreign key relationships between tables.
    - Use aggregate functions (e.g., SUM, COUNT, AVG) if the question implies summarization.
    - Filter data based on conditions mentioned in the question.
    - Order results if the question suggests a specific order.
    - Assume the most common interpretation if the question is ambiguous, and add a comment (e.g., -- Assuming...) in the query.
    - Provide only the SQL query as output, without explanations.

    User Question: {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "llama3-70b-8192",
        "gemma2-9b-it",
    ]

    proposal_llms = [ChatGroq(
        model=model,
        temperature=0,
        api_key=st.secrets["GROQ_API_KEY"]
    ) for model in models]

    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser()
           for i, llm in enumerate(proposal_llms)}
    )

    aggregator_template = """
    Synthesize the best SQL query from these proposals:
    {proposals}

    Original Question: {question}
    Schema: {schema}

    Return ONLY the final SQL query without any explanations or formatting.
    The query must:
    1. Start with SELECT
    2. Use explicit JOIN syntax
    3. Include proper table aliases
    4. Contain no comments or markdown
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)

    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema
        )
        | RunnablePassthrough.assign(
            proposals=proposal_chain,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | aggregator_prompt
        | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )

def get_response(user_query: str, chat_history: list) -> str:
    sql_chain = get_sql_chain()
    raw_query = sql_chain.invoke({
        "question": user_query,
        "chat_history": chat_history
    })

    # Clean and validate SQL query
    query = raw_query.split(";")[0] + ";"
    query = query.replace("```sql", "").replace("```", "").strip()
    query = "\n".join([line for line in query.split("\n")
                      if not line.strip().startswith(("--", "#", "/*"))])

    if not query.lower().startswith("select"):
        st.error(f"Invalid query generated: {query}")
        return "Failed to generate valid database query. Please try again."

    data = fetch_data_from_api("execute_query", {"query": query})
    if not data:
        return "Couldn't retrieve data. Please try again or rephrase your question."

    response_template = """
    Generate a natural language response based on:
    - Question: {question}
    - Results: {response}
    - History: {chat_history}

    Guidelines:
    1. If results are empty, suggest possible reasons or alternative queries.
    2. Be clear and concise.
    3. Highlight key numbers or trends.
    4. Use bullet points for lists.
    5. Mention any data limitations.
    6. Keep under 200 words.
    """

    chain = (
        RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
        | ChatPromptTemplate.from_template(response_template)
        | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )

    return chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })

if __name__ == "__main__":
    main()
