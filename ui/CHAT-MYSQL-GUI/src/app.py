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
import re
import uuid

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
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store, from simple lookups to complex analytics.")
    ]
    st.session_state.query_history = []

# Sanitize user input
def sanitize_input(query):
    # Remove potentially dangerous characters and limit length
    query = re.sub(r'[<>{};]', '', query)
    return query[:500]  # Limit to 500 characters

# Authenticate user
def authenticate(email, password):
    try:
        response = requests.post(
            st.secrets["API_URL"],
            params={"action": "authenticate_user", "key": st.secrets["API_KEY"]},
            json={"email": email, "password": password},
            timeout=10
        )
        data = response.json() if response.text else {}
        if response.status_code == 200 and data.get("status") == "success":
            st.session_state.authenticated = True
            st.session_state.user = data["data"]
            st.success("Login Successful!")
            return True
        else:
            st.error(f"Login failed: {data.get('error', 'Invalid credentials')}")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
    return False

# Handle user queries
def handle_query(query: str, complexity: str = "simple"):
    query = sanitize_input(query.strip())
    if not query:
        st.warning("Please enter a valid query.")
        return
    st.session_state.chat_history.append(HumanMessage(content=query))
    st.session_state.query_history.append(query)
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            natural_response, data = get_response(query, st.session_state.chat_history, complexity)
            # Log complex queries
            if complexity == "advanced" and st.session_state.user["role"] in ["Owner", "Admin"]:
                log_query(query)
        except Exception as e:
            natural_response = f"An error occurred: {str(e)}. Try rephrasing your question or simplifying it."
            data = None
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            # Handle large datasets
            if len(df) > 1000:
                st.warning("Results are large. Showing summary and top 100 rows.")
                st.write(f"Total rows: {len(df)}")
                df_summary = df.describe().to_dict()
                st.write("Summary Statistics:", df_summary)
                df = df.head(100)
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots()
                    if chart_type == 'bar':
                        df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1]}")
                    elif chart_type == 'scatter':
                        df.plot(kind='scatter', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} vs {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'stacked_bar':
                        df.pivot_table(index=columns[0], columns=columns[2], values=columns[1], aggfunc='sum').plot(kind='bar', stacked=True, ax=ax)
                        ax.set_title(f"{columns[1]} by {columns[0]} and {columns[2]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 1 or len(df.columns) > 1:
                st.table(df)

# Log complex queries
def log_query(query):
    try:
        requests.post(
            st.secrets["API_URL"],
            params={"action": "log_query", "key": st.secrets["API_KEY"]},
            json={
                "admin_id": st.session_state.user["employee_id"],
                "details": json.dumps({"query": query, "timestamp": datetime.datetime.now().isoformat()}),
                "action_type": "INSERT"
            },
            timeout=5
        )
    except Exception:
        pass  # Silent fail to avoid disrupting user experience

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
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store, from simple lookups to complex analytics.")
    ]
    st.success("Chat history cleared. Starting a new conversation!")

# Fetch data from API
@st.cache_data(ttl=60)
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
        data = response.json()
        if data.get("status") == "success":
            return data["data"]
        else:
            st.error(f"API Error: {data.get('error', 'Unknown error')}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Validate SQL queries
def validate_query(query):
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT", "COUNT", "SUM", "AVG", "MIN", "MAX", "WITH", "HAVING"]
    query_upper = query.upper()
    if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
        return False
    forbidden = ["DELETE", "UPDATE", "INSERT", "DROP", "TRUNCATE", "ALTER", "CREATE"]
    if any(kw in query_upper for kw in forbidden):
        return False
    # Limit complexity (e.g., max 5 joins)
    join_count = len(re.findall(r'\bJOIN\b', query_upper))
    if join_count > 5:
        return False
    return True

# Define SQL chain
def get_sql_chain(complexity: str):
    schema = """
    Database Schema:
    - admin_logs: adminlogs_id (PK), action_type (INSERT/UPDATE/DELETE), admin_id (FK to employees), approved_by_owner (FK to employees), details (JSON), created_at
    - categories: category_id (PK), category_name, created_at, updated_at
    - discount_logs: discount_id (PK), invoice_id (FK to invoices), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - employees: employee_id (PK), first_name, last_name, role (Owner/Admin/Cashier), email, password_hash, created_at, updated_at, last_password_change
    - inventory_logs: log_id (PK), product_id (FK to products), change_type (Sale/Restock/Adjustment), quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash/Card/Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - sync_log: id (PK), table_name, record_id, action (INSERT/UPDATE/DELETE), timestamp, synced
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address, created_at, updated_at
    - void_logs: void_id (PK), invoice_id (FK to invoices), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    """
    template = """
    You are an expert SQL assistant for the SCC School Store Database.
    Generate an accurate SQL query based on the schema to answer the user's question.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Query Complexity:** {complexity}

    **Instructions:**
    - Use 'today' as {current_sg_date} for WHERE clauses (e.g., WHERE order_date = '{current_sg_date}').
    - Use explicit JOIN syntax with table aliases (e.g., p for products, i for invoices).
    - Leverage indexes (e.g., idx_invoices_date, idx_products_name).
    - Use aggregate functions (COUNT, SUM, AVG) for summarization.
    - Support complex queries with subqueries, CTEs, or window functions if needed for advanced analytics.
    - Order results by relevance (e.g., date DESC for recent data).
    - Avoid non-existent tables/columns.
    - Limit results to 1000 rows unless specified.
    - For complex queries, prioritize performance (e.g., use indexed columns, avoid excessive joins).
    - Examples:
      - Simple: "What is the stock of SCC SHIRT?" → SELECT stock FROM products WHERE product_name = 'SCC SHIRT';
      - Complex: "What is the profit margin trend for Uniforms over 6 months?" → WITH monthly_profit AS (SELECT DATE_TRUNC('month', i.order_date) AS month, AVG(p.sale_price - p.purchase_price) / p.purchase_price * 100 AS margin FROM invoices i JOIN invoice_details id ON i.invoice_id = id.invoice_id JOIN products p ON id.product_id = p.product_id JOIN categories c ON p.category_id = c.category_id WHERE c.category_name = 'Uniforms' AND i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 6 MONTH) GROUP BY month) SELECT month, margin FROM monthly_profit ORDER BY month;

    **User Question:** {question}

    Return ONLY the SQL query.
    """
    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "llama3-8b-8192",
        "llama-3.3-70b-versatile",
        "llama3-70b-8192",
        "gemma2-9b-it",
    ]
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

    **Original Question:** {question}
    **Schema:** {schema}
    **Complexity:** {complexity}

    Return ONLY the SQL query. Ensure:
    1. Starts with SELECT or WITH
    2. Uses explicit JOINs with aliases
    3. No comments or markdown
    4. Valid per schema
    5. Optimized for performance (e.g., use indexes, limit joins)
    """
    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)
    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda x: x["current_sg_date"],
            current_sg_datetime=lambda x: x["current_sg_datetime"],
            chat_summary=lambda x: " ".join([msg.content for msg in x["chat_history"][-5:]]),
            complexity=lambda x: x["complexity"]
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

# Generate AI response
def get_response(user_query: str, chat_history: list, complexity: str):
    time_keywords = ["current time", "what time is it", "date and time", "today's date", "now"]
    data_keywords = ["sales", "invoice", "product", "category", "stock", "revenue", "order", "employee", "payment", "quantity", "price", "total", "discount", "due", "paid", "inventory", "void", "profit", "margin", "trend"]
    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        return f"Current time and date: {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None
    else:
        singapore_tz = pytz.timezone('Asia/Singapore')
        now_sg = datetime.datetime.now(singapore_tz)
        current_sg_date = now_sg.strftime('%Y-%m-%d')
        current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')
        sql_chain = get_sql_chain(complexity)
        raw_query = sql_chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
            "current_sg_date": current_sg_date,
            "current_sg_datetime": current_sg_datetime,
            "complexity": complexity
        })
        query = raw_query.split(";")[0] + ";"
        query = query.replace("```sql", "").replace("```", "").strip()
        query = "\n".join([line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))])
        if not validate_query(query):
            # Attempt to rephrase query
            rephrase_template = """
            Rephrase the following query to make it clearer and compatible with SQL SELECT queries:
            **Original Query:** {query}
            Return the rephrased query as plain text.
            """
            rephrase_chain = (
                ChatPromptTemplate.from_template(rephrase_template)
                | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
                | StrOutputParser()
            )
            rephrased_query = rephrase_chain.invoke({"query": user_query})
            st.warning(f"Invalid query. Trying rephrased query: {rephrased_query}")
            raw_query = sql_chain.invoke({
                "question": rephrased_query,
                "chat_history": chat_history,
                "current_sg_date": current_sg_date,
                "current_sg_datetime": current_sg_datetime,
                "complexity": complexity
            })
            query = raw_query.split(";")[0] + ";"
            query = query.replace("```sql", "").replace("```", "").strip()
            query = "\n".join([line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))])
            if not validate_query(query):
                return "Unable to generate a valid database query. Please rephrase your question.", None
        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return "No data retrieved. Try rephrasing your question or expanding the time frame.", None
        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}
        - **Complexity:** {complexity}

        **Guidelines:**
        1. If empty results, suggest: "No data found. Try a broader time frame or different product."
        2. Highlight insights (e.g., highest/lowest values, trends, comparisons).
        3. Use markdown: **bold** for emphasis, - for lists, ``` for code.
        4. Use ₱ for monetary values.
        5. For complex queries, include statistical insights (e.g., averages, growth rates).
        6. Keep concise (<300 words for simple, <500 for complex).
        7. If results are large, summarize key points.
        """
        chain = (
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | ChatPromptTemplate.from_template(response_template)
            | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
            | StrOutputParser()
        )
        natural_response = chain.invoke({
            "question": user_query,
            "response": json.dumps(data, indent=2),
            "chat_history": chat_history,
            "complexity": complexity
        })
        return natural_response, data

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    # Prioritize monetary columns for financial queries
    monetary_columns = [col for col in numerical_columns if any(kw in col.lower() for kw in ["total", "subtotal", "price", "paid", "due", "discount"])]
    if date_columns and numerical_columns:
        return "line", (date_columns[0], monetary_columns[0] if monetary_columns else numerical_columns[0])
    elif categorical_columns and numerical_columns and len(categorical_columns) >= 2:
        unique_categories = len(df[categorical_columns[0]].unique())
        if unique_categories <= 10 and "breakdown" in query_lower:
            return "stacked_bar", (categorical_columns[0], monetary_columns[0] if monetary_columns else numerical_columns[0], categorical_columns[1])
        elif unique_categories <= 6 and "percentage" in query_lower:
            return "pie", (categorical_columns[0], monetary_columns[0] if monetary_columns else numerical_columns[0])
        else:
            return "bar", (categorical_columns[0], monetary_columns[0] if monetary_columns else numerical_columns[0])
    elif numerical_columns and len(numerical_columns) >= 2 and any(kw in query_lower for kw in ["stock", "price", "margin"]):
        return "scatter", (numerical_columns[0], numerical_columns[1])
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
                        st.rerun()
    else:
        if st.session_state.user["role"] in ["Owner", "Admin"]:
            st.title("Chat with AcaSquad AI")
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
                if st.button("Refresh Data"):
                    st.cache_data.clear()
                    st.success("Data cache cleared. Fetching fresh data...")
                    st.rerun()
                complexity = st.radio("Query Complexity", ["Simple", "Advanced"], help="Simple: Basic lookups (e.g., stock levels). Advanced: Analytics (e.g., trends, margins).")
                with st.expander("Recent Queries"):
                    selected_query = st.selectbox("Select a recent query to reuse:", [""] + st.session_state.query_history[-10:])
                    if selected_query:
                        handle_query(selected_query, complexity.lower())
                with st.expander("📈 Sales Performance", expanded=True):
                    sales_queries = [
                        "What are the best-selling products from the first invoice to today?",
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
                            handle_query(q, complexity.lower())
                with st.expander("📦 Inventory Management"):
                    inventory_queries = [
                        "Which products are out of stock?",
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?",
                        "What is the total value of current inventory?",
                        "What is the value of inventory by category?",
                        "How many products do we have in total?",
                        "What are the product categories we have?",
                        "List all products added in the last 30 days."
                    ]
                    for q in inventory_queries:
                        if st.button(q, key=f"inv_{q}"):
                            handle_query(q, complexity.lower())
                with st.expander("👥 Employee Performance"):
                    employee_queries = [
                        "Who is the top-performing employee this month?",
                        "What are the total sales by each employee this week?",
                        "Which employee has the highest number of transactions today?",
                        "Who is currently logged in?",
                        "What are the login and logout times for Felisha Guevarra today?",
                        "How many times has each employee logged in this month?"
                    ]
                    for q in employee_queries:
                        if st.button(q, key=f"emp_{q}"):
                            handle_query(q, complexity.lower())
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
                        "Which products have the highest discounts applied?"
                    ]
                    for q in financial_queries:
                        if st.button(q, key=f"fin_{q}"):
                            handle_query(q, complexity.lower())
                with st.expander("🎟️ Discounts and Voids"):
                    discount_void_queries = [
                        "What discounts were applied this week?",
                        "Which products received discounts today?",
                        "How many voided transactions occurred this month?",
                        "What is the total amount voided this week?",
                        "Who approved the most discounts this month?"
                    ]
                    for q in discount_void_queries:
                        if st.button(q, key=f"dv_{q}"):
                            handle_query(q, complexity.lower())
                with st.expander("🏪 Store Operations"):
                    ops_queries = [
                        "What is the busiest hour of the day for sales?",
                        "Which day of the week has the highest foot traffic?",
                        "What is the average number of transactions per day?",
                        "What is the average time between login and first transaction for employees?",
                        "How many transactions were completed in the last hour?",
                        "Show me the inventory changes for SCC SHIRT this week.",
                        "What are the most recent inventory adjustments?"
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q}"):
                            handle_query(q, complexity.lower())
                with st.expander("🔍 Advanced Analytics"):
                    analytics_queries = [
                        "What is the profit margin for SCC SHIRT over the last 3 months?",
                        "How many units of SCC Booklet were sold this month?",
                        "What is the sales history for SCC SHIRT?",
                        "Which product category has the highest profit margin this year?",
                        "What is the average price of products in each category?",
                        "Which products should we reorder soon?",
                        "What is the revenue trend by category over the last 6 months?",
                        "Which employees have the highest sales growth rate?"
                    ]
                    for q in analytics_queries:
                        if st.button(q, key=f"analytics_{q}"):
                            handle_query(q, complexity.lower())
            display_chat_history()
            user_query = st.chat_input("Type a message (e.g., 'What is the profit margin trend for Uniforms?')...")
            if user_query:
                handle_query(user_query, complexity.lower())
        else:
            st.error("Access denied. Please contact the Admin.")
            if st.button("Logout"):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.rerun()

if __name__ == "__main__":
    main()

# Hide Streamlit UI elements
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
