import streamlit as st
import requests
import json
from urllib.parse import quote  # Added for URL encoding
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

def main():
    # Initialize page config first
    st.set_page_config(
        page_title="SCC School Store",
        page_icon=":speech_balloon:",
        layout="wide"
    )
    
    # Debugging section
    st.write("Secrets Verification:", {
        "API_URL": "API_URL" in st.secrets,
        "API_KEY": "API_KEY" in st.secrets,
        "GROQ_API_KEY": "GROQ_API_KEY" in st.secrets
    })

    try:
        # Access secrets
        API_URL = st.secrets["API_URL"]
        API_KEY = st.secrets["API_KEY"]
        GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
    except KeyError as e:
        st.error(f"Missing required secret: {str(e)}")
        st.stop()

    # UI Components
    st.title("Chat with AcaSquad AI")
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

    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            AIMessage(content="Hello! I'm a AcaSquad AI assistant. Ask me anything about your store."),
        ]

    # Sidebar components
    with st.sidebar:
        st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
        
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
                handle_query(question)

    # Display chat history
    display_chat_history()

    # Handle user input
    user_query = st.chat_input("Type a message...")
    if user_query:
        handle_query(user_query)

def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human"):
        st.markdown(query)
    
    with st.spinner("Generating response..."):
        response = get_response(query, st.session_state.chat_history)
    
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
            # URL encode the query parameter
            if 'query' in params:
                params['query'] = quote(params['query'])
            payload.update(params)
        
        response = requests.get(
            st.secrets["API_URL"],
            params=payload,
            timeout=10
        )
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

def get_sql_chain():
    template = """
    You are an AI assistant helping a user retrieve data from the SCC School Store Database via an API.
    Based on the provided table schema, generate an accurate SQL query to answer the user's question.
    
    Database Schema:
    - categories
    - employees
    - inventory_logs
    - invoices
    - invoice_details
    - products
    - user_logins
    
    Ensure proper joins and conditions considering foreign key relationships.
    
    <SCHEMA>
    {schema}
    </SCHEMA>
    
    Conversation History: {chat_history}
    
    Provide only the SQL query as output.
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    proposal_llms = [ChatGroq(model=model, temperature=0, api_key=st.secrets["GROQ_API_KEY"]) for model in [
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "llama3-70b-8192",
        "gemma2-9b-it",
    ]]
    
    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser() for i, llm in enumerate(proposal_llms)}
    )
    
    aggregator_template = """
    Synthesize the best SQL query from these proposals:
    {proposals}
    
    Original Question: {question}
    Schema: {schema}
    
    Criteria:
    1. Accuracy - Correct tables and joins
    2. Efficiency - Optimized performance
    3. Security - SQL injection prevention
    4. Standards - SQL best practices
    
    Return ONLY the final SQL query.
    """
    
    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)
    
    return (
        RunnablePassthrough.assign(
            schema=lambda _: json.dumps({
                "tables": ["categories", "employees", "inventory_logs", 
                          "invoices", "invoice_details", "products", "user_logins"]
            }, indent=2)
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
    query = sql_chain.invoke({
        "question": user_query,
        "chat_history": chat_history
    })
    
    # Debugging: Uncomment to see generated SQL
    # st.write(f"Generated SQL: {query}")
    
    data = fetch_data_from_api("execute_query", {"query": query})
    if not data:
        return "Sorry, I couldn't retrieve the data. Please try again."
    
    response_template = """
    Generate a natural language response based on:
    - Question: {question}
    - Results: {response}
    - History: {chat_history}
    
    Guidelines:
    1. Clear and concise
    2. Highlight key insights
    3. Professional yet friendly tone
    4. Note data limitations if any
    """
    
    response_prompt = ChatPromptTemplate.from_template(response_template)
    chain = (
        RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
        | response_prompt
        | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
    
    return chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })

if __name__ == "__main__":
    main()
