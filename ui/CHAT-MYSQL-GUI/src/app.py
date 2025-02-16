import os
import re
import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_community.utilities import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

# Load environment variables
load_dotenv()

# Model configuration
proposal_models = [
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "llama3-70b-8192",
    "gemma2-9b-it",
]
aggregator_model = "llama3-70b-8192"

# Fetch API keys from environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"

if LANGCHAIN_TRACING_V2:
    from langchain.globals import set_debug
    set_debug(True)

# Initialize the database connection
def init_database(user: str, password: str, host: str, port: str, database: str) -> SQLDatabase:
    db_uri = f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
    return SQLDatabase.from_uri(db_uri)

# Validate and clean SQL queries (e.g., fix escaped underscores)
def validate_sql_query(query: str) -> str:
    return re.sub(r"\\_", "_", query)

# Execute SQL query with error handling
def run_sql_query(db, query: str):
    try:
        return db.run(query)
    except Exception as e:
        return f"SQL Execution Error: {str(e)}"

# Generate SQL query using the MoA approach
def get_sql_chain(db):
    template = """
You are an AI assistant tasked with generating an accurate SQL query for the SCC School Store Database (school_store_db).
The schema consists of the following tables:
- categories
- employees
- inventory_logs
- invoices
- invoice_details
- products
- user_logins

Ensure that your query correctly uses table joins and adheres to the foreign key constraints.
Schema Details:
{schema}

Conversation History: {chat_history}

Provide only the SQL query as output without any extra commentary or formatting.
"""
    prompt = ChatPromptTemplate.from_template(template)
    proposal_llms = [ChatGroq(model=model, temperature=0, api_key=GROQ_API_KEY) for model in proposal_models]
    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser() for i, llm in enumerate(proposal_llms)}
    )
    
    aggregator_template = """
You are a senior SQL expert. Given the following SQL query proposals:

{proposals}

And considering the original question:
{question}

And the database schema:
{schema}

Select or synthesize the best SQL query that is accurate, efficient, and secure.
Return only the final SQL query.
"""
    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)
    
    return (
        RunnablePassthrough.assign(schema=lambda _: db.get_table_info())
        | RunnablePassthrough.assign(
            proposals=proposal_chain,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | aggregator_prompt
        | ChatGroq(model=aggregator_model, temperature=0, api_key=GROQ_API_KEY)
        | StrOutputParser()
    )

# Generate a natural language response based on the SQL query and results
def get_response(user_query: str, db: SQLDatabase, chat_history: list):
    sql_chain = get_sql_chain(db)
    
    response_template = """
You are an experienced data analyst. Using the following:
- User Question: {question}
- Generated SQL Query: {query}
- Query Results: {response}
- Database Schema: {schema}
- Conversation History: {chat_history}

Craft a clear and accurate natural language response summarizing the insights from the data.
Ensure the answer is factual and directly addresses the question.
Return only the final response.
"""
    response_prompt = ChatPromptTemplate.from_template(response_template)
    response_proposals = RunnableParallel(
        **{f"proposal_{i}": response_prompt | llm | StrOutputParser() for i, llm in enumerate(
            [ChatGroq(model=model, temperature=0.2, api_key=GROQ_API_KEY) for model in proposal_models]
        )}
    )
    response_aggregator_template = """
You are a seasoned analyst. Review the following responses:

{proposals}

Given:
- Original Question: {question}
- SQL Query Used: {query}
- Database Results: {response}

Synthesize a final, accurate, and clear response that summarizes the data and answers the question completely.
Return only the final response.
"""
    response_aggregator_prompt = ChatPromptTemplate.from_template(response_aggregator_template)
    
    chain = (
        RunnablePassthrough.assign(
            query=sql_chain,
            schema=lambda _: db.get_table_info(),
        )
        .assign(
            response=lambda x: run_sql_query(db, validate_sql_query(x["query"]))
        )
        | RunnablePassthrough.assign(
            proposals=response_proposals,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | response_aggregator_prompt
        | ChatGroq(model=aggregator_model, temperature=0.2, api_key=GROQ_API_KEY)
        | StrOutputParser()
    )
    
    return chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })

# Main Streamlit app
def main():
    st.set_page_config(page_title="SCC School Store", page_icon=":speech_balloon:", layout="wide")
    
    st.title("Chat with SCC School Store AI")
    
    st.markdown("""
    <style>
    /* Style the chat input's inner text field directly */
    .stChatInput input {
        border: 2px solid #ccc !important;  /* Thicker border */
        padding: 10px 40px 10px 10px;         /* Extra right padding for the icon */
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='%23888' viewBox='0 0 24 24'%3E%3Cpath d='M12 2L10.59 3.41 18.17 11H2v2h16.17l-7.58 7.59L12 22l10-10L12 2z'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 10px center;
        background-size: 20px 20px;
    }
    .stChatMessage {
        margin-bottom: 20px;
    }
    .stHorizontalBlock {
        display: flex;
        overflow-x: auto;
        margin-bottom: 10px;
    }
    .stHorizontalBlock button {
        flex: 0 0 auto;
        margin-right: 10px;
    }
    </style>
    """, unsafe_allow_html=True)
    
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [AIMessage(content="Hello! I'm the SCC School Store assistant. How may I help you today?")]
    
    with st.sidebar:
        st.image("ui/CHAT-MYSQL-GUI/src/img/SCC.png", caption="SCC School Store Chat", use_container_width=True)

        with st.spinner("Connecting to database..."):
            db = init_database(
                user="root2",
                password="password",
                host="localhost",
                port="3306",
                database="school_store_db"
            )
            st.session_state.db = db
            st.success("Connected to database!")
        
        st.markdown("### Ready to Ask Questions")
        questions = [
            "What are the best-selling products?",
            "Show me the sales data for last month.",
            "Which products are out of stock?",
            "What is the total revenue this year?",
            "List all invoices from last week.",
            "Which day generated the highest revenue?",
            "How many products do we have?",
            "What are the product categories available?"
        ]
        
        for question in questions:
            if st.button(question):
                st.session_state.chat_history.append(HumanMessage(content=question))
                with st.chat_message("Human", avatar="ui/CHAT-MYSQL-GUI/src/img/human_icon.jpeg"):
                    st.markdown(question)
                with st.chat_message("AI", avatar="ui/CHAT-MYSQL-GUI/src/img/ai_icon.jpeg"):
                    response = get_response(question, st.session_state.db, st.session_state.chat_history)
                    st.markdown(response)
                st.session_state.chat_history.append(AIMessage(content=response))
    
    # Display the chat history
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="ui/CHAT-MYSQL-GUI/src/img/ai_icon.jpeg"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="ui/CHAT-MYSQL-GUI/src/img/human_icon.jpeg"):
                st.markdown(message.content)
    
    # Chat input section
    user_query = st.chat_input("Type a message...")
    if user_query is not None and user_query.strip() != "":
        st.session_state.chat_history.append(HumanMessage(content=user_query))
        with st.chat_message("Human", avatar="ui/CHAT-MYSQL-GUI/src/img/human_icon.jpeg"):
            st.markdown(user_query)
        with st.chat_message("AI", avatar="ui/CHAT-MYSQL-GUI/src/img/ai_icon.jpeg"):
            response = get_response(user_query, st.session_state.db, st.session_state.chat_history)
            st.markdown(response)
        st.session_state.chat_history.append(AIMessage(content=response))

if __name__ == "__main__":
    main()
