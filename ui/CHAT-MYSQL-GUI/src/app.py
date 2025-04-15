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

# Set page configuration
st.set_page_config(
    page_title="AcaSquad AI",
    page_icon=":speech_balloon:",
    layout="wide"
)

# Function to show pop-up messages
def show_popup(message):
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

# Function to authenticate user via API
def authenticate(email, password):
    try:
        response = requests.post(
            st.secrets["API_URL"],
            params={"action": "authenticate_user", "key": st.secrets["API_KEY"]},
            json={"email": email, "password": password}
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
        st.error(f"Authentication error: {str(e)}")
    return False

# Initialize vector store for RAG
@lru_cache(maxsize=1)
def initialize_vector_store():
    products_query = "SELECT product_id, product_name FROM products;"
    categories_query = "SELECT category_id, category_name FROM categories;"
    products_data = fetch_data_from_api("execute_query", {"query": products_query})
    categories_data = fetch_data_from_api("execute_query", {"query": categories_query})
    
    texts = (
        [item["product_name"] for item in products_data if item.get("product_name")] +
        [item["category_name"] for item in categories_data if item.get("category_name")]
    )
    metadatas = (
        [{"type": "product", "id": item["product_id"]} for item in products_data if item.get("product_name")] +
        [{"type": "category", "id": item["category_id"]} for item in categories_data if item.get("category_name")]
    )
    
    if not texts or not metadatas:
        return None
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    try:
        vector_store = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
        return vector_store
    except Exception as e:
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
        results = st.session_state.vector_store.similarity_search(query, k=3)
        matches = [
            {"text": res.page_content, "type": res.metadata.get("type", ""), "id": res.metadata.get("id", "")}
            for res in results if res.page_content and res.metadata
        ]
        return json.dumps(matches)
    except Exception as e:
        st.error(f"Fuzzy match error: {str(e)}")
        return json.dumps([])

# Fetch data from API with caching
@st.cache_data
def fetch_data_from_api(action: str, params: dict = None) -> dict:
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
            error_msg = data.get("error", "Unknown error")
            st.error(f"API Error: {error_msg}")
            return None
    except requests.RequestException as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Validate SQL queries
def validate_query(query):
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"]
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        return False
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"]
    return all(kw not in query_upper for kw in forbidden) and any(kw in query_upper for kw in allowed_keywords)

# Classify query domain
def classify_query(query: str) -> str:
    classification_template = """
    Classify the query into one domain: sales, inventory, employee, financial, operations, misc.
    Query: {query}
    Return only the domain name (e.g., 'sales').
    """
    prompt = ChatPromptTemplate.from_template(classification_template)
    chain = prompt | ChatGroq(model="llama3-8b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    return chain.invoke({"query": query})

# Plan multi-hop query
def plan_multi_hop_query(query: str, schema: str) -> list:
    planner_template = """
    Decompose the query into sequential SQL steps.
    **Schema:** {schema}
    **Query:** {query}
    Return a JSON list of steps, each with 'desc' and 'sql' keys.
    Example: [{"desc": "Get top products", "sql": "SELECT ..."}]
    """
    prompt = ChatPromptTemplate.from_template(planner_template)
    chain = prompt | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    try:
        steps = json.loads(chain.invoke({"query": query, "schema": schema}))
        return steps if isinstance(steps, list) else [{"desc": "Execute query", "sql": query}]
    except json.JSONDecodeError:
        return [{"desc": "Execute query", "sql": query}]

# Define specialized SQL chain
def get_sql_chain(domain: str):
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

    domain_prompts = {
        "sales": """
        Focus on invoices, invoice_details, products.
        Use SUM(id.quantity) for quantities, SUM(i.total) for revenue.
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
        Example: SELECT product_name, stock FROM products WHERE stock < reorder_level;
        """,
        "employee": """
        Focus on employees, user_logins.
        Example: SELECT e.first_name, COUNT(ul.log_id) FROM employees e 
        INNER JOIN user_logins ul ON e.employee_id = ul.employee_id 
        GROUP BY e.employee_id;
        """,
        "financial": """
        Focus on invoices, invoice_details.
        Example: SELECT SUM(i.total) FROM invoices i WHERE i.total > 0;
        """,
        "operations": """
        Focus on invoices, user_logins.
        Example: SELECT HOUR(i.order_time), SUM(id.quantity) 
        FROM invoices i INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id 
        WHERE i.total > 0 GROUP BY HOUR(i.order_time);
        """,
        "misc": """
        General queries.
        Example: SELECT product_name, sale_price FROM products;
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
    - Use INNER JOINs.
    - Group by unique IDs and names.
    - For sales, use WHERE i.total > 0.
    - For best-selling products, use SUM(id.quantity) and ORDER BY DESC.
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
    - Uses INNER JOINs
    - Includes WHERE i.total > 0 for invoices
    - Groups by unique IDs
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
            "chat_summary": " ".join([msg.content for msg in inputs["chat_history"][-3:]]),
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
def orchestrate_query(query: str, chat_history: list, current_sg_date: str, current_sg_datetime: str):
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
            data = fetch_data_from_api("execute_query", {"query": query})
            return {"domain": domain, "data": data, "query": query} if data else None
        return None

    with ThreadPoolExecutor() as executor:
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
    """
    prompt = ChatPromptTemplate.from_template(aggregator_template)
    chain = prompt | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    natural_response = chain.invoke({
        "question": query,
        "results": json.dumps(results, indent=2)
    })
    return natural_response, results[-1]["data"] if results else None

# Generate AI response
def get_response(user_query: str, chat_history: list):
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve", "overview"
    ]

    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        return f"Your current time and date is {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None
    else:
        singapore_tz = pytz.timezone('Asia/Singapore')
        now_sg = datetime.datetime.now(singapore_tz)
        current_sg_date = now_sg.strftime('%Y-%m-%d')
        current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

        schema = """
        - categories: category_id (PK), category_name, created_at
        - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at
        - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes
        - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at
        - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price
        - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
        - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address
        """

        steps = plan_multi_hop_query(user_query, schema)
        all_data = []
        for step in steps:
            query = step["sql"].strip()
            if not validate_query(query):
                return "Invalid query generated.", None
            if any(kw in user_query.lower() for kw in ["best-selling", "sales", "revenue", "inventory", "overview"]):
                fetch_data_from_api.clear()
            data = fetch_data_from_api("execute_query", {"query": query})
            if data is None:
                return f"No data for step: {step['desc']}.", None
            all_data.append({"step": step["desc"], "data": data})

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
def handle_query(query: str):
    if not query:
        return
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
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "discount", "total_revenue", "avg_price", "net_total", "base_cost", "profit", "avg_sales_value", "total_inventory_value", "category_value"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                elif col.lower() in ["total_sold", "transaction_count", "login_count", "product_count", "total_products", "total_categories", "total_invoices"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots()
                    if chart_type == 'bar':
                        df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '')}")
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 0 or len(df.columns) > 1:
                st.table(df)

# Display chat history
def display_chat_history():
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="dist/img/ai.png"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="dist/img/Human.png"):
                st.markdown(message.content)

# Clear chat history
def clear_chat():
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
    ]
    st.success("Chat history cleared. Starting a new conversation!")

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    if date_columns and numerical_columns:
        return "line", (date_columns[0], numerical_columns[0])
    elif categorical_columns and numerical_columns:
        unique_categories = len(df[categorical_columns[0]].unique())
        if unique_categories <= 6 and ("percentage" in query_lower or "breakdown" in query_lower):
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
            st.title("Chat with our AcaSquad AI")
            with st.sidebar:
                st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
                st.markdown(f"Logged in as {st.session_state.user['first_name']} {st.session_state.user['last_name']} ({st.session_state.user['role']})")
                if st.button("Logout"):
                    st.session_state.authenticated = False
                    st.session_state.user = None
                    st.rerun()
                if st.button("Clear Chat"):
                    clear_chat()
                    st.rerun()
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
                        if st.button(q, key=f"sales_{q}"):
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
                        "List all products added in the last 30 days."
                    ]
                    for q in inventory_queries:
                        if st.button(q, key=f"inv_{q}"):
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
                        if st.button(q, key=f"emp_{q}"):
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
                        if st.button(q, key=f"fin_{q}"):
                            handle_query(q)
                with st.expander("🏪 Store Operations"):
                    ops_queries = [
                        "What is the busiest hour of the day for sales?",
                        "Which day of the week has the highest foot traffic?",
                        "What is the average number of transactions per day?",
                        "What is the average time between login and first transaction for employees?",
                        "How many transactions were completed in the last hour?",
                        "Show me this week’s inventory changes for all products.",
                        "What are the most recent inventory adjustments?"
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q}"):
                            handle_query(q)
                with st.expander("🔍 Miscellaneous Insights"):
                    misc_queries = [
                        "What are the profit margins for all products?",
                        "What are the total units sold for all products this month?",
                        "What is the sales history for all products this year?",
                        "Which product category has the highest sales this year?",
                        "What is the average price of products in each category?",
                        "Which products should we reorder soon?",
                        "How many products are within 10% of their reorder level?"
                    ]
                    for q in misc_queries:
                        if st.button(q, key=f"misc_{q}"):
                            handle_query(q)
            if "chat_history" not in st.session_state:
                st.session_state.chat_history = [
                    AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
                ]
            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query)
        else:
            st.error("Sorry, you can't access this. Please contact the Admin.")
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
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)