
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Streamlit page configuration
st.set_page_config(page_title="SCC School Store Chatbot", page_icon="🏬", layout="wide")

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "user_authenticated" not in st.session_state:
    st.session_state.user_authenticated = False
if "cache" not in st.session_state:
    st.session_state.cache = {}

# Database schema (assumed from ltmptpysnd_school_store_db.sql)
SCHEMA = """
Tables:
- invoices (invoice_id, order_date, total, employee_id)
- invoice_details (invoice_id, product_id, quantity, total_price)
- products (product_id, product_name, category_id, stock, sale_price, purchase_price, reorder_level)
- categories (category_id, category_name)
- employees (employee_id, employee_name, role)
- void_logs (void_id, invoice_id, void_date)
- discount_logs (discount_id, invoice_id, discount_amount)
- admin_action_logs (log_id, admin_id, action, action_date)
"""

# Initialize embeddings and vector store
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")  # Original embedding model
documents = [SCHEMA] + [
    "sales data: invoices, invoice_details",
    "inventory: products, stock, reorder_level",
    "financials: invoices.total, discount_logs.discount_amount",
    "employees: employees.employee_name, employees.role"
]
vectorstore = FAISS.from_texts(documents, embeddings)

@st.cache_resource
def get_vectorstore():
    return vectorstore

def fetch_data_from_api(action: str, params: dict = None) -> Optional[Dict]:
    """Fetch data from the database API."""
    try:
        headers = {"Authorization": f"Bearer {os.getenv('API_TOKEN')}"}
        response = requests.post(
            os.getenv("API_URL"),
            json={"action": action, "params": params or {}},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"API request failed: {str(e)}")
        return None

def validate_query(query: str) -> bool:
    """Validate SQL query for safety and correctness."""
    try:
        # Check for SELECT statement
        query_upper = query.upper()
        if not query_upper.strip().startswith("SELECT"):
            logger.warning("Query is not a SELECT statement")
            st.error("Only SELECT queries are allowed.")
            return False
        
        # Check for forbidden keywords
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER"]
        if any(keyword in query_upper for keyword in forbidden):
            logger.warning("Forbidden keyword detected")
            st.error("Query contains forbidden operations.")
            return False
        
        # Validate table references
        tables = re.findall(r'\bFROM\s+([a-zA-Z_]+)\b|\bJOIN\s+([a-zA-Z_]+)\b', query, re.IGNORECASE)
        tables = [t for sublist in tables for t in sublist if t]
        valid_tables = ["invoices", "invoice_details", "products", "categories", "employees", "void_logs", "discount_logs", "admin_action_logs"]
        for table in tables:
            if table.lower() not in valid_tables:
                logger.warning(f"Invalid table: {table}")
                st.error(f"Table '{table}' is not valid.")
                return False
        
        return True
    except Exception as e:
        logger.error(f"Query validation failed: {str(e)}")
        st.error(f"Invalid query: {str(e)}")
        return False

def validate_results(data: List[Dict], query: str) -> bool:
    """Validate query results for consistency."""
    if not data:
        logger.warning("No data returned")
        return False
    if "revenue" in query.lower() or "total" in query.lower():
        return all(float(item.get("revenue", item.get("total", 0))) >= 0 for item in data)
    if "quantity" in query.lower():
        return all(int(item.get("quantity", 0)) >= 0 for item in data)
    return True

def fuzzy_match_text(text: str) -> List[Dict]:
    """Perform fuzzy matching with RAG."""
    try:
        vectorstore = get_vectorstore()
        results = vectorstore.similarity_search(text, k=3)
        entities = []
        for result in results:
            if "tables:" in result.page_content.lower():
                entities.append({"type": "schema", "value": result.page_content})
            elif "sales" in result.page_content.lower():
                entities.append({"type": "domain", "value": "sales"})
            elif "inventory" in result.page_content.lower():
                entities.append({"type": "domain", "value": "inventory"})
        return entities
    except Exception as e:
        logger.error(f"Fuzzy match failed: {str(e)}")
        return []

def expand_entities(matched_entities: List[Dict]) -> List[Dict]:
    """Expand matched entities based on schema relationships."""
    expanded = []
    for entity in matched_entities:
        if entity["type"] == "domain" and entity["value"] == "sales":
            expanded.append({"table": "invoices", "columns": ["total", "order_date"]})
            expanded.append({"table": "invoice_details", "columns": ["quantity", "total_price"]})
        elif entity["type"] == "domain" and entity["value"] == "inventory":
            expanded.append({"table": "products", "columns": ["product_name", "stock", "reorder_level"]})
    return expanded

def classify_query(query: str) -> str:
    """Classify query into a domain."""
    matched_entities = fuzzy_match_text(query)
    domains = [e["value"] for e in matched_entities if e["type"] == "domain"]
    
    if "sales" in domains or any(word in query.lower() for word in ["revenue", "sold", "invoices"]):
        return "sales"
    elif "inventory" in domains or any(word in query.lower() for word in ["stock", "products", "reorder"]):
        return "inventory"
    elif any(word in query.lower() for word in ["profit", "discount", "financial"]):
        return "financials"
    elif any(word in query.lower() for word in ["employee", "cashier", "admin"]):
        return "employees"
    return "misc"

def get_sql_chain(domain: str) -> Runnable:
    """Create a LangChain pipeline for SQL generation."""
    prompt_template = """
    You are a SQL expert for a school store database. Generate a SELECT query for the following user question based on the domain: {domain}.
    
    User Question: {query}
    Database Schema: {schema}
    
    Ensure the query:
    - Uses proper JOINs for related tables.
    - Filters out voided transactions using void_logs (e.g., LEFT JOIN void_logs ON invoices.invoice_id = void_logs.invoice_id WHERE void_logs.void_id IS NULL).
    - Includes discounts from discount_logs where applicable.
    - Handles date filters (e.g., today, this month) using CURDATE().
    - Returns results in a user-friendly format (e.g., meaningful column aliases).
    - Avoids aggregation errors (e.g., GROUP BY all non-aggregated columns).
    
    Output only the SQL query as a string.
    """
    prompt = ChatPromptTemplate.from_template(prompt_template)
    model = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
    return prompt | model | StrOutputParser()

def plan_multi_hop_query(query: str, schema: str) -> List[Dict[str, str]]:
    """Plan a multi-hop query for complex questions."""
    prompt_template = """
    You are a SQL query planner. Break down the following complex query into sequential SELECT query steps.
    
    User Question: {query}
    Database Schema: {schema}
    
    Output a JSON array of steps, each with:
    - description: Brief description of the step.
    - sql: SELECT query for the step (use placeholders like (previous_result) for intermediate results).
    
    Ensure steps:
    - Are executable and produce intermediate results.
    - Filter out voided transactions (void_logs).
    - Include discounts (discount_logs) where relevant.
    - Handle complex aggregations (e.g., profit margins, subqueries).
    """
    prompt = ChatPromptTemplate.from_template(prompt_template)
    model = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
    chain = prompt | model | StrOutputParser()
    
    try:
        plan = json.loads(chain.invoke({"query": query, "schema": schema}))
        if not isinstance(plan, list) or not all("sql" in step and "description" in step for step in plan):
            logger.error("Invalid multi-hop plan")
            return []
        return plan
    except Exception as e:
        logger.error(f"Multi-hop planning failed: {str(e)}")
        return []

def execute_multi_hop_query(steps: List[Dict[str, str]]) -> Optional[List[Dict]]:
    """Execute multi-hop query steps."""
    results = []
    for step in steps:
        sql = step["sql"]
        if "(previous_result)" in sql and results:
            sql = sql.replace("(previous_result)", json.dumps(results[-1]))
        if not validate_query(sql):
            logger.error(f"Invalid step query: {sql}")
            return None
        data = fetch_data_from_api("execute_query", {"query": sql})
        if not data or not validate_results(data.get("result", []), sql):
            logger.error(f"Step execution failed: {sql}")
            return None
        results.append(data["result"])
    return results[-1] if results else None

def determine_chart_type(data: List[Dict]) -> Tuple[str, Tuple[str, str]]:
    """Determine appropriate chart type and columns."""
    if not data or not isinstance(data, list) or not data[0]:
        return "table", ("", "")
    
    keys = data[0].keys()
    numeric_cols = [k for k in keys if isinstance(data[0][k], (int, float))]
    categorical_cols = [k for k in keys if isinstance(data[0][k], str)]
    
    if len(numeric_cols) >= 1 and len(categorical_cols) >= 1:
        return "bar", (categorical_cols[0], numeric_cols[0])
    return "table", ("", "")

def get_response(query: str, chat_history: List) -> Tuple[str, Optional[List]]:
    """Process user query and return response with data."""
    # Cache check
    cache_key = f"{query}_{datetime.now().strftime('%Y%m%d')}"
    if cache_key in st.session_state.cache:
        return st.session_state.cache[cache_key]
    
    domain = classify_query(query)
    matched_entities = fuzzy_match_text(query)
    expanded_entities = expand_entities(matched_entities)
    
    # Handle complex queries
    if len(expanded_entities) > 1 or " by " in query.lower() or " and " in query.lower():
        steps = plan_multi_hop_query(query, SCHEMA)
        if steps:
            data = execute_multi_hop_query(steps)
            if data:
                response = f"Results for '{query}' (Complex Query):\n\n"
                response += f"Found {len(data)} records.\n"
                st.session_state.cache[cache_key] = (response, data)
                return response, data
    
    # Handle simple queries
    chain = get_sql_chain(domain)
    try:
        sql_query = chain.invoke({"query": query, "schema": SCHEMA, "domain": domain})
        if not validate_query(sql_query):
            return "Invalid query generated.", None
        
        data = fetch_data_from_api("execute_query", {"query": sql_query})
        if not data or "result" not in data:
            logger.error(f"API returned no data for query: {sql_query}")
            return "No data found. Try rephrasing your question.", None
        
        results = data["result"]
        if not validate_results(results, query):
            logger.warning(f"Invalid results for query: {sql_query}")
            return "Results seem incorrect. Please try a different question.", None
        
        # Structure response
        response = f"Results for '{query}':\n\n"
        response += f"Found {len(results)} records.\n"
        if domain == "sales":
            total = sum(float(r.get("total", r.get("revenue", 0))) for r in results)
            response += f"Total: ₱{total:.2f}\n"
        elif domain == "inventory":
            low_stock = sum(1 for r in results if r.get("stock", 0) < r.get("reorder_level", 0))
            response += f"Low Stock Items: {low_stock}\n"
        
        st.session_state.cache[cache_key] = (response, results)
        return response, results
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        return f"Error: {str(e)}. Please try again.", None

def authenticate_user(email: str, password: str) -> bool:
    """Authenticate user via API."""
    try:
        response = fetch_data_from_api("authenticate", {"email": email, "password": password})
        return response and response.get("status") == "success"
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}")
        return False

# Streamlit UI
st.title("SCC School Store Chatbot")
st.markdown("Ask questions about sales, inventory, financials, or employees!")

# Authentication
if not st.session_state.user_authenticated:
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        if submit:
            if authenticate_user(email, password):
                st.session_state.user_authenticated = True
                st.success("Logged in successfully!")
                st.rerun()
            else:
                st.error("Invalid credentials.")
else:
    # Chat interface
    user_input = st.text_input("Ask a question about the store:", key="user_input")
    if user_input:
        response, data = get_response(user_input, st.session_state.chat_history)
        st.session_state.chat_history.append({"user": user_input, "bot": response, "data": data})
        
        # Display chat history
        for chat in st.session_state.chat_history:
            with st.chat_message("user"):
                st.write(chat["user"])
            with st.chat_message("assistant"):
                st.write(chat["bot"])
                if chat["data"]:
                    df = pd.DataFrame(chat["data"])
                    chart_type, columns = determine_chart_type(chat["data"])
                    if chart_type == "bar" and columns[0] and columns[1]:
                        st.bar_chart(df.set_index(columns[0])[columns[1]])
                    st.dataframe(df, use_container_width=True)
    
    # Logout
    if st.button("Logout"):
        st.session_state.user_authenticated = False
        st.session_state.chat_history = []
        st.session_state.cache = {}
        st.rerun()
