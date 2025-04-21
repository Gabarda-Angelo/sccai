import streamlit as st
import streamlit.components.v1 as components
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
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import re
import logging
import seaborn as sns
import uuid
from typing import Dict, List, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set page configuration
st.set_page_config(
    page_title="AcaSquad AI",
    page_icon=":speech_balloon:",
    layout="wide"
)

# Function to show pop-up messages
def show_popup(message: str) -> None:
    components.html(
        f"""
        <script>
            alert("{message}");
        </script>
        """,
        height=0,
        width=0,
    )

# Initialize session state
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user = None
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I'm your AcaSquad AI assistant. Ask me anything about your store.")
    ]
if "last_query" not in st.session_state:
    st.session_state.last_query = ""
if "query_cache" not in st.session_state:
    st.session_state.query_cache = {}

# Function to authenticate user via API
def authenticate(email: str, password: str) -> bool:
    try:
        response = requests.post(
            st.secrets["API_URL"],
            params={"action": "authenticate_user", "key": st.secrets["API_KEY"]},
            json={"email": email, "password": password},
            timeout=10
        )
        data = response.json() if response.text.strip() else {}
        if response.status_code == 200 and data.get("status") == "success" and "data" in data:
            st.session_state.authenticated = True
            st.session_state.user = data["data"]
            st.success("Login Successful!")
            return True
        else:
            error_message = data.get("error", "Invalid credentials")
            st.error(f"Login failed: {error_message}")
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        st.error(f"Authentication error: {str(e)}")
    return False

# Initialize vector store for RAG
@lru_cache(maxsize=1)
def initialize_vector_store() -> Optional[FAISS]:
    products_query = "SELECT product_id, product_name, description FROM products;"
    categories_query = "SELECT category_id, category_name FROM categories;"
    products_data = fetch_data_from_api("execute_query", {"query": products_query})
    categories_data = fetch_data_from_api("execute_query", {"query": categories_query})
    
    texts = (
        [f"{item['product_name']}: {item.get('description', '')}" for item in products_data if item.get('product_name')] +
        [item["category_name"] for item in categories_data if item.get("category_name")]
    )
    metadatas = (
        [{"type": "product", "id": item["product_id"]} for item in products_data if item.get("product_name")] +
        [{"type": "category", "id": item["category_id"]} for item in categories_data if item.get("category_name")]
    )
    
    if not texts or not metadatas:
        logger.warning("No texts or metadatas for vector store")
        return None
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    try:
        vector_store = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
        return vector_store
    except Exception as e:
        logger.error(f"Vector store initialization failed: {str(e)}")
        st.error(f"Vector store initialization failed: {str(e)}")
        return None

# Fuzzy match for RAG
@lru_cache(maxsize=100)
def fuzzy_match_text(query: str) -> str:
    if not st.session_state.vector_store:
        st.session_state.vector_store = initialize_vector_store()
    if not st.session_state.vector_store:
        return json.dumps([])
    try:
        results = st.session_state.vector_store.similarity_search(query, k=5)
        matches = [
            {"text": res.page_content, "type": res.metadata.get("type", ""), "id": res.metadata.get("id", "")}
            for res in results if res.page_content and res.metadata
        ]
        return json.dumps(matches)
    except Exception as e:
        logger.error(f"Fuzzy match error: {str(e)}")
        st.error(f"Fuzzy match error: {str(e)}")
        return json.dumps([])

# Fetch data from API with caching
@st.cache_data(ttl=300)
def fetch_data_from_api(action: str, params: dict = None) -> Optional[Dict]:
    try:
        payload = {"action": action, "key": st.secrets["API_KEY"]}
        if params:
            if "query" in params:
                st.session_state.last_query = params["query"]
                params["query"] = quote(params["query"])
            payload.update(params)
        response = requests.get(
            st.secrets["API_URL"],
            params=payload,
            timeout=15
        )
        if not response.text.strip():
            logger.error("Received empty response from API")
            st.error("Received empty response from API")
            return None
        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response: {response.text[:200]}...")
            st.error(f"Invalid JSON response: {response.text[:200]}...")
            return None
        if data.get("status") == "success":
            return data["data"]
        else:
            error_msg = data.get("error", "Unknown error")
            logger.error(f"API Error: {error_msg}")
            st.error(f"API Error: {error_msg}")
            return None
    except requests.RequestException as e:
        logger.error(f"Connection error: {str(e)}")
        st.error(f"Connection error: {str(e)}")
        return None

# Validate SQL queries
def validate_query(query: str) -> bool:
    if not query:
        logger.warning("Validation failed: Query is empty")
        return False
    query_normalized = " ".join(query.split()).upper()
    if not query_normalized.startswith("SELECT"):
        logger.warning("Validation failed: Query does not start with SELECT")
        return False
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"]
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"]
    if any(kw in query_normalized for kw in forbidden):
        logger.warning(f"Validation failed: Forbidden keyword found in {query_normalized}")
        return False
    if not any(kw in query_normalized for kw in allowed_keywords):
        logger.warning(f"Validation failed: No allowed keywords found in {query_normalized}")
        return False
    return True

# Classify query domain
def classify_query(query: str) -> str:
    classification_template = """
    Classify the query into one domain: sales, inventory, employee, financial, operations, misc.
    Query: {query}
    Return only the domain name (e.g., 'sales').
    """
    prompt = ChatPromptTemplate.from_template(classification_template)
    chain = prompt | ChatGroq(model="llama3-8b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    try:
        return chain.invoke({"query": query})
    except Exception as e:
        logger.error(f"Query classification error: {str(e)}")
        return "misc"

# Plan multi-hop query
def plan_multi_hop_query(query: str, schema: str) -> List[Dict[str, str]]:
    planner_template = """
    Decompose the query into sequential SQL steps for the SCC School Store Database.
    **Schema:** {schema}
    **Query:** {query}
    Return a JSON list of steps, each with 'description' and 'sql' keys.
    Instructions:
    - Generate only SELECT queries using INNER JOINs or LEFT JOINs where appropriate.
    - Avoid INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE.
    - For sales queries like 'top selling products', use SUM(id.quantity) from invoice_details, join with products and invoices, and ORDER BY DESC.
    - For invoice queries with dates (e.g., 'sales invoice details on April 14, 2025'), filter invoices by order_date (format: 'YYYY-MM-DD') and include details from invoice_details.
    - For financial queries like 'revenue, profit', calculate SUM(i.total) for revenue, SUM(id.quantity * p.purchase_price) for cost, and derive profit and margin.
    - For employee queries like 'logged in details', use user_logins and employees, filter by login_time or date.
    - For inventory queries, use products and inventory_logs, filter by stock or log_date.
    - Ensure each SQL query is valid and includes FROM, GROUP BY, or WHERE as needed.
    - Handle complex queries by breaking into intermediate steps (e.g., aggregate sales then join with categories).
    Example:
    [
        {{"description": "Get top products", "sql": "SELECT p.product_name, SUM(id.quantity) as total_sold FROM invoice_details id INNER JOIN products p ON id.product_id = p.product_id INNER JOIN invoices i ON id.invoice_id = i.invoice_id WHERE i.total > 0 GROUP BY p.product_id, p.product_name ORDER BY total_sold DESC LIMIT 5;"}},
        {{"description": "Get invoice details for a date", "sql": "SELECT i.invoice_id, i.order_date, i.total, id.quantity, p.product_name FROM invoices i INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id INNER JOIN products p ON id.product_id = p.product_id WHERE i.order_date = '2025-04-14' AND i.total > 0;"}},
        {{"description": "Get financial metrics", "sql": "SELECT SUM(i.total) as revenue, SUM(id.quantity * p.purchase_price) as base_cost, (SUM(i.total) - SUM(id.quantity * p.purchase_price)) as profit, ((SUM(i.total) - SUM(id.quantity * p.purchase_price)) / NULLIF(SUM(i.total), 0) * 100) as profit_margin FROM invoices i INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id INNER JOIN products p ON id.product_id = p.product_id WHERE i.total > 0;"}},
        {{"description": "Get login details", "sql": "SELECT e.first_name, e.last_name, ul.login_time FROM employees e INNER JOIN user_logins ul ON e.employee_id = ul.employee_id WHERE DATE(ul.login_time) = '2025-04-15';"}}
    ]
    """
    prompt = ChatPromptTemplate.from_template(planner_template)
    chain = prompt | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    try:
        steps = json.loads(chain.invoke({"query": query, "schema": schema}))
        return steps if isinstance(steps, list) else [{"description": "Execute query", "sql": ""}]
    except Exception as e:
        logger.error(f"Multi-hop query planning error: {str(e)}")
        return [{"description": "Execute query", "sql": ""}]

# Define specialized SQL chain
def get_sql_chain(domain: str):
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role (Owner, Admin, Cashier), email, password_hash, created_at, updated_at, last_password_change
    - inventory_logs: log_id (PK), product_id (FK to products), change_type (Sale, Restock, Adjustment), quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash, Card, Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address
    - discount_logs: discount_id (PK), invoice_id (FK to invoices, nullable), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - void_logs: void_id (PK), invoice_id (FK to invoices, nullable), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - action_requests: request_id (PK), admin_id (FK to employees), action_type (EDIT, DELETE, UPDATE, INSERT), table_name, record_id, status (PENDING, APPROVED, DENIED), approver_id (FK to employees), created_at, updated_at
    - admin_action_logs: log_id (PK), admin_id (FK to employees), action_type (EDIT, DELETE, UPDATE, INSERT), table_name, record_id, request_id (FK to action_requests), created_at
    - sync_log: id (PK), table_name, record_id, action (INSERT, UPDATE, DELETE), timestamp, synced
    """

    domain_prompts = {
        "sales": """
        Focus on invoices, invoice_details, products, discount_logs, void_logs.
        Use SUM(id.quantity) for quantities, SUM(i.total) for revenue.
        Include discount_logs for discount details and void_logs for voided transactions.
        Example: SELECT p.product_name, SUM(id.quantity) as total_sold 
        FROM invoice_details id 
        INNER JOIN products p ON id.product_id = p.product_id 
        INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
        WHERE i.total > 0 
        GROUP BY p.product_id, p.product_name 
        ORDER BY total_sold DESC 
        LIMIT 5;
        """,
        "inventory": """
        Focus on products, inventory_logs.
        Example: SELECT p.product_name, p.stock, p.reorder_level 
        FROM products p 
        WHERE p.stock < p.reorder_level;
        """,
        "employee": """
        Focus on employees, user_logins, action_requests, admin_action_logs.
        Example: SELECT e.first_name, COUNT(ul.log_id) as login_count 
        FROM employees e 
        INNER JOIN user_logins ul ON e.employee_id = ul.employee_id 
        GROUP BY e.employee_id;
        """,
        "financial": """
        Focus on invoices, invoice_details, products, discount_logs.
        Example: SELECT SUM(i.total) as revenue, SUM(id.quantity * p.purchase_price) as cost 
        FROM invoices i 
        INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id 
        INNER JOIN products p ON id.product_id = p.product_id 
        WHERE i.total > 0;
        """,
        "operations": """
        Focus on invoices, user_logins, sync_log.
        Example: SELECT HOUR(i.order_time) as hour, SUM(id.quantity) as total_quantity 
        FROM invoices i 
        INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id 
        WHERE i.total > 0 
        GROUP BY HOUR(i.order_time);
        """,
        "misc": """
        General queries across all tables.
        Example: SELECT p.product_name, p.sale_price, c.category_name 
        FROM products p 
        INNER JOIN categories c ON p.category_id = c.category_id;
        """
    }

    template = """
    Generate an SQL query for the SCC School Store Database.
    **Domain:** {domain_prompt}
    **Schema:** {schema}
    **Matched Entities:** {matched_entities}
    **Current date:** {current_sg_date}
    **Current datetime:** {current_sg_datetime}
    **Conversation Summary:** {chat_summary}

    Instructions:
    - Use INNER JOINs or LEFT JOINs where appropriate.
    - Group by unique IDs and names.
    - For sales, use WHERE i.total > 0 and check discount_logs/void_logs if relevant.
    - For best-selling products, use SUM(id.quantity) and ORDER BY DESC.
    - Handle date filters using order_date or log_date in 'YYYY-MM-DD' format.
    - Ensure query is valid and optimized.
    - Return only the SQL query.

    **Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = ["llama3-70b-8192", "gemma2-9b-it", "llama-3.3-70b-versatile"]
    proposal_llms = [
        ChatGroq(model=model, temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        for model in models
    ]
    proposal_chain = RunnableParallel(
        **{f"proposal_{i}": prompt | llm | StrOutputParser() for i, llm in enumerate(proposal_llms)}
    )

    aggregator_template = """
    Synthesize the best SQL query from:
    {proposals}
    **Question:** {question}
    **Schema:** {schema}
    Return only the SQL query, ensuring:
    - Starts with SELECT
    - Uses INNER JOINs or LEFT JOINs
    - Includes WHERE i.total > 0 for invoices
    - Groups by unique IDs
    - Optimized for performance
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)

    def prepare_inputs(inputs):
        try:
            matched_entities = json.loads(fuzzy_match_text(inputs["question"]))
        except json.JSONDecodeError:
            matched_entities = []
        return {
            "schema": schema,
            "matched_entities": json.dumps(matched_entities),
            "current_sg_date": inputs["current_sg_date"],
            "current_sg_datetime": inputs["current_sg_datetime"],
            "chat_summary": " ".join([msg.content for msg in inputs["chat_history"][-5:]]),
            "question": inputs["question"],
            "domain_prompt": domain_prompts.get(domain, "General queries")
        }

    return (
        RunnablePassthrough()
        | prepare_inputs
        | RunnablePassthrough.assign(proposals=proposal_chain)
        | aggregator_prompt
        | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )

# Handle multi-domain queries
def orchestrate_query(query: str, chat_history: List, current_sg_date: str, current_sg_datetime: str) -> Tuple[str, Optional[List]]:
    domain = classify_query(query)
    domains = [domain] if isinstance(domain, str) else domain

    def run_agent(domain):
        sql_chain = get_sql_chain(domain)
        raw_query = sql_chain.invoke({
            "question": query,
            "chat_history": chat_history,
            "current_sg_date": current_sg_date,
            "current_sg_datetime": current_sg_datetime
        })
        query = raw_query.split(";")[0] + ";"
        query = query.replace("```sql", "").replace("```", "").strip()
        if validate_query(query):
            cache_key = f"{domain}_{query}"
            if cache_key in st.session_state.query_cache:
                return {"domain": domain, "data": st.session_state.query_cache[cache_key], "query": query}
            data = fetch_data_from_api("execute_query", {"query": query})
            if data:
                st.session_state.query_cache[cache_key] = data
                return {"domain": domain, "data": data, "query": query}
        return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(filter(None, executor.map(run_agent, domains)))

    if not results:
        return "No valid data retrieved.", None

    aggregator_template = """
    Combine results:
    {results}
    **Question:** {question}
    Generate a natural language response:
    - Use 'units' for quantities.
    - Use ₱ for money, 2 decimal places.
    - Use markdown: **bold**, - lists.
    - Note if total_discount = 0.
    - Caution if total_categories ≥ total_products.
    - Keep response concise, under 200 words.
    """
    prompt = ChatPromptTemplate.from_template(aggregator_template)
    chain = prompt | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    natural_response = chain.invoke({
        "question": query,
        "results": json.dumps(results, indent=2)
    })
    return natural_response, results[-1]["data"] if results else None

# Generate AI response
def get_response(user_query: str, chat_history: List) -> Tuple[str, Optional[List]]:
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve", "overview", "profit", "cost", "margin",
        "cashier", "login", "void", "discount_log", "action_request", "admin_action"
    ]
    conversational_keywords = [
        "only", "not", "why", "how come", "that’s", "correct", "wrong", "explain"
    ]

    # Handle conversational queries
    if any(kw in user_query.lower() for kw in conversational_keywords) and not any(kw in user_query.lower() for kw in data_keywords):
        if "only 9 not 10" in user_query.lower():
            return "The database contains only 9 products with sales data. Would you like me to fetch something else?", None
        return "Please provide a specific data request about the store.", None

    # Handle time queries
    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        return f"Current time and date: {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None

    singapore_tz = pytz.timezone('Asia/Singapore')
    now_sg = datetime.datetime.now(singapore_tz)
    current_sg_date = now_sg.strftime('%Y-%m-%d')
    current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

    schema = """
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role (Owner, Admin, Cashier), email, password_hash, created_at, updated_at, last_password_change
    - inventory_logs: log_id (PK), product_id (FK to products), change_type (Sale, Restock, Adjustment), quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash, Card, Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address
    - discount_logs: discount_id (PK), invoice_id (FK to invoices, nullable), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - void_logs: void_id (PK), invoice_id (FK to invoices, nullable), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - action_requests: request_id (PK), admin_id (FK to employees), action_type (EDIT, DELETE, UPDATE, INSERT), table_name, record_id, status (PENDING, APPROVED, DENIED), approver_id (FK to employees), created_at, updated_at
    - admin_action_logs: log_id (PK), admin_id (FK to employees), action_type (EDIT, DELETE, UPDATE, INSERT), table_name, record_id, request_id (FK to action_requests), created_at
    - sync_log: id (PK), table_name, record_id, action (INSERT, UPDATE, DELETE), timestamp, synced
    """

    # Check for multi-domain or complex query
    domain = classify_query(user_query)
    if isinstance(domain, list) or " and " in user_query.lower():
        return orchestrate_query(user_query, chat_history, current_sg_date, current_sg_datetime)

    # Plan multi-hop query
    steps = plan_multi_hop_query(user_query, schema)
    all_data = []
    for step in steps:
        query = step.get("sql", "").strip()
        step_desc = step.get("description", "Execute query")
        logger.info(f"Raw SQL from plan_multi_hop_query for step '{step_desc}': {query}")

        # Extract limit for sales queries
        limit = 5
        if "top" in user_query.lower() and "selling" in user_query.lower():
            match = re.search(r'top\s+(\d+)', user_query.lower())
            limit = int(match.group(1)) if match else 5

        # Fallback queries for sidebar and additional questions
        if not query:
            query_lower = user_query.lower()
            if "best-selling products of all time" in query_lower:
                query = f"""
                SELECT p.product_name, SUM(id.quantity) as total_sold 
                FROM invoice_details id 
                INNER JOIN products p ON id.product_id = p.product_id 
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
                WHERE i.total > 0 
                GROUP BY p.product_id, p.product_name 
                ORDER BY total_sold DESC 
                LIMIT {limit};
                """
                step_desc = f"Get top {limit} best-selling products of all time"
            elif "top 5 best-selling products this month" in query_lower:
                query = f"""
                SELECT p.product_name, SUM(id.quantity) as total_sold 
                FROM invoice_details id 
                INNER JOIN products p ON id.product_id = p.product_id 
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                GROUP BY p.product_id, p.product_name 
                ORDER BY total_sold DESC 
                LIMIT 5;
                """
                step_desc = "Get top 5 best-selling products this month"
            elif "highest sales this week" in query_lower:
                query = f"""
                SELECT p.product_name, SUM(id.quantity) as total_sold 
                FROM invoice_details id 
                INNER JOIN products p ON id.product_id = p.product_id 
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
                WHERE i.total > 0 AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY p.product_id, p.product_name 
                ORDER BY total_sold DESC 
                LIMIT 1;
                """
                step_desc = "Get product with highest sales this week"
            elif "best-selling products in each category" in query_lower:
                query = """
                SELECT c.category_name, p.product_name, SUM(id.quantity) as total_sold
                FROM invoice_details id 
                INNER JOIN products p ON id.product_id = p.product_id 
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
                INNER JOIN categories c ON p.category_id = c.category_id
                WHERE i.total > 0
                GROUP BY c.category_id, p.product_id, p.product_name
                ORDER BY c.category_id, total_sold DESC;
                """
                step_desc = "Get best-selling products in each category"
            elif "sales trend over the past year" in query_lower:
                query = """
                SELECT DATE_FORMAT(i.order_date, '%Y-%m') as month, SUM(i.total) as revenue
                FROM invoices i
                WHERE i.total > 0 AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR)
                GROUP BY DATE_FORMAT(i.order_date, '%Y-%m')
                ORDER BY month;
                """
                step_desc = "Get sales trend over the past year"
            elif "daily sales trend for this month" in query_lower:
                query = """
                SELECT i.order_date, SUM(i.total) as revenue
                FROM invoices i
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                GROUP BY i.order_date
                ORDER BY i.order_date;
                """
                step_desc = "Get daily sales trend for this month"
            elif "day of the week has the highest sales" in query_lower:
                query = """
                SELECT DAYNAME(i.order_date) as day_name, SUM(i.total) as revenue
                FROM invoices i
                WHERE i.total > 0
                GROUP BY DAYNAME(i.order_date)
                ORDER BY revenue DESC
                LIMIT 1;
                """
                step_desc = "Get day of the week with highest sales"
            elif "total revenue this year" in query_lower:
                query = """
                SELECT SUM(i.total) as revenue
                FROM invoices i
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE());
                """
                step_desc = "Get total revenue this year"
            elif "total revenue for today" in query_lower:
                query = f"""
                SELECT SUM(i.total) as revenue
                FROM invoices i
                WHERE i.total > 0 AND i.order_date = '{current_sg_date}';
                """
                step_desc = "Get total revenue for today"
            elif "average daily revenue this month" in query_lower:
                query = """
                SELECT AVG(daily_revenue) as avg_daily_revenue
                FROM (
                    SELECT i.order_date, SUM(i.total) as daily_revenue
                    FROM invoices i
                    WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                    GROUP BY i.order_date
                ) daily;
                """
                step_desc = "Get average daily revenue this month"
            elif "revenue breakdown by product category" in query_lower:
                query = """
                SELECT c.category_name, SUM(i.total) as revenue
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                INNER JOIN products p ON id.product_id = p.product_id
                INNER JOIN categories c ON p.category_id = c.category_id
                WHERE i.total > 0
                GROUP BY c.category_id, c.category_name
                ORDER BY revenue DESC;
                """
                step_desc = "Get revenue breakdown by product category"
            elif "products are out of stock" in query_lower:
                query = """
                SELECT p.product_name, p.stock
                FROM products p
                WHERE p.stock = 0;
                """
                step_desc = "Get products out of stock"
            elif "products are below the reorder level" in query_lower:
                query = """
                SELECT p.product_name, p.stock, p.reorder_level
                FROM products p
                WHERE p.stock < p.reorder_level;
                """
                step_desc = "Get products below reorder level"
            elif "current stock levels for all products" in query_lower:
                query = """
                SELECT p.product_name, p.stock, c.category_name
                FROM products p
                INNER JOIN categories c ON p.category_id = c.category_id
                ORDER BY p.product_name;
                """
                step_desc = "Get current stock levels for all products"
            elif "total value of current inventory" in query_lower:
                query = """
                SELECT SUM(p.stock * p.purchase_price) as total_inventory_value
                FROM products p;
                """
                step_desc = "Get total value of current inventory"
            elif "value of inventory by category" in query_lower:
                query = """
                SELECT c.category_name, SUM(p.stock * p.purchase_price) as inventory_value
                FROM products p
                INNER JOIN categories c ON p.category_id = c.category_id
                GROUP BY c.category_id, c.category_name
                ORDER BY inventory_value DESC;
                """
                step_desc = "Get value of inventory by category"
            elif "products do we have in total" in query_lower:
                query = """
                SELECT COUNT(*) as total_products
                FROM products;
                """
                step_desc = "Get total number of products"
            elif "product categories we have" in query_lower:
                query = """
                SELECT category_name
                FROM categories
                ORDER BY category_name;
                """
                step_desc = "Get all product categories"
            elif "products added in the last 30 days" in query_lower:
                query = """
                SELECT p.product_name, p.created_at
                FROM products p
                WHERE p.created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                ORDER BY p.created_at DESC;
                """
                step_desc = "Get products added in the last 30 days"
            elif "top-performing employee this month" in query_lower:
                query = """
                SELECT e.first_name, e.last_name, SUM(i.total) as total_sales
                FROM invoices i
                INNER JOIN employees e ON i.employee_id = e.employee_id
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                GROUP BY e.employee_id, e.first_name, e.last_name
                ORDER BY total_sales DESC
                LIMIT 1;
                """
                step_desc = "Get top-performing employee this month"
            elif "total sales by each employee this week" in query_lower:
                query = """
                SELECT e.first_name, e.last_name, SUM(i.total) as total_sales
                FROM invoices i
                INNER JOIN employees e ON i.employee_id = e.employee_id
                WHERE i.total > 0 AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY e.employee_id, e.first_name, e.last_name
                ORDER BY total_sales DESC;
                """
                step_desc = "Get total sales by each employee this week"
            elif "highest number of transactions today" in query_lower:
                query = f"""
                SELECT e.first_name, e.last_name, COUNT(i.invoice_id) as transaction_count
                FROM invoices i
                INNER JOIN employees e ON i.employee_id = e.employee_id
                WHERE i.total > 0 AND i.order_date = '{current_sg_date}'
                GROUP BY e.employee_id, e.first_name, e.last_name
                ORDER BY transaction_count DESC
                LIMIT 1;
                """
                step_desc = "Get employee with highest transactions today"
            elif "currently logged in" in query_lower:
                query = f"""
                SELECT e.first_name, e.last_name, ul.login_time
                FROM employees e
                INNER JOIN user_logins ul ON e.employee_id = ul.employee_id
                WHERE ul.logout_time IS NULL AND DATE(ul.login_time) = '{current_sg_date}';
                """
                step_desc = "Get currently logged in employees"
            elif "login and logout times for all employees" in query_lower:
                query = f"""
                SELECT e.first_name, e.last_name, ul.login_time, ul.logout_time
                FROM employees e
                INNER JOIN user_logins ul ON e.employee_id = ul.employee_id
                WHERE DATE(ul.login_time) = '{current_sg_date}'
                ORDER BY ul.login_time;
                """
                step_desc = "Get login and logout times for all employees today"
            elif "times has each employee logged in this month" in query_lower:
                query = """
                SELECT e.first_name, e.last_name, COUNT(ul.log_id) as login_count
                FROM employees e
                INNER JOIN user_logins ul ON e.employee_id = ul.employee_id
                WHERE YEAR(ul.login_time) = YEAR(CURDATE()) AND MONTH(ul.login_time) = MONTH(CURDATE())
                GROUP BY e.employee_id, e.first_name, e.last_name
                ORDER BY login_count DESC;
                """
                step_desc = "Get login counts for each employee this month"
            elif "sales invoices details for today" in query_lower:
                query = f"""
                SELECT i.invoice_id, i.order_date, i.total, id.quantity, p.product_name
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                INNER JOIN products p ON id.product_id = p.product_id
                WHERE i.total > 0 AND i.order_date = '{current_sg_date}';
                """
                step_desc = "Get sales invoice details for today"
            elif "invoices from last week" in query_lower:
                query = """
                SELECT i.invoice_id, i.order_date, i.total, i.payment_type
                FROM invoices i
                WHERE i.total > 0 AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                ORDER BY i.order_date DESC;
                """
                step_desc = "Get invoices from last week"
            elif "total amount due from unpaid invoices" in query_lower:
                query = """
                SELECT SUM(i.due) as total_due
                FROM invoices i
                WHERE i.due > 0;
                """
                step_desc = "Get total amount due from unpaid invoices"
            elif "average transaction value this month" in query_lower:
                query = """
                SELECT AVG(i.total) as avg_transaction_value
                FROM invoices i
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE());
                """
                step_desc = "Get average transaction value this month"
            elif "most common payment method used" in query_lower:
                query = """
                SELECT i.payment_type, COUNT(*) as transaction_count
                FROM invoices i
                WHERE i.total > 0
                GROUP BY i.payment_type
                ORDER BY transaction_count DESC
                LIMIT 1;
                """
                step_desc = "Get most common payment method"
            elif "percentage of transactions are paid by cash" in query_lower:
                query = """
                SELECT (SUM(CASE WHEN i.payment_type = 'Cash' THEN 1 ELSE 0 END) / COUNT(*)) * 100 as cash_percentage
                FROM invoices i
                WHERE i.total > 0;
                """
                step_desc = "Get percentage of cash transactions"
            elif "transactions were made by card this week" in query_lower:
                query = """
                SELECT COUNT(*) as card_transactions
                FROM invoices i
                WHERE i.total > 0 AND i.payment_type = 'Card' AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY);
                """
                step_desc = "Get number of card transactions this week"
            elif "total discount given this month" in query_lower:
                query = """
                SELECT SUM(i.discount) as total_discount
                FROM invoices i
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE());
                """
                step_desc = "Get total discount given this month"
            elif "invoices had the highest discounts this month" in query_lower:
                query = """
                SELECT i.invoice_id, i.order_date, i.discount
                FROM invoices i
                WHERE i.total > 0 AND i.discount > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                ORDER BY i.discount DESC
                LIMIT 5;
                """
                step_desc = "Get invoices with highest discounts this month"
            elif "busiest hour of the day for sales" in query_lower:
                query = """
                SELECT HOUR(i.order_time) as hour, SUM(id.quantity) as total_quantity
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                WHERE i.total > 0
                GROUP BY HOUR(i.order_time)
                ORDER BY total_quantity DESC
                LIMIT 1;
                """
                step_desc = "Get busiest hour of the day for sales"
            elif "day of the week has the highest foot traffic" in query_lower:
                query = """
                SELECT DAYNAME(i.order_date) as day_name, COUNT(*) as transaction_count
                FROM invoices i
                WHERE i.total > 0
                GROUP BY DAYNAME(i.order_date)
                ORDER BY transaction_count DESC
                LIMIT 1;
                """
                step_desc = "Get day of the week with highest foot traffic"
            elif "average number of transactions per day" in query_lower:
                query = """
                SELECT AVG(daily_transactions) as avg_daily_transactions
                FROM (
                    SELECT i.order_date, COUNT(*) as daily_transactions
                    FROM invoices i
                    WHERE i.total > 0
                    GROUP BY i.order_date
                ) daily;
                """
                step_desc = "Get average number of transactions per day"
            elif "average time between login and first transaction" in query_lower:
                query = """
                SELECT AVG(TIMESTAMPDIFF(MINUTE, ul.login_time, MIN(i.order_time))) as avg_minutes
                FROM user_logins ul
                INNER JOIN invoices i ON ul.employee_id = i.employee_id
                WHERE i.total > 0 AND i.order_date = DATE(ul.login_time)
                GROUP BY ul.log_id;
                """
                step_desc = "Get average time between login and first transaction"
            elif "transactions were completed in the last hour" in query_lower:
                query = f"""
                SELECT COUNT(*) as recent_transactions
                FROM invoices i
                WHERE i.total > 0 AND i.created_at >= DATE_SUB('{current_sg_datetime}', INTERVAL 1 HOUR);
                """
                step_desc = "Get transactions in the last hour"
            elif "inventory changes for all products" in query_lower:
                query = """
                SELECT p.product_name, il.change_type, il.quantity, il.log_date
                FROM inventory_logs il
                INNER JOIN products p ON il.product_id = p.product_id
                WHERE il.log_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                ORDER BY il.log_date DESC;
                """
                step_desc = "Get inventory changes for all products this week"
            elif "most recent inventory adjustments" in query_lower:
                query = """
                SELECT p.product_name, il.change_type, il.quantity, il.log_date, il.notes
                FROM inventory_logs il
                INNER JOIN products p ON il.product_id = p.product_id
                WHERE il.change_type = 'Adjustment'
                ORDER BY il.log_date DESC
                LIMIT 5;
                """
                step_desc = "Get most recent inventory adjustments"
            elif "profit margins for all products" in query_lower:
                query = """
                SELECT p.product_name, ((p.sale_price - p.purchase_price) / NULLIF(p.sale_price, 0) * 100) as profit_margin
                FROM products p
                ORDER BY profit_margin DESC;
                """
                step_desc = "Get profit margins for all products"
            elif "total units sold for all products this month" in query_lower:
                query = """
                SELECT p.product_name, SUM(id.quantity) as total_sold
                FROM invoice_details id
                INNER JOIN products p ON id.product_id = p.product_id
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE()) AND MONTH(i.order_date) = MONTH(CURDATE())
                GROUP BY p.product_id, p.product_name
                ORDER BY total_sold DESC;
                """
                step_desc = "Get total units sold for all products this month"
            elif "sales history for all products this year" in query_lower:
                query = """
                SELECT p.product_name, SUM(id.quantity) as total_sold, SUM(i.total) as revenue
                FROM invoice_details id
                INNER JOIN products p ON id.product_id = p.product_id
                INNER JOIN invoices i ON id.invoice_id = i.invoice_id
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE())
                GROUP BY p.product_id, p.product_name
                ORDER BY total_sold DESC;
                """
                step_desc = "Get sales history for all products this year"
            elif "category has the highest sales this year" in query_lower:
                query = """
                SELECT c.category_name, SUM(i.total) as revenue
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                INNER JOIN products p ON id.product_id = p.product_id
                INNER JOIN categories c ON p.category_id = c.category_id
                WHERE i.total > 0 AND YEAR(i.order_date) = YEAR(CURDATE())
                GROUP BY c.category_id, c.category_name
                ORDER BY revenue DESC
                LIMIT 1;
                """
                step_desc = "Get category with highest sales this year"
            elif "average price of products in each category" in query_lower:
                query = """
                SELECT c.category_name, AVG(p.sale_price) as avg_price
                FROM products p
                INNER JOIN categories c ON p.category_id = c.category_id
                GROUP BY c.category_id, c.category_name
                ORDER BY avg_price DESC;
                """
                step_desc = "Get average price of products in each category"
            elif "products should we reorder soon" in query_lower:
                query = """
                SELECT p.product_name, p.stock, p.reorder_level
                FROM products p
                WHERE p.stock <= p.reorder_level;
                """
                step_desc = "Get products to reorder soon"
            elif "products are within 10% of their reorder level" in query_lower:
                query = """
                SELECT p.product_name, p.stock, p.reorder_level
                FROM products p
                WHERE p.stock <= (p.reorder_level * 1.1) AND p.stock > p.reorder_level;
                """
                step_desc = "Get products within 10% of reorder level"
            elif "discount logs this month" in query_lower:
                query = """
                SELECT dl.discount_id, dl.created_at, dl.details, e.first_name, e.last_name
                FROM discount_logs dl
                INNER JOIN employees e ON dl.cashier_id = e.employee_id
                WHERE YEAR(dl.created_at) = YEAR(CURDATE()) AND MONTH(dl.created_at) = MONTH(CURDATE())
                ORDER BY dl.created_at DESC;
                """
                step_desc = "Get discount logs for this month"
            elif "voided transactions this week" in query_lower:
                query = """
                SELECT vl.void_id, vl.created_at, vl.details, e.first_name, e.last_name
                FROM void_logs vl
                INNER JOIN employees e ON vl.cashier_id = e.employee_id
                WHERE vl.created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                ORDER BY vl.created_at DESC;
                """
                step_desc = "Get voided transactions this week"
            elif "pending action requests" in query_lower:
                query = """
                SELECT ar.request_id, ar.action_type, ar.table_name, ar.status, e.first_name, e.last_name
                FROM action_requests ar
                INNER JOIN employees e ON ar.admin_id = e.employee_id
                WHERE ar.status = 'PENDING'
                ORDER BY ar.created_at DESC;
                """
                step_desc = "Get pending action requests"
            elif "admin actions this month" in query_lower:
                query = """
                SELECT aal.log_id, aal.action_type, aal.table_name, aal.created_at, e.first_name, e.last_name
                FROM admin_action_logs aal
                INNER JOIN employees e ON aal.admin_id = e.employee_id
                WHERE YEAR(aal.created_at) = YEAR(CURDATE()) AND MONTH(aal.created_at) = MONTH(CURDATE())
                ORDER BY aal.created_at DESC;
                """
                step_desc = "Get admin actions this month"
            elif "unsynced changes" in query_lower:
                query = """
                SELECT sl.id, sl.table_name, sl.record_id, sl.action, sl.timestamp
                FROM sync_log sl
                WHERE sl.synced = FALSE
                ORDER BY sl.timestamp DESC
                LIMIT 10;
                """
                step_desc = "Get unsynced changes"
            elif "invoice" in query_lower:
                date_match = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s+\d{4}', query_lower)
                date_str = current_sg_date
                if date_match:
                    try:
                        date_obj = datetime.datetime.strptime(date_match.group(0), "%B %d, %Y")
                        date_str = date_obj.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                elif "today" in query_lower:
                    date_str = current_sg_date
                query = f"""
                SELECT i.invoice_id, i.order_date, i.total, id.quantity, p.product_name, i.payment_type
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                INNER JOIN products p ON id.product_id = p.product_id
                WHERE i.total > 0 AND i.order_date = '{date_str}';
                """
                step_desc = f"Get invoice details for {date_str}"
            elif any(kw in query_lower for kw in ["revenue", "profit", "cost", "margin"]):
                query = """
                SELECT 
                    SUM(i.total) as revenue,
                    SUM(id.quantity * p.purchase_price) as base_cost,
                    (SUM(i.total) - SUM(id.quantity * p.purchase_price)) as profit,
                    ((SUM(i.total) - SUM(id.quantity * p.purchase_price)) / NULLIF(SUM(i.total), 0) * 100) as profit_margin
                FROM invoices i
                INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
                INNER JOIN products p ON id.product_id = p.product_id
                WHERE i.total > 0;
                """
                step_desc = "Get financial metrics"
            elif any(kw in query_lower for kw in ["login", "logged", "cashier"]):
                date_str = current_sg_date
                time_condition = ""
                if "4pm to 9pm" in query_lower:
                    time_condition = " AND TIME(ul.login_time) BETWEEN '16:00:00' AND '21:00:00'"
                query = f"""
                SELECT e.first_name, e.last_name, e.role, ul.login_time, ul.logout_time
                FROM employees e
                INNER JOIN user_logins ul ON e.employee_id = ul.employee_id
                WHERE DATE(ul.login_time) = '{date_str}'{time_condition};
                """
                step_desc = f"Get login details for {date_str}"

        # Normalize query for validation
        query = query.strip() if query else ""
        logger.info(f"Generated SQL for step '{step_desc}': {query}")
        if not validate_query(query):
            return f"Invalid query generated for step: {step_desc}.", None

        # Clear cache for dynamic queries
        if any(kw in user_query.lower() for kw in ["best-selling", "sales", "revenue", "inventory", "overview", "profit", "login", "discount", "void", "action", "sync"]):
            fetch_data_from_api.clear()

        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return f"No data for step: {step_desc}.", None
        all_data.append({"step": step_desc, "data": data})

    response_template = """
    Generate a response based on:
    - **Question:** {question}
    - **Results:** {response}
    - **History:** {chat_history}
    Guidelines:
    - State "No data found" if empty.
    - Use 'units' for quantities.
    - Use ₱ for money, 2 decimal places.
    - Use **bold** for emphasis, - for lists.
    - Note if total_discount = 0.
    - Caution if total_categories ≥ total_products.
    - Keep under 200 words.
    """
    chain = (
        RunnablePassthrough.assign(response=lambda _: json.dumps(all_data, indent=2))
        | ChatPromptTemplate.from_template(response_template)
        | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
    natural_response = chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })
    return natural_response, all_data[-1]["data"] if all_data else None

# Handle user queries
def handle_query(query: str) -> None:
    if not query:
        return
    query_id = str(uuid.uuid4())
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            natural_response, data = get_response(query, st.session_state.chat_history)
            logger.info(f"Query {query_id} processed successfully")
        except Exception as e:
            logger.error(f"Query {query_id} handling error: {str(e)}")
            natural_response = f"An error occurred: {str(e)}"
            data = None
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            for col in df.columns:
                if "date" in col.lower() or "time" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "discount", "revenue", "cost", "profit"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce').round(2)
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                elif "margin" in col.lower():
                    df[col] = pd.to_numeric(df[col], errors='coerce').round(2)
                    df.rename(columns={col: f"{col} (%)"}, inplace=True)
                elif col.lower() in ["total_sold", "quantity", "transaction_count", "login_count", "product_count", "total_products", "total_categories", "total_invoices"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots(figsize=(10, 6))
                    sns.set_style("whitegrid")
                    if chart_type == 'bar':
                        sns.barplot(data=df, x=columns[0], y=columns[1], ax=ax, palette="viridis")
                        ax.set_title(f"{columns[1].replace(' (₱)', '').replace(' (%)', '')} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "quantity", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)').replace(' (%)', ' (%)'))
                        plt.xticks(rotation=45, ha='right')
                    elif chart_type == 'line':
                        sns.lineplot(data=df, x=columns[0], y=columns[1], ax=ax, marker='o', color='b')
                        ax.set_title(f"{columns[1].replace(' (₱)', '').replace(' (%)', '')} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "quantity", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)').replace(' (%)', ' (%)'))
                        plt.xticks(rotation=45)
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%', colors=sns.color_palette("pastel"))
                        ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '').replace(' (%)', '')}")
                    plt.tight_layout()
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), f"data_{query_id}.csv")
            if len(df) > 0 or len(df.columns) > 1:
                st.dataframe(df, use_container_width=True)

# Display chat history
def display_chat_history() -> None:
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="dist/img/ai.png"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="dist/img/Human.png"):
                st.markdown(message.content)

# Clear chat history
def clear_chat() -> None:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I'm your AcaSquad AI assistant. Ask me anything about your store.")
    ]
    st.session_state.query_cache.clear()
    st.success("Chat history cleared. Starting a new conversation!")

# Determine chart type
def determine_chart_type(query: str, df: pd.DataFrame) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    if df.empty or len(df.columns) < 2:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or "time" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    if date_columns and numerical_columns:
        return "line", (date_columns[0], numerical_columns[0])
    elif categorical_columns and numerical_columns:
        unique_categories = len(df[categorical_columns[0]].unique())
        if unique_categories <= 6 and ("percentage" in query_lower or "breakdown" in query_lower or "distribution" in query_lower):
            return "pie", (categorical_columns[0], numerical_columns[0])
        else:
            return "bar", (categorical_columns[0], numerical_columns[0])
    return None, None

# Main application
def main():
    if not st.session_state.authenticated:
        col1, col2, col3 = st.columns([1, 3, 1])
        with col2:
            st.title("Login to AcaSquad AI")
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submit = st.form_submit_button("Login")
                if submit:
                    if authenticate(email, password):
                        st.session_state.authenticated = True
                        st.rerun()
    else:
        if st.session_state.user["role"] in ["Owner", "Admin"]:
            st.title("AcaSquad AI: School Store Insights")
            with st.sidebar:
                st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
                st.markdown(f"**Logged in as:** {st.session_state.user['first_name']} {st.session_state.user['last_name']} ({st.session_state.user['role']})")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Logout"):
                        st.session_state.authenticated = False
                        st.session_state.user = None
                        st.rerun()
                with col2:
                    if st.button("Clear Chat"):
                        clear_chat()
                        st.rerun()
                st.markdown("---")
                with st.expander("📈 Sales Performance"):
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
                        if st.button(q, key=f"sales_{q.replace(' ', '_')}"):
                            handle_query(q)
                with st.expander("📦 Inventory Management"):
                    inventory_queries = [
                        "Which products are out of stock?",
                        "Which products are below the reorder level?",
                        "What are the current stock levels for all products?",
                        "What is the total value of current inventory?",
                        "What is the value of inventory by category?",
                        "How many products do we have in total?",
                        "What are the product categories we have?",
                        "List all products added in the last 30 days.",
                        "Which products should we reorder soon?",
                        "Which products are within 10% of their reorder level?"
                    ]
                    for q in inventory_queries:
                        if st.button(q, key=f"inv_{q.replace(' ', '_')}"):
                            handle_query(q)
                with st.expander("👥 Employee Performance"):
                    employee_queries = [
                        "Who is the top-performing employee this month?",
                        "What are the total sales by each employee this week?",
                        "Which employee has the highest number of transactions today?",
                        "Who is currently logged in?",
                        "What are today’s login and logout times for all employees?",
                        "How many times has each employee logged in this month?"
                    ]
                    for q in employee_queries:
                        if st.button(q, key=f"emp_{q.replace(' ', '_')}"):
                            handle_query(q)
                with st.expander("💰 Financial Insights"):
                    financial_queries = [
                        "Give me the sales invoices details for today.",
                        "List all invoices from last week.",
                        "What is the total amount due from unpaid invoices?",
                        "What is the average transaction value this month?",
                        "What is the most common payment method used?",
                        "What percentage of transactions are paid by cash?",
                        "How many transactions were made by card this week?",
                        "What is the total discount given this month?",
                        "Which invoices had the highest discounts this month?"
                    ]
                    for q in financial_queries:
                        if st.button(q, key=f"fin_{q.replace(' ', '_')}"):
                            handle_query(q)
                with st.expander("🏪 Store Operations"):
                    ops_queries = [
                        "What is the busiest hour of the day for sales?",
                        "Which day of the week has the highest foot traffic?",
                        "What is the average number of transactions per day?",
                        "What is the average time between login and first transaction for employees?",
                        "How many transactions were completed in the last hour?",
                        "Show me this week’s inventory changes for all products.",
                        "What are the most recent inventory adjustments."
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q.replace(' ', '_')}"):
                            handle_query(q)
                with st.expander("🔍 Miscellaneous Insights"):
                    misc_queries = [
                        "What are the profit margins for all products?",
                        "What are the total units sold for all products this month?",
                        "What is the sales history for all products this year?",
                        "Which product category has the highest sales this year?",
                        "What is the average price of products in each category?",
                        "Show me the discount logs for this month.",
                        "List all voided transactions this week.",
                        "What are the pending action requests?",
                        "Show me the admin actions for this month.",
                        "List the unsynced changes in the database."
                    ]
                    for q in misc_queries:
                        if st.button(q, key=f"misc_{q.replace(' ', '_')}"):
                            handle_query(q)
            display_chat_history()
            user_query = st.chat_input("Ask about sales, inventory, employees, financials, or operations...")
            if user_query:
                handle_query(user_query)
        else:
            st.error("Access restricted. Please contact an Admin.")
            if st.button("Logout"):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.rerun()

if __name__ == "__main__":
    main()

# Hide Streamlit default UI elements
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
