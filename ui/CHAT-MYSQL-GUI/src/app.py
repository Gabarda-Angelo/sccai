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

# Set page configuration (must be the first Streamlit command)
st.set_page_config(
    page_title="AcaSquad AI",
    page_icon=":speech_balloon:",
    layout="wide"
)

# Function to show pop-up messages using a JavaScript alert
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

# Initialize session state for authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user = None

# Function to authenticate user via API
def authenticate(email, password):
    """Authenticate a user by sending credentials to the API."""
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

        if response.status_code == 200:
            if data.get("status") == "success" and "data" in data:
                st.session_state.authenticated = True
                st.session_state.user = data["data"]
                st.success("Login Successful!")
                return True
            else:
                error_message = data.get("error", "Invalid credentials")
                st.error(f"Login failed: {error_message}")
        else:
            error_message = data.get("error", "Unknown error")
            st.error(f"Login failed: {error_message} (Server error: {response.status_code})")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
    return False

# Function to handle user queries
def handle_query(query: str):
    """Process a user's query, update chat history, and display response."""
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
            # Preprocess data for charts
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "discount", "total_revenue", "avg_price", "net_total", "base_cost", "profit", "avg_sales_value", "total_inventory_value", "category_value"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                elif col.lower() in ["total_sold", "transaction_count", "login_count", "product_count", "total_products", "total_categories", "total_invoices"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')  # Keep as quantity
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
    """Render the chat history in the UI."""
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI", avatar="dist/img/ai.png"):
                st.markdown(message.content)
        elif isinstance(message, HumanMessage):
            with st.chat_message("Human", avatar="dist/img/Human.png"):
                st.markdown(message.content)

# Function to clear chat history
def clear_chat():
    """Reset the chat history to start a new conversation."""
    st.session_state.chat_history = [
        AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
    ]
    st.success("Chat history cleared. Starting a new conversation!")

# Function to fetch data from API with caching
@st.cache_data
def fetch_data_from_api(action: str, params: dict = None) -> dict:
    """Fetch data from the API based on the specified action and parameters."""
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
    """Validate that the SQL query is safe and executable."""
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"]
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        return False
    return all(any(kw in query_upper for kw in allowed_keywords) for line in query_upper.split("\n") if line.strip())

# Function to define SQL chain for query generation
def get_sql_chain():
    """Create a chain to generate SQL queries based on user input."""
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
    You are an AI assistant helping a user retrieve data from the SCC School Store Database via an API.
    Based on the provided table schema, generate an accurate SQL query to answer the user's question.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (format: YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (format: YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use explicit INNER JOINs for data integrity.
    - Group by unique identifiers (e.g., product_id, invoice_id) alongside names to avoid ambiguity.
    - For 'best-selling products,' use SUM(id.quantity) and order by total_sold DESC.
    - For revenue, use SUM(i.total) or SUM(id.total_price) as specified.
    - Exclude canceled/invalid invoices with WHERE i.total > 0.
    - Return empty result sets for no data, not errors.
    - Use DECIMAL for monetary fields; INTEGER for quantities.
    - Provide only the SQL query, without explanations.

    **Specific Query Mappings:**
    - "overview statistics":
      SELECT 
          ROUND(AVG(i.total), 2) AS avg_sales_value,
          SUM(i.discount) AS total_discount,
          COUNT(DISTINCT p.product_id) AS total_products,
          COUNT(DISTINCT c.category_id) AS total_categories,
          COUNT(i.invoice_id) AS total_invoices,
          SUM(i.total) AS total_revenue,
          SUM(i.total - i.discount) AS net_total,
          SUM(id.quantity * p.purchase_price) AS base_cost,
          (SUM(i.total - i.discount) - SUM(id.quantity * p.purchase_price)) AS profit
      FROM invoices i
      INNER JOIN invoice_details id ON id.invoice_id = i.invoice_id
      INNER JOIN products p ON id.product_id = p.product_id
      INNER JOIN categories c ON p.category_id = c.category_id
      WHERE i.total > 0
      AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s')
          BETWEEN '2025-02-14 00:00:00' AND '2025-04-13 13:41:26';
    - "best-selling products of all time":
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      GROUP BY p.product_id, p.product_name 
      ORDER BY total_sold DESC;
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
      LIMIT 5;
    - "product with highest sales this week":
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND i.order_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE() 
      GROUP BY p.product_id, p.product_name 
      ORDER BY total_sold DESC 
      LIMIT 1;
    - "best-selling products in each category":
      SELECT c.category_name, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      INNER JOIN categories c ON p.category_id = c.category_id 
      WHERE i.total > 0 
      GROUP BY c.category_id, c.category_name, p.product_id, p.product_name 
      HAVING SUM(id.quantity) = (
          SELECT MAX(total_sold)
          FROM (
              SELECT SUM(id2.quantity) AS total_sold
              FROM invoice_details id2
              INNER JOIN products p2 ON id2.product_id = p2.product_id
              INNER JOIN invoices i2 ON id2.invoice_id = i2.invoice_id
              WHERE i2.total > 0 AND p2.category_id = c.category_id
              GROUP BY p2.product_id
          ) AS sub
      )
      ORDER BY c.category_name;
    - "sales trend over the past year":
      SELECT DATE_FORMAT(i.order_date, '%Y-%m') AS month, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND i.order_date >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) 
      GROUP BY DATE_FORMAT(i.order_date, '%Y-%m') 
      ORDER BY month;
    - "daily sales trend for this month":
      SELECT i.order_date, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE()) 
      GROUP BY i.order_date 
      ORDER BY i.order_date;
    - "day of the week with highest sales":
      SELECT DAYNAME(i.order_date) AS day_of_week, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      GROUP BY DAYNAME(i.order_date) 
      ORDER BY total_sold DESC 
      LIMIT 1;
    - "total revenue this year":
      SELECT SUM(i.total) AS total_revenue 
      FROM invoices i 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE());
    - "total revenue for today":
      SELECT SUM(i.total) AS total_revenue 
      FROM invoices i 
      WHERE i.total > 0 
      AND i.order_date = CURDATE();
    - "average daily revenue this month":
      SELECT AVG(daily_total) AS avg_daily_revenue 
      FROM (
          SELECT i.order_date, SUM(i.total) AS daily_total 
          FROM invoices i 
          WHERE i.total > 0 
          AND YEAR(i.order_date) = YEAR(CURDATE()) 
          AND MONTH(i.order_date) = MONTH(CURDATE()) 
          GROUP BY i.order_date
      ) AS daily;
    - "revenue breakdown by product category":
      SELECT c.category_name, SUM(id.total_price) AS total_revenue 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      INNER JOIN categories c ON p.category_id = c.category_id 
      WHERE i.total > 0 
      GROUP BY c.category_id, c.category_name 
      ORDER BY total_revenue DESC;
    - "products out of stock":
      SELECT p.product_name, p.stock 
      FROM products p 
      WHERE p.stock = 0;
    - "products below reorder level":
      SELECT p.product_name, p.stock, p.reorder_level 
      FROM products p 
      WHERE p.stock < p.reorder_level;
    - "current stock levels for all products":
      SELECT p.product_name, p.stock 
      FROM products p 
      ORDER BY p.product_name;
    - "total value of current inventory":
      SELECT SUM(p.stock * p.sale_price) AS total_inventory_value 
      FROM products p;
    - "value of inventory by category":
      SELECT c.category_name, SUM(p.stock * p.sale_price) AS category_value 
      FROM products p 
      INNER JOIN categories c ON p.category_id = c.category_id 
      GROUP BY c.category_id, c.category_name;
    - "total number of products":
      SELECT COUNT(*) AS total_products 
      FROM products;
    - "product categories":
      SELECT c.category_name 
      FROM categories c;
    - "products added in last 30 days":
      SELECT p.product_name, p.created_at 
      FROM products p 
      WHERE p.created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY);
    - "top-performing employee this month":
      SELECT e.first_name, e.last_name, SUM(i.total) AS total_sales 
      FROM invoices i 
      INNER JOIN employees e ON i.employee_id = e.employee_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE()) 
      GROUP BY e.employee_id, e.first_name, e.last_name 
      ORDER BY total_sales DESC 
      LIMIT 1;
    - "total sales by each employee this week":
      SELECT e.first_name, e.last_name, SUM(i.total) AS total_sales 
      FROM invoices i 
      INNER JOIN employees e ON i.employee_id = e.employee_id 
      WHERE i.total > 0 
      AND i.order_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE() 
      GROUP BY e.employee_id, e.first_name, e.last_name 
      ORDER BY total_sales DESC;
    - "employee with highest transactions today":
      SELECT e.first_name, e.last_name, COUNT(i.invoice_id) AS transaction_count 
      FROM invoices i 
      INNER JOIN employees e ON i.employee_id = e.employee_id 
      WHERE i.total > 0 
      AND i.order_date = CURDATE() 
      GROUP BY e.employee_id, e.first_name, e.last_name 
      ORDER BY transaction_count DESC 
      LIMIT 1;
    - "currently logged in employees":
      SELECT e.first_name, e.last_name 
      FROM user_logins ul 
      INNER JOIN employees e ON ul.employee_id = e.employee_id 
      WHERE ul.login_time IS NOT NULL 
      AND ul.logout_time IS NULL;
    - "today’s login and logout times for all employees":
      SELECT e.first_name, e.last_name, ul.login_time, ul.logout_time 
      FROM user_logins ul 
      INNER JOIN employees e ON ul.employee_id = e.employee_id 
      WHERE DATE(ul.login_time) = CURDATE();
    - "employee login counts this month":
      SELECT e.first_name, e.last_name, COUNT(ul.log_id) AS login_count 
      FROM user_logins ul 
      INNER JOIN employees e ON ul.employee_id = e.employee_id 
      WHERE YEAR(ul.login_time) = YEAR(CURDATE()) 
      AND MONTH(ul.login_time) = MONTH(CURDATE()) 
      GROUP BY e.employee_id, e.first_name, e.last_name;
    - "sales invoices details for today":
      SELECT i.invoice_id, i.order_date, i.order_time, i.subtotal, i.discount, i.total, i.paid, i.due, i.payment_type 
      FROM invoices i 
      WHERE i.order_date = CURDATE();
    - "invoices from last week":
      SELECT i.invoice_id, i.order_date, i.order_time, i.subtotal, i.discount, i.total, i.paid, i.due, i.payment_type 
      FROM invoices i 
      WHERE i.order_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 13 DAY) AND DATE_SUB(CURDATE(), INTERVAL 7 DAY);
    - "total amount due from unpaid invoices":
      SELECT SUM(i.due) AS total_due 
      FROM invoices i 
      WHERE i.due > 0;
    - "average transaction value this month":
      SELECT AVG(i.total) AS avg_transaction_value 
      FROM invoices i 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE());
    - "most common payment method":
      SELECT i.payment_type, COUNT(*) AS usage_count 
      FROM invoices i 
      WHERE i.total > 0 
      GROUP BY i.payment_type 
      ORDER BY usage_count DESC 
      LIMIT 1;
    - "percentage of cash transactions":
      SELECT (COUNT(*) / (SELECT COUNT(*) FROM invoices WHERE total > 0)) * 100 AS cash_percentage 
      FROM invoices i 
      WHERE i.payment_type = 'Cash' 
      AND i.total > 0;
    - "card transactions this week":
      SELECT COUNT(*) AS card_transactions 
      FROM invoices i 
      WHERE i.payment_type LIKE '%Card%' 
      AND i.total > 0 
      AND i.order_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE();
    - "total discount given this month":
      SELECT SUM(i.discount) AS total_discount 
      FROM invoices i 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE());
    - "invoices with highest discounts this month":
      SELECT i.invoice_id, i.discount, GROUP_CONCAT(p.product_name) AS products 
      FROM invoices i 
      INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id 
      INNER JOIN products p ON id.product_id = p.product_id 
      WHERE i.discount > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE()) 
      GROUP BY i.invoice_id, i.discount 
      ORDER BY i.discount DESC 
      LIMIT 5;
    - "busiest hour for sales":
      SELECT HOUR(i.order_time) AS hour, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      GROUP BY HOUR(i.order_time) 
      ORDER BY total_sold DESC 
      LIMIT 1;
    - "day of week with highest foot traffic":
      SELECT DAYNAME(i.order_date) AS day_of_week, COUNT(i.invoice_id) AS transaction_count 
      FROM invoices i 
      WHERE i.total > 0 
      GROUP BY DAYNAME(i.order_date) 
      ORDER BY transaction_count DESC 
      LIMIT 1;
    - "average transactions per day":
      SELECT AVG(daily_count) AS avg_transactions 
      FROM (
          SELECT COUNT(*) AS daily_count 
          FROM invoices i 
          WHERE i.total > 0 
          GROUP BY i.order_date
      ) AS daily;
    - "average time between login and first transaction":
      SELECT e.first_name, e.last_name, AVG(TIMESTAMPDIFF(MINUTE, ul.login_time, MIN(STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s')))) AS avg_minutes 
      FROM user_logins ul 
      INNER JOIN employees e ON ul.employee_id = e.employee_id 
      INNER JOIN invoices i ON ul.employee_id = i.employee_id 
      WHERE i.total > 0 
      AND i.order_date = DATE(ul.login_time) 
      GROUP BY e.employee_id, e.first_name, e.last_name;
    - "transactions in last hour":
      SELECT COUNT(*) AS transaction_count 
      FROM invoices i 
      WHERE i.total > 0 
      AND STR_TO_DATE(CONCAT(i.order_date, ' ', i.order_time), '%Y-%m-%d %H:%i:%s') >= DATE_SUB(NOW(), INTERVAL 1 HOUR);
    - "inventory changes this week for all products":
      SELECT p.product_name, il.change_type, il.quantity, il.log_date, il.notes 
      FROM inventory_logs il 
      INNER JOIN products p ON il.product_id = p.product_id 
      WHERE il.log_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND CURDATE();
    - "recent inventory adjustments":
      SELECT p.product_name, il.change_type, il.quantity, il.log_date, il.notes 
      FROM inventory_logs il 
      INNER JOIN products p ON il.product_id = p.product_id 
      ORDER BY il.log_date DESC 
      LIMIT 10;
    - "profit margins for all products":
      SELECT p.product_id, p.product_name, ROUND((p.sale_price - p.purchase_price) / p.sale_price * 100, 2) AS profit_margin 
      FROM products p 
      ORDER BY profit_margin DESC;
    - "total units sold for all products this month":
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      AND MONTH(i.order_date) = MONTH(CURDATE()) 
      GROUP BY p.product_id, p.product_name 
      ORDER BY total_sold DESC;
    - "sales history for all products this year":
      SELECT p.product_name, DATE_FORMAT(i.order_date, '%Y-%m') AS month, SUM(id.quantity) AS total_sold 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      GROUP BY p.product_id, p.product_name, DATE_FORMAT(i.order_date, '%Y-%m') 
      ORDER BY p.product_name, month;
    - "category with highest sales this year":
      SELECT c.category_name, SUM(id.total_price) AS total_revenue 
      FROM invoice_details id 
      INNER JOIN products p ON id.product_id = p.product_id 
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id 
      INNER JOIN categories c ON p.category_id = c.category_id 
      WHERE i.total > 0 
      AND YEAR(i.order_date) = YEAR(CURDATE()) 
      GROUP BY c.category_id, c.category_name 
      ORDER BY total_revenue DESC 
      LIMIT 1;
    - "average price of products in each category":
      SELECT c.category_name, AVG(p.sale_price) AS avg_price 
      FROM products p 
      INNER JOIN categories c ON p.category_id = c.category_id 
      GROUP BY c.category_id, c.category_name;
    - "products to reorder soon":
      SELECT p.product_name, p.stock, p.reorder_level 
      FROM products p 
      WHERE p.stock < p.reorder_level;
    - "products within 10% of reorder level":
      SELECT COUNT(*) AS product_count 
      FROM products p 
      WHERE p.stock <= p.reorder_level * 1.1;

    **Guidelines:**
    - "Sales" means SUM(id.quantity) unless revenue (SUM(i.total)) is specified.
    - Use 'CURDATE()' for today, 'DATE_SUB(CURDATE(), INTERVAL X)' for periods.
    - For discounts, use i.discount from invoices table.
    - Ensure monetary values use ROUND(x, 2) for precision.
    - Verify category counts against product counts for consistency.

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
        **{
            f"proposal_{i}": prompt | llm | StrOutputParser()
            for i, llm in enumerate(proposal_llms)
        }
    )

    aggregator_template = """
    Synthesize the best SQL query from these proposals:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return ONLY the final SQL query without any explanations or formatting.
    The query must:
    1. Start with SELECT
    2. Use explicit INNER JOIN syntax
    3. Include WHERE i.total > 0 for invoice queries
    4. Group by unique IDs (e.g., product_id) alongside names
    5. Contain no comments or markdown
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)

    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda x: x["current_sg_date"],
            current_sg_datetime=lambda x: x["current_sg_datetime"],
            chat_summary=lambda x: " ".join([msg.content for msg in x["chat_history"][-3:]])
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

# Function to generate AI response
def get_response(user_query: str, chat_history: list):
    """Generate a natural language response and fetch data based on the user's query."""
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
        natural_response = f"Your current time and date is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
        return natural_response, None
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

        query = raw_query.split(";")[0] + ";"
        query = query.replace("```sql", "").replace("```", "").strip()
        query = "\n".join(
            [line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))]
        )

        if not validate_query(query):
            return "Failed to generate a valid database query. Please try again.", None

        # Clear cache for critical queries
        if any(kw in user_query.lower() for kw in ["best-selling", "sales", "revenue", "inventory", "overview"]):
            fetch_data_from_api.clear()
        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return "Couldn't retrieve data. Please try again or rephrase your question.", None 

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        1. If results are empty, state: "No data found for this query. This could be due to no records matching the criteria."
        2. For quantities (e.g., total_sold, total_invoices), use 'units', 'items', or 'records'.
        3. For monetary values, use peso sign (₱) and format to 2 decimal places.
        4. Highlight key insights (e.g., top item, highest value).
        5. Use markdown: **bold** for emphasis, - for lists.
        6. If total_discount = 0, note: "No discounts recorded, which is unusual for this period."
        7. If total_categories ≥ total_products, caution: "High category count relative to products; verify category assignments."
        8. Keep concise, under 200 words.
        """

        chain = (
            RunnablePassthrough.assign(
                response=lambda _: json.dumps(data, indent=2)
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

# Function to determine chart type for data visualization
def determine_chart_type(query, df):
    """Determine the appropriate chart type based on query and data."""
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

# Main application logic
def main():
    """Main function to run the AcaSquad AI application."""
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

            # Sidebar setup
            with st.sidebar:
                st.image("ui/CHAT-MYSQL-GUI/src/img/logo.png", use_container_width=True)
                st.markdown(f"Logged in as {st.session_state.user['first_name']} {st.session_state.user['last_name']} ({st.session_state.user['role']})")
                if st.button("Logout"):
                    st.session_state.authenticated = False
                    st.session_state.user = None
                    st.rerun()
                
                # Add Clear Chat button
                if st.button("Clear Chat"):
                    clear_chat()
                    st.rerun()

                # Quick Queries Expanders
                with st.expander("📊 Overview", expanded=True):
                    overview_queries = [
                        "Show overview statistics"
                    ]
                    for q in overview_queries:
                        if st.button(q, key=f"overview_{q}"):
                            handle_query(q)

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

            # Main area setup
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
