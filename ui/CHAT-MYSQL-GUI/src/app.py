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

# Set page configuration
st.set_page_config(
    page_title="AcaSquad AI",
    page_icon=":speech_balloon:",
    layout="wide"
)

# Initialize session state for authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
    ]

# Function to authenticate user via API
def authenticate(email, password):
    try:
        response = requests.post(
            st.secrets["API_URL"],
            params={"action": "authenticate_user", "key": st.secrets["API_KEY"]},
            json={"email": email, "password": password}
        )
        data = response.json()
        if response.status_code == 200 and data.get("status") == "success":
            st.session_state.authenticated = True
            st.session_state.user = data["data"]
            return True
        st.error(f"Login failed: {data.get('error', 'Invalid credentials')}")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
    return False

# Function to validate SQL queries
def validate_query(query):
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        return False
    forbidden_keywords = ["DELETE", "UPDATE", "INSERT", "DROP", "ALTER"]
    return not any(kw in query_upper for kw in forbidden_keywords)

# Function to validate query semantics
def validate_query_semantics(query, question, schema):
    try:
        query_lower = query.lower()
        question_lower = question.lower()
        
        # Date-specific validation
        if "april" in question_lower:
            date_str = "2025-04-" + ("13" if "13" in question_lower else "12" if "12" in question_lower else "14")
            if "where" not in query_lower or date_str not in query_lower:
                return False
        
        # Employee transaction validation
        if "employee" in question_lower and "transaction" in question_lower:
            if "employees" not in query_lower or "invoices" not in query_lower or "join" not in query_lower:
                return False
        
        # Invoice details validation
        if "invoice" in question_lower:
            if "invoices" not in query_lower:
                return False
        
        # Financial metrics validation
        if any(kw in question_lower for kw in ["revenue", "profit", "base cost", "total invoice"]):
            if "sum" not in query_lower or "invoices" not in query_lower:
                return False
        
        # Login validation
        if "log" in question_lower and "employee" in question_lower:
            if "user_logins" not in query_lower:
                return False
        
        return True
    except Exception:
        return False

# Function to fetch data from API
@st.cache_data
def fetch_data_from_api(action: str, params: dict = None) -> dict:
    try:
        payload = {"action": action, "key": st.secrets["API_KEY"]}
        if params:
            if "query" in params:
                params["query"] = quote(params["query"])
            payload.update(params)
        response = requests.get(st.secrets["API_URL"], params=payload, timeout=15)
        data = response.json()
        if data.get("status") == "success":
            return data["data"]
        st.error(f"API Error: {data.get('error', 'Unknown error')}")
        return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Function to generate SQL chain
def get_sql_chain():
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at, updated_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address, created_at, updated_at
    """
    template = """
    You are an expert SQL assistant for the SCC School Store Database.
    Given the schema and user query, generate a valid SQL query.

    **Schema:** {schema}
    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)

    **Instructions:**
    - For dates like "April 13, 2025", use WHERE order_date = '2025-04-13'.
    - For invoice details, join invoices with invoice_details and products.
    - For transactions by employee, join employees with invoices.
    - For revenue, use SUM(i.total); for profit, use SUM(id.total_price - id.quantity * p.purchase_price).
    - For profit margin, use (profit / SUM(i.total) * 100).
    - Use INNER JOIN for all joins.
    - Return only the SQL query.

    **User Query:** {question}
    """
    prompt = ChatPromptTemplate.from_template(template)
    model = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
    
    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda _: datetime.datetime.now(pytz.timezone('Asia/Singapore')).strftime('%Y-%m-%d')
        )
        | prompt
        | model
        | StrOutputParser()
    )

# Function to generate response
def get_response(user_query: str, chat_history: list):
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at, updated_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address, created_at, updated_at
    """
    
    sql_chain = get_sql_chain()
    query = sql_chain.invoke({"question": user_query})
    query = query.split(";")[0] + ";"
    
    if not validate_query(query) or not validate_query_semantics(query, user_query, schema):
        log_data = {
            "query": user_query,
            "generated_sql": query,
            "error": "Validation failed",
            "timestamp": datetime.datetime.now().isoformat()
        }
        with open("query_log.json", "a") as f:
            json.dump(log_data, f)
            f.write("\n")
        return "No data found for this query. Please try a more specific question or check the sidebar for suggestions.", None

    data = fetch_data_from_api("execute_query", {"query": query})
    if data is None or (isinstance(data, list) and not data):
        log_data = {
            "query": user_query,
            "generated_sql": query,
            "error": "No data returned",
            "timestamp": datetime.datetime.now().isoformat()
        }
        with open("query_log.json", "a") as f:
            json.dump(log_data, f)
            f.write("\n")
        return f"No records found for '{user_query}'. Try checking another date or query.", None

    response_template = """
    Based on the query "{question}" and results:

    **Results:** {response}

    Provide a concise natural language response:
    - Use markdown for clarity (e.g., **bold**, - lists).
    - For monetary values, use ₱ and 2 decimal places.
    - Highlight key insights (e.g., highest value).
    - If no data, state clearly.
    - Keep under 150 words.
    """
    chain = (
        RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
        | ChatPromptTemplate.from_template(response_template)
        | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
    
    natural_response = chain.invoke({"question": user_query})
    return natural_response, data

# Function to determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower()]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    
    if date_columns and numerical_columns:
        return "line", (date_columns[0], numerical_columns[0])
    elif categorical_columns and numerical_columns:
        return "bar", (categorical_columns[0], numerical_columns[0])
    return None, None

# Function to handle queries
def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human"):
        st.markdown(query)
    
    with st.spinner("Analyzing..."):
        natural_response, data = get_response(query, st.session_state.chat_history)
    
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and data:
            df = pd.DataFrame(data)
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["total", "subtotal", "discount", "paid", "due", "price", "revenue", "profit"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                fig, ax = plt.subplots()
                if chart_type == 'bar':
                    df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                    ax.set_title(f"{columns[1]} by {columns[0]}")
                elif chart_type == 'line':
                    df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                    ax.set_title(f"{columns[1]} Over Time")
                st.pyplot(fig)
            st.table(df)

# Main application
def main():
    if not st.session_state.authenticated:
        st.title("Login to AcaSquad AI")
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                if authenticate(email, password):
                    st.rerun()
    else:
        st.title("Chat with AcaSquad AI")
        with st.sidebar:
            st.markdown(f"Logged in as {st.session_state.user['first_name']} ({st.session_state.user['role']})")
            if st.button("Logout"):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.rerun()
            if st.button("Clear Chat"):
                st.session_state.chat_history = [
                    AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
                ]
                st.rerun()
            
            with st.expander("📈 Sales"):
                sales_queries = [
                    "Sales invoices details for April 14, 2025",
                    "Total revenue for April 14, 2025",
                    "Best-selling products today"
                ]
                for q in sales_queries:
                    if st.button(q):
                        handle_query(q)
            
            with st.expander("👥 Employees"):
                emp_queries = [
                    "Employees logged in on April 14, 2025",
                    "Top employee by transactions on April 14, 2025"
                ]
                for q in emp_queries:
                    if st.button(q):
                        handle_query(q)
        
        for msg in st.session_state.chat_history:
            with st.chat_message("AI" if isinstance(msg, AIMessage) else "Human"):
                st.markdown(msg.content)
        
        if user_query := st.chat_input("Ask about your store..."):
            handle_query(user_query)

if __name__ == "__main__":
    main()

# Hide Streamlit default UI elements
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
