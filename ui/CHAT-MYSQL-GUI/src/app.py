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
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
    ]
if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = True  # Enabled by default per DEBUG_MODE = "true"

# Authentication function
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
            st.error(f"Login failed: {data.get('error', 'Invalid credentials')}")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
    return False

# Handle user query
def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            natural_response, data, debug_info = get_response(query, st.session_state.chat_history)
            if st.session_state.debug_mode:
                st.markdown("### Debug Info")
                st.write(f"**Raw Query**: {debug_info['raw_query']}")
                st.write(f"**Cleaned Query**: {debug_info['cleaned_query']}")
                st.write(f"**API Response**: {debug_info['api_response']}")
                st.write(f"**API Status Code**: {debug_info['status_code']}")
                st.write(f"**Raw Data**: {debug_info['raw_data']}")
        except Exception as e:
            natural_response = f"An error occurred: {str(e)}. Please try rephrasing your question or check the database connection."
            data = None
            debug_info = {"raw_query": "N/A", "cleaned_query": "N/A", "api_response": str(e), "status_code": "N/A", "raw_data": "N/A"}
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            # Preprocess data
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "profit", "margin", "amount_discounted"]):
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
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 1 or len(df.columns) > 1:
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

# Fetch data from API
@st.cache_data(ttl=300, show_spinner=False)
def fetch_data_from_api(action: str, params: dict = None, _cache_buster: str = "") -> tuple:
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
        status_code = response.status_code
        if not response.text.strip():
            return None, "Empty response from API", status_code, None
        data = response.json()
        if data.get("status") == "success":
            return data["data"], "Success", status_code, data
        else:
            return None, data.get("error", "Unknown error"), status_code, data
    except requests.RequestException as e:
        return None, str(e), "N/A", None

# Validate SQL query
def validate_query(query):
    allowed_keywords = [
        "SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT",
        "SUM", "COUNT", "AVG", "MIN", "MAX", "JSON_EXTRACT", "BETWEEN", "LIKE", "IN", "AS"
    ]
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        raise ValueError("Query must start with SELECT")
    if not any(kw in query_upper for kw in allowed_keywords[1:]):  # Exclude SELECT from keyword check
        raise ValueError("Query must contain at least one of: " + ", ".join(allowed_keywords[1:]))
    return True

# Format response
def format_response(question: str, data: list) -> str:
    if not data or not isinstance(data, list) or len(data) == 0:
        if "profit" in question.lower() or "base cost" in question.lower():
            return ("No data found. This may be due to missing purchase price information or no sales records. "
                    "Please check the products table for valid purchase_price values. "
                    "Would you like to see products with missing purchase prices?")
        return "Sorry, I couldn't retrieve the data. Please try again or check the database connection. Would you like more details or to check specific products?"

    question_lower = question.lower()
    try:
        # Convert string values to numeric where applicable
        result = data[0]
        for key in ['total_revenue', 'base_cost', 'total_profit', 'profit_margin']:
            if key in result:
                if result[key] is None:
                    result[key] = 0.0
                elif isinstance(result[key], str):
                    try:
                        result[key] = float(result[key].replace(',', ''))
                    except (ValueError, AttributeError):
                        result[key] = 0.0
                elif not isinstance(result[key], (int, float)):
                    result[key] = 0.0

        warning = ""
        if ("base cost" in question_lower or "profit" in question_lower) and result.get('base_cost', 0.0) == 0.0:
            warning = "\n\n⚠️ Warning: Base cost is 0. This may indicate missing purchase_price data in the products table."
        if "profit" in question_lower and result.get('total_profit', 0.0) == 0.0:
            warning = "\n\n⚠️ Warning: Profit is 0. This may indicate missing purchase_price data or no sales records."

        if "best selling products" in question_lower:
            response = "Top-selling products in your store:\n\n"
            for row in data[:3]:
                response += f"- **{row['product_name']}** with **{row['total_quantity']}** units sold\n"
            response += f"**{data[0]['product_name']}** takes the top spot, followed by **{data[1]['product_name']}**."
        elif "total revenue" in question_lower:
            revenue = result.get('total_revenue', 0.0)
            response = f"Total Revenue: **₱{revenue:,.2f}**\n\nThis reflects all sales after discounts, indicating strong performance."
        elif "total base cost" in question_lower:
            cost = result.get('base_cost', 0.0)
            response = f"Total Base Cost: **₱{cost:,.2f}**\n\nThis covers the cost of goods sold, key for profitability analysis."
            response += warning
        elif "total profit" in question_lower:
            profit = result.get('total_profit', 0.0)
            response = f"Total Profit: **₱{profit:,.2f}**\n\nThis is your revenue minus base costs, showing financial health."
            response += warning
        elif "profit margin" in question_lower:
            margin = result.get('profit_margin', 0.0)
            response = f"Profit Margin: **{margin:.2f}%**\n\nThis shows the percentage of revenue retained as profit."
        else:
            response = json.dumps(data, indent=2)
    except (KeyError, TypeError, ValueError) as e:
        response = f"Error formatting response: {str(e)}. Please check the database or try rephrasing the query."
    
    response += "\n\nWould you like more details or to check specific products?"
    return response

# Define SQL chain
def get_sql_chain():
    schema = """
    Database Schema:
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash/Card/Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role (Owner/Admin/Cashier), email, password_hash, created_at, updated_at, last_password_change
    - admin_logs: adminlogs_id (PK), action_type (INSERT/UPDATE/DELETE), admin_id (FK to employees), approved_by_owner (FK to employees), details (JSON), created_at
    - discount_logs: discount_id (PK), invoice_id (FK to invoices), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type (Sale/Restock/Adjustment), quantity, log_date, notes, created_at, updated_at
    - sync_log: id (PK), table_name, record_id, action (INSERT/UPDATE/DELETE), timestamp, synced
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address, created_at, updated_at
    - void_logs: void_id (PK), invoice_id (FK to invoices), cashier_id (FK to employees), admin_email (FK to employees.email), details (JSON), created_at
    """

    template = """
    You are an AI assistant for the SCC School Store Database, generating SQL queries for MariaDB 10.6.21.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use 'today' as '{current_sg_date}' (e.g., WHERE order_date = '{current_sg_date}').
    - For revenue, use SUM(i.total) from invoices to account for discounts.
    - For base cost, use SUM(id.quantity * COALESCE(p.purchase_price, 0)) from invoice_details id JOIN products p.
    - For profit, use SUM(i.total - (id.quantity * COALESCE(p.purchase_price, 0))) from invoices i JOIN invoice_details id JOIN products p.
    - For profit margin, use ROUND((SUM(i.total - (id.quantity * COALESCE(p.purchase_price, 0))) / SUM(i.total)) * 100, 2) from invoices i JOIN invoice_details id JOIN products p.
    - For best-selling products, use SUM(id.quantity) from invoice_details id JOIN products p, grouped by product_id.
    - If asked about missing purchase prices, use SELECT product_id, product_name FROM products WHERE purchase_price IS NULL OR purchase_price = 0.
    - Use COALESCE to handle NULL purchase_price values, assuming 0 if NULL.
    - If the query asks for 'all time' or 'from the very first invoice', do NOT add a date filter.
    - Ensure queries are valid for MariaDB 10.6.21.
    - Return only the SQL query, no explanations.

    **User Question:** {question}
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

    Return ONLY the final SQL query. Ensure:
    1. Starts with SELECT
    2. Uses explicit JOIN syntax with aliases
    3. Handles JSON_EXTRACT for JSON fields
    4. Uses COALESCE for purchase_price in cost/profit calculations
    5. Valid for MariaDB 10.6.21
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)
    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda x: x["current_sg_date"],
            current_sg_datetime=lambda x: x["current_sg_datetime"],
            chat_summary=lambda x: " ".join([msg.content for msg in x["chat_history"][-5:]])
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
def get_response(user_query: str, chat_history: list):
    time_keywords = ["current time", "what time is it", "date and time", "today's date", "now"]
    data_keywords = [
        "sales", "invoice", "product", "category", "stock", "revenue", "order", "employee",
        "payment", "quantity", "price", "total", "discount", "due", "paid", "inventory",
        "profit", "margin"
    ]
    debug_info = {"raw_query": "", "cleaned_query": "", "api_response": "", "status_code": "", "raw_data": ""}
    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        return f"Your current time and date is {current_time.strftime('%Y-%m-%d %H:%M:%S')} in Singapore.", None, debug_info
    else:
        singapore_tz = pytz.timezone('Asia/Singapore')
        now_sg = datetime.datetime.now(singapore_tz)
        current_sg_date = now_sg.strftime('%Y-%m-%d')
        current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

        sql_chain = get_sql_chain()
        raw_query = sql_chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
            "current_sg_date": current_sg_date,
            "current_sg_datetime": current_sg_datetime
        })
        debug_info["raw_query"] = raw_query

        # Extract SQL query
        query_lines = raw_query.split("\n")
        sql_query = ""
        in_sql_block = False
        for line in query_lines:
            line = line.strip()
            if line.upper().startswith("SELECT"):
                in_sql_block = True
                sql_query = line
            elif in_sql_block:
                sql_query += "\n" + line
                if ";" in line:
                    break
        query = sql_query.replace("```sql", "").replace("```", "").strip()
        if not query:
            raise ValueError("No valid SQL query extracted from response")
        if not query.endswith(";"):
            query += ";"
        query = "\n".join(
            [line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))]
        )
        debug_info["cleaned_query"] = query

        # Validate query
        try:
            validate_query(query)
        except ValueError as e:
            debug_info["api_response"] = str(e)
            return f"Invalid SQL query: {str(e)}. Please rephrase your question.", None, debug_info

        data, api_response, status_code, raw_data = fetch_data_from_api("execute_query", {"query": query})
        debug_info["api_response"] = api_response
        debug_info["status_code"] = status_code
        debug_info["raw_data"] = json.dumps(raw_data, indent=2) if raw_data else "No data returned"
        if data is None:
            return f"Couldn't retrieve data. API error: {api_response} (Status: {status_code}). Try rephrasing or checking the database connection.", None, debug_info

        natural_response = format_response(user_query, data)
        return natural_response, data, debug_info

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2 or len(df) < 2:  # Skip charts for single records
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
        if unique_categories <= 6 and "percentage" in question_lower:
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
                        st.rerun()
    else:
        if st.session_state.user["role"] in ["Owner", "Admin"]:
            st.title("Chat with AcaSquad AI")
            with st.sidebar:
                st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
                st.markdown(f"Logged in as {st.session_state.user['first_name']} {st.session_state.user['last_name']} ({st.session_state.user['role']})")
                st.checkbox("Debug Mode", key="debug_mode", value=True)  # Default to True
                if st.button("Logout"):
                    st.session_state.authenticated = False
                    st.session_state.user = None
                    st.rerun()
                if st.button("Clear Chat"):
                    clear_chat()
                    st.rerun()
                with st.expander("📈 Sales Performance", expanded=True):
                    queries = [
                        "What are the best-selling products this month?",
                        "What is the total revenue for today?",
                        "What is the daily sales trend for this month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q)
                with st.expander("📦 Inventory Management"):
                    queries = [
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?",
                        "What are the most recent inventory adjustments?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"inv_{q}"):
                            handle_query(q)
                with st.expander("👥 Employee Performance"):
                    queries = [
                        "Who is currently logged in?",
                        "What are the total sales by each employee this week?",
                        "Who has the highest number of transactions today?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"emp_{q}"):
                            handle_query(q)
                with st.expander("💰 Financial Insights"):
                    queries = [
                        "What is the total amount due from unpaid invoices?",
                        "What is the total discount given this month?",
                        "What is the profit margin for SCC SHIRT this year?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"fin_{q}"):
                            handle_query(q)
            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query)
        else:
            st.error("Access restricted. Contact Admin.")
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
