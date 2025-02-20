import time
import logging
import json
from dotenv import load_dotenv
import os
import re
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_community.utilities import SQLDatabase
from langchain_groq import ChatGroq
from sshtunnel import SSHTunnelForwarder, BaseSSHTunnelForwarderError
import sshtunnel
import socket
from sqlalchemy import text
from contextlib import closing

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("sshtunnel_debug.log"),
        logging.StreamHandler()
    ]
)
sshtunnel.DEFAULT_LOGLEVEL = logging.DEBUG

# Load environment variables
load_dotenv(override=True)

# Model configuration
proposal_models = [
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "llama3-70b-8192",
    "gemma2-9b-it",
]
aggregator_model = "llama3-70b-8192"


def validate_env():
    required_vars = [
        "GROQ_API_KEY", "SSH_HOST", "SSH_PORT", "SSH_USERNAME",
        "SSH_PRIVATE_KEY_PATH", "DB_USER", "DB_PASSWORD", "DB_NAME"
    ]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}")


validate_env()


def validate_sql_query(query: str) -> str:
    return re.sub(r"\\_", "_", query)


def init_database_via_ssh():
    ssh_host = os.getenv("SSH_HOST")
    ssh_port = int(os.getenv("SSH_PORT", 21098))
    ssh_username = os.getenv("SSH_USERNAME")
    ssh_pkey = os.getenv("SSH_PRIVATE_KEY_PATH")
    # With your key now without a passphrase, this will be empty or None
    ssh_key_password = os.getenv("SSH_PRIVATE_KEY_PASSWORD") or None

    # Enhanced network diagnostics
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(15)
            result = sock.connect_ex((ssh_host, ssh_port))

            st.markdown(f"""
            **Network Diagnostics:**
            - Target Server: `{ssh_host}:{ssh_port}`
            - Resolved IP: `{socket.gethostbyname(ssh_host)}`
            - Connection Result: `{result} ({os.strerror(result)})`
            """)

            if result != 0:
                st.error("""
                **Critical Connectivity Issue**
                1. Verify server firewall allows port 21098
                2. Check network outbound rules
                3. Confirm SSH service is running
                """)
                raise ConnectionError(
                    f"SSH server unreachable (error code: {result})")

    except Exception as e:
        st.error(f"Network pre-check failed: {str(e)}")
        raise

    server = SSHTunnelForwarder(
        (ssh_host, ssh_port),
        ssh_username=ssh_username,
        ssh_pkey=ssh_pkey,
        ssh_private_key_password=ssh_key_password,
        remote_bind_address=("127.0.0.1", 3306),
        local_bind_address=("127.0.0.1", 5522),  # Explicitly set local port
        set_keepalive=30,
        allow_agent=False,
    )

    try:
        server.start()
        st.success(
            f"SSH tunnel established on local port {server.local_bind_port}")
        logging.info(f"Tunnel status: {server.tunnel_is_up()}")
    except BaseSSHTunnelForwarderError as e:
        st.error(f"""
        **SSH Connection Failed**
        Possible issues:
        - Invalid credentials
        - Network restrictions
        - Firewall blocking
        - Key format issues
        
        Technical details: {str(e)}
        """)
        raise

    # Database connection with retry logic
    max_retries = 3
    delay = 1  # start with a 1-second delay
    for attempt in range(max_retries):
        try:
            # Attempt to connect to the database
            db_user = os.getenv("DB_USER")
            db_password = os.getenv("DB_PASSWORD")
            db_name = os.getenv("DB_NAME")
            db_uri = f"mysql+mysqlconnector://{db_user}:{db_password}@127.0.0.1:5522/{db_name}?allow_local_infile=true"
            db = SQLDatabase.from_uri(db_uri)
            with db._engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            st.success("Database connection validated!")
            return db, server

        except Exception as e:
            if attempt == max_retries - 1:
                st.error(
                    f"Database connection failed after {max_retries} attempts: {str(e)}")
                server.stop()  # Use stop() to close the tunnel properly
                raise
            logging.warning(
                f"Connection attempt {attempt+1} failed, retrying in {delay} seconds...")
            st.warning(
                f"Connection attempt {attempt+1} failed, retrying in {delay} seconds...")
            time.sleep(delay)
            delay *= 2  # double the delay for next retry


def get_sql_chain(db):
    template = """
You are an AI assistant helping a user retrieve data from the SCC School Store Database (school_store_db).
Based on the provided table schema, generate an accurate SQL query to answer the user's question.
The schema includes the following tables: 
- categories
- employees
- inventory_logs
- invoices
- invoice_details
- products
- user_logins

Ensure you use the appropriate joins and conditions considering foreign key constraints and data integrity.

<SCHMEA>
{schema}
</SCHMEA>

Conversation History: {chat_history}

Provide only the SQL query as output—without any additional text, explanations, or formatting.
Do not enclose the query in backticks or other characters.
Escape table or column names only if absolutely necessary.
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
        RunnablePassthrough.assign(
            schema=lambda _: json.dumps(db.get_table_info, indent=2))
        | RunnablePassthrough.assign(
            proposals=proposal_chain,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | aggregator_prompt
        | ChatGroq(model=aggregator_model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
        | StrOutputParser()
    )


def get_response(user_query: str, db: SQLDatabase, chat_history: list):
    sql_chain = get_sql_chain(db)

    response_template = """
You are an AI-powered data analyst. Generate a natural language response based on:
- User Question: {question}
- SQL Query: {query}
- Query Results: {response}
- Schema: {schema}
- Chat History: {chat_history}

Guidelines:
1. Be clear and concise
2. Highlight key insights from the data
3. Use a professional yet friendly tone
4. Address any data limitations if applicable
"""
    response_prompt = ChatPromptTemplate.from_template(response_template)

    response_proposals = RunnableParallel(
        **{f"proposal_{i}": response_prompt | llm | StrOutputParser()
           for i, llm in enumerate([
               ChatGroq(model=model, temperature=0.2,
                        api_key=os.getenv("GROQ_API_KEY"))
               for model in proposal_models
           ])}
    )

    response_aggregator_template = """
Synthesize the best response from these analyst proposals:

{proposals}

Original Question: {question}
SQL Query Used: {query}
Database Results: {response}

Provide a final answer that:
1. Combines the clearest insights
2. Maintains technical accuracy
3. Is most user-friendly
4. Addresses all aspects of the question

Return ONLY the final response without any metadata or explanations.
"""
    response_aggregator_prompt = ChatPromptTemplate.from_template(
        response_aggregator_template)

    chain = (
        RunnablePassthrough.assign(
            query=sql_chain,
            schema=lambda _: json.dumps(db.get_table_info, indent=2)
        )
        .assign(
            response=lambda x: db.run(validate_sql_query(x["query"])),
        )
        | RunnablePassthrough.assign(
            proposals=response_proposals,
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | response_aggregator_prompt
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
            AIMessage(
                content="Hello! I'm a SCC School Store assistant. Ask me anything about your store."),
        ]

    with st.sidebar:
        st.image("ui/CHAT-MYSQL-GUI/src/img/SCC.png", use_container_width=True)

        if 'db' not in st.session_state or 'tunnel' not in st.session_state:
            try:
                with st.spinner("Establishing secure connection..."):
                    db, tunnel = init_database_via_ssh()
                    st.session_state.db = db
                    st.session_state.tunnel = tunnel

            except Exception as e:
                st.error(f"""
                **Critical Connection Failure**
                {str(e)}
                
                Troubleshooting steps:
                1. Verify SSH credentials in .env file
                2. Check server firewall settings
                3. Confirm database credentials
                4. Test network connectivity
                """)
                if 'tunnel' in st.session_state:
                    st.session_state.tunnel.stop()
                st.stop()

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
                st.session_state.chat_history.append(
                    HumanMessage(content=question))
                with st.chat_message("Human"):
                    st.markdown(question)
                response = get_response(
                    question, st.session_state.db, st.session_state.chat_history)
                st.session_state.chat_history.append(
                    AIMessage(content=response))
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
        response = get_response(
            user_query, st.session_state.db, st.session_state.chat_history)
        st.session_state.chat_history.append(AIMessage(content=response))
        with st.chat_message("AI"):
            st.markdown(response)

    # Cleanup on app exit
    if 'tunnel' in st.session_state:
        st.session_state.tunnel.stop()


if __name__ == "__main__":
    main()
