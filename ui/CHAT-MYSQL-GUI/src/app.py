import streamlit as st
import streamlit.components.v1 as components
import requests
import json
import pandas as pd
import matplotlib.pyplot as plt
from urllib.parse import quote
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
import datetime
import pytz
import re

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

# Function to authenticate user
def authenticate(email, password):
    try:
        response = requests.post(
            st.secrets["API_URL"],
            params={"action": "authenticate_user", "key": st.secrets["API_KEY"]},
            json={"email": email, "password": password}
        )
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {}

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

# Function to parse date ranges from query
def parse_date_range(query):
    query_lower = query.lower()
    singapore_tz = pytz.timezone('Asia/Singapore')
    now = datetime.datetime.now(singapore_tz)
    today = now.strftime('%Y-%m-%d')
    
    # Regex for specific date/time ranges
    date_time_pattern = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)'
    date_pattern = r'(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})'
    time_pattern = r'(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)'
    
    # Specific date/time range
    match = re.search(date_time_pattern, query)
    if match:
        try:
            start = datetime.datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
            end = datetime.datetime.strptime(match.group(2), '%Y-%m-%d %H:%M:%S')
            return start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    # Date range
    match = re.search(date_pattern, query)
    if match:
        return f"{match.group(1)} 00:00:00", f"{match.group(2)} 23:59:59"
    
    # Time range today
    match = re.search(time_pattern, query_lower)
    if match:
        try:
            start_time = datetime.datetime.strptime(match.group(1), '%I:%M %p').strftime('%H:%M:00')
            end_time = datetime.datetime.strptime(match.group(2), '%I:%M %p').strftime('%H:%M:59')
            return f"{today} {start_time}", f"{today} {end_time}"
        except:
            pass
    
    # Keywords
    if "today" in query_lower:
        return f"{today} 00:00:00", f"{today} 23:59:59"
    if "this week" in query_lower:
        start = (now - datetime.timedelta(days=now.weekday())).strftime('%Y-%m-%d')
        return f"{start} 00:00:00", f"{today} 23:59:59"
    if "this month" in query_lower:
        start = now.replace(day=1).strftime('%Y-%m-%d')
        return f"{start} 00:00:00", f"{today} 23:59:59"
    if "this year" in query_lower:
        start = now.replace(month=1, day=1).strftime('%Y-%m-%d')
        return f"{start} 00:00:00", f"{today} 23:59:59"
    
    # Default: today
    return f"{today} 00:00:00", f"{today} 23:59:59"

# Function to handle queries
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

# Function to display chat history
def display_chat_history():
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="dist/img/ai.png"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="dist/img/Human.png"):
                st.markdown(message.content)

# Function to clear chat
def clear_chat():
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
    ]
    st.success("Chat history cleared. Starting a new conversation!")

# Function to fetch data from API
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

# Function to validate SQL queries
def validate_query(query):
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return False, "Query does not start with SELECT"
    forbidden = ["DELETE", "UPDATE", "INSERT", "DROP", "ALTER", "TRUNCATE", "CREATE", "REPLACE"]
    for kw in forbidden:
        if kw in query_upper:
            return False, f"Query contains forbidden keyword: {kw}"
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "GROUP BY", "ORDER BY", "LIMIT", "HAVING", "COUNT", "SUM", "AVG", "MAX", "MIN", "ROUND", "COALESCE", "STR_TO_DATE", "CONCAT"]
    if not any(kw in query_upper for kw in allowed_keywords):
        return False, "Query lacks required SQL keywords"
    return True, ""

# Function to define SQL chain
def get_sql_chain():
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

    template = """
    You are an expert SQL assistant for the SCC School Store Database. Generate a valid, accurate SQL query based on the user's question, adhering strictly to the provided schema and instructions.

    **Database Schema:**
    {schema}

    **Current Date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current Datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)
    **Date Range:** From {date_from} to {date_to}

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Generate SELECT queries only, starting with SELECT.
    - Use INNER JOIN for data integrity unless LEFT JOIN is explicitly needed.
    - Avoid row duplication:
      - For invoices, use COUNT(DISTINCT i.invoice_id).
      - For revenue, use SUM(i.total).
      - For profit, calculate SUM(i.total) - SUM(id.quantity * p.purchase_price).
    - Filter with WHERE i.total > 0 to exclude invalid invoices.
    - Use STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') for datetime comparisons.
    - Apply date filters with BETWEEN '{date_from}' AND '{date_to}' if specified.
    - If no period is provided, default to today ({current_sg_date} 00:00:00 to {current_sg_datetime}).
    - Use ROUND(value, 2) for monetary values.
    - For best-selling products, sort by SUM(id.quantity) DESC.
    - Group by unique IDs (e.g., invoice_id, product_id) alongside descriptive fields.
    - Return empty result sets if no data is found.
    - Do not use backticks, comments, or markdown in the query.
    - Ensure the query is executable without errors.

    **Query Mappings:**
    - "overview statistics":
      WITH invoice_stats AS (
          SELECT 
              COUNT(DISTINCT i.invoice_id) AS total_invoices,
              ROUND(AVG(i.total), 2) AS avg_sales_value,
              SUM(i.total) AS total_revenue
          FROM invoices i
          WHERE i.total > 0
          AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') BETWEEN '{date_from}' AND '{date_to}'
      ),
      cost_stats AS (
          SELECT 
              COALESCE(SUM(id.quantity * p.purchase_price), 0) AS base_cost
          FROM invoices i
          INNER JOIN invoice_details id ON id.invoice_id = i.invoice_id
          INNER JOIN products p ON id.product_id = p.product_id
          WHERE i.total > 0
          AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') BETWEEN '{date_from}' AND '{date_to}'
      )
      SELECT 
          i_stats.total_invoices,
          i_stats.avg_sales_value,
          i_stats.total_revenue,
          c_stats.base_cost,
          (i_stats.total_revenue - c_stats.base_cost) AS profit,
          ROUND((i_stats.total_revenue - c_stats.base_cost) / i_stats.total_revenue * 100, 1) AS profit_margin,
          (SELECT COUNT(*) FROM products p WHERE p.stock <= p.reorder_level) AS low_stock_count,
          (SELECT p.product_name 
           FROM invoice_details id2
           INNER JOIN products p ON id2.product_id = p.product_id
           INNER JOIN invoices i2 ON id2.invoice_id = i2.invoice_id
           WHERE i2.total > 0
           AND STR_TO_DATE(CONCAT(i2.order_date, ' ', i2.order_time), '%Y-%m-%d %H:%i:%s') BETWEEN '{date_from}' AND '{date_to}'
           GROUP BY p.product_id, p.product_name
           ORDER BY SUM(id2.quantity) DESC
           LIMIT 1) AS top_product
      FROM invoice_stats i_stats
      CROSS JOIN cost_stats c_stats
    - "best-selling products of all time":
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      GROUP BY p.product_id, p.product_name 
      ORDER BY total_sold DESC
    - "top 5 best-selling products this month":
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE()) 
      GROUP BY p.product_id, p.product_name 
      ORDER BY total_sold DESC 
      LIMIT 5
    - "total revenue for period":
      SELECT SUM(i.total) AS total_revenue 
      FROM invoices i 
      WHERE i.total > 0 
      AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') BETWEEN '{date_from}' AND '{date_to}'
    - "invoices in period":
      SELECT i.invoice_id, i.order_date, i.order_time, i.subtotal, i.discount, i.total, i.paid, i.due, i.payment_type,
             GROUP_CONCAT(CONCAT(id.quantity, ' ', p.product_name, ' (₱', id.total_price, ')')) AS items
      FROM invoices i 
      INNER JOIN invoice_details id ON id.invoice_id = i.invoice_id
      INNER JOIN products p ON id.product_id = p.product_id
      WHERE i.total > 0 
      AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') BETWEEN '{date_from}' AND '{date_to}'
      GROUP BY i.invoice_id, i.order_date, i.order_time, i.subtotal, i.discount, i.total, i.paid, i.due, i.payment_type

    **User Question:** {question}

    Generate a single, executable SQL query without backticks, comments, or markdown formatting:
    """

    prompt = ChatPromptTemplate.from_template(template)
    llm = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
    return prompt | llm | StrOutputParser()

# Function to generate response
def get_response(user_query: str, chat_history: list):
    time_keywords = ["current time", "what time is it", "date and time", "today's date", "now"]
    if any(keyword in user_query.lower() for keyword in time_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        return f"Current time in Singapore: {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None
    
    singapore_tz = pytz.timezone('Asia/Singapore')
    now_sg = datetime.datetime.now(singapore_tz)
    current_sg_date = now_sg.strftime('%Y-%m-%d')
    current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')
    
    date_from, date_to = parse_date_range(user_query)
    
    sql_chain = get_sql_chain()
    raw_query = sql_chain.invoke({
        "current_sg_date": current_sg_date,
        "current_sg_datetime": current_sg_datetime,
        "date_from": date_from,
        "date_to": date_to,
        "chat_summary": " ".join([msg.content for msg in chat_history[-3:]]),
        "question": user_query
    })
    
    query = raw_query.strip()
    if query.endswith(';'):
        query = query[:-1]
    query = query.replace("```sql", "").replace("```", "").strip()
    query = "\n".join(
        [line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))]
    )
    query = query + ";"
    
    is_valid, reason = validate_query(query)
    if not is_valid:
        return f"Invalid query generated: {reason}. Please rephrase your question.", None
    
    fetch_data_from_api.clear()
    data = fetch_data_from_api("execute_query", {"query": query})
    if data is None:
        return f"No data retrieved for {date_from} to {date_to}. Try rephrasing your query.", None
    
    response_template = """
    Generate a natural language response based on:
    - **Question:** {question}
    - **Results:** {response}
    - **Period:** {date_from} to {date_to}

    **Guidelines:**
    - If results are empty, state: "No data found for {date_from} to {date_to}."
    - Use ₱ for monetary values, formatted to 2 decimal places.
    - Use 'units' for quantities.
    - Highlight key insights (e.g., **Top Product**: SCC SHIRT).
    - Keep response concise, under 150 words.
    - Provide clear, actionable information based on the data.
    """
    
    chain = (
        RunnablePassthrough.assign(
            response=lambda _: json.dumps(data, indent=2),
            date_from=lambda _: date_from,
            date_to=lambda _: date_to
        )
        | ChatPromptTemplate.from_template(response_template)
        | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
    
    natural_response = chain.invoke({
        "question": user_query,
        "chat_history": chat_history,
    })
    
    return natural_response, data

# Function to determine chart type
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
                if submit and authenticate(email, password):
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
                with st.expander("📈 Sales Performance"):
                    sales_queries = [
                        "What are the best-selling products of all time?",
                        "What are the top 5 best-selling products this month?",
                        "What is the total revenue from 2025-04-14 15:00:00 to 2025-04-14 15:59:13?",
                        "List invoices from 2025-04-14 15:00:00 to 2025-04-14 15:59:13"
                    ]
                    for q in sales_queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q)
            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query)
        else:
            st.error("Access denied. Contact Admin.")
            if st.button("Logout"):
                st.session_state.authenticated = False
                st.session_state.user = None
                st.rerun()

if __name__ == "__main__":
    main()

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
