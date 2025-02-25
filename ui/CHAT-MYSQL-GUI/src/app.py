import streamlit as st
import requests
import json
import pandas as pd
import matplotlib.pyplot as plt
from urllib.parse import quote
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
import datetime
import pytz
from sqlalchemy import create_engine, text
from passlib.hash import bcrypt

# Database connection setup
engine = create_engine(
    f"mysql+mysqlconnector://{st.secrets['database']['username']}:{st.secrets['database']['password']}@{st.secrets['database']['host']}/{st.secrets['database']['dbname']}"
)

def verify_credentials(email, password):
    """Verify user credentials against the database."""
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM employees WHERE email = :email")
            result = conn.execute(query, {"email": email})
            row = result.fetchone()
            if row:
                user = dict(row._mapping)
                if bcrypt.verify(password, user['password_hash']):
                    return user
            return None
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return None

def main():
    # Initialize session state for authentication
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.first_name = None
        st.session_state.last_name = None
        st.session_state.email = None

    if not st.session_state.logged_in:
        # Display login page
        st.title("Login to AcaSquad AI")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            user = verify_credentials(email, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.employee_id = user['employee_id']
                st.session_state.first_name = user['first_name']
                st.session_state.last_name = user['last_name']
                st.session_state.email = user['email']
                st.session_state.role = user['role']
                st.rerun()  # Refresh to show main content
            else:
                st.error("Invalid email or password")
    else:
        # Check role-based access
        if st.session_state.role == 'Cashier':
            st.error("Sorry, you can't access this. Please contact the Admin.")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.rerun()
        else:
            # Main content for authorized users (Admin/Owner)
            st.set_page_config(
                page_title="AcaSquad AI",
                page_icon=":speech_balloon:",
                layout="wide"
            )
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

            if "chat_history" not in st.session_state:
                st.session_state.chat_history = [
                    AIMessage(content="Hello! I will be your assistant. Ask me anything about your store."),
                ]

            with st.sidebar:
                st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
                st.write(f"Logged in as: {st.session_state.first_name} {st.session_state.last_name} ({st.session_state.role})")
                if st.button("Logout"):
                    st.session_state.logged_in = False
                    st.rerun()
                st.markdown("""
                <a href="https://bookstoreadmin.shop/ui/pos.php" target="_blank" style="display: inline-block; width:100%; padding:10px; background-color:#f25570; border:none; cursor:pointer; color:white; text-align:center; text-decoration: none;">
                    Back
                </a>
                """, unsafe_allow_html=True)

                st.markdown("### Quick Queries")
                with st.expander("📈 Sales Performance", expanded=True):
                    sales_queries = [
                        "What are the best-selling products of all time?",
                        "What are the top 5 best-selling products this month?",
                        "Which product has the highest sales this week?",
                        "What are the best-selling products in each category?",
                        "Show me the sales trend over the past year.",
                        "What is the daily sales trend for this month?",
                        "Which day of the week has the highest sales?",
                        "What is the total revenue this year?",
                        "What is the total revenue for today?",
                        "What is the average daily revenue this month?",
                        "What is the revenue breakdown by product category?"
                    ]
                    for q in sales_queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q)
                # ... (rest of the expanders remain unchanged) ...

            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query)

# Rest of your original functions remain unchanged
def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            natural_response, data = get_response(query, st.session_state.chat_history)
        except Exception as e:
            natural_response = f"An error occurred: {str(e)}"
            data = None
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            monetary_columns = ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due"]
            for col in monetary_columns:
                if col in df.columns:
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                st.markdown(f"### {chart_type.capitalize()} Chart")
                try:
                    if chart_type == 'bar':
                        st.bar_chart(df.set_index(columns[0])[columns[1]])
                    elif chart_type == 'line':
                        st.line_chart(df.set_index(columns[0])[columns[1]])
                    elif chart_type == 'pie':
                        fig, ax = plt.subplots()
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        st.pyplot(fig)
                except Exception as e:
                    st.write(f"Chart rendering failed: {str(e)}")
            if len(df) > 1 or len(df.columns) > 1:
                st.table(df)

def display_chat_history():
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="dist/img/ai.png"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="dist/img/Human.png"):
                st.markdown(message.content)

# ... (fetch_data_from_api, get_sql_chain, get_response, determine_chart_type remain unchanged) ...

if __name__ == "__main__":
    main()

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)