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
from retry import retry
import logging
import re
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set page configuration
st.set_page_config(
    page_title="AcaSquad AI",
    page_icon=":speech_balloon:",
    layout="wide"
)

# AI SQL Agent Class
class AISQLAgent:
    def __init__(self, api_url, api_key, groq_api_key, schema, allowed_tables):
        self.api_url = api_url
        self.api_key = api_key
        self.groq_api_key = groq_api_key
        self.schema = schema
        self.allowed_tables = allowed_tables
        self.llm = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=self.groq_api_key)

    def generate_sql_query(self, user_query, chat_history, current_sg_date, current_sg_datetime, product_name=None):
        # Extract date from user query (e.g., "May 3, 2025" -> '2025-05-03')
        date_pattern = r'on (\w+ \d{1,2}, \d{4})'
        match = re.search(date_pattern, user_query.lower())
        if match:
            specific_date = datetime.datetime.strptime(match.group(1), '%B %d, %Y').strftime('%Y-%m-%d')
        else:
            specific_date = current_sg_date  # Default to current date if not specified

        template = """
        You are an AI SQL Agent for the SCC School Store Database, generating precise SQL queries for MariaDB 10.6.21.

        **Database Schema:**
        {schema}

        **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
        **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

        **Conversation History:** {chat_history}

        **Instructions:**
        - Generate SQL queries valid for MariaDB 10.6.21, optimized for performance.
        - Use 'today' as '{current_sg_date}' for daily queries unless a specific date is provided.
        - For datetime filtering, use CONCAT(i.order_date, ' ', i.order_time) for invoices.
        - For date ranges, use BETWEEN 'start_date' AND 'end_date' or explicit comparisons.
        - Handle NULL values with COALESCE (e.g., COALESCE(p.purchase_price, 0)).
        - Use appropriate JOINs (INNER JOIN for required matches, LEFT JOIN for optional data).
        - For aggregations, ensure all non-aggregated columns in SELECT are in GROUP BY.
        - Alias all computed columns clearly (e.g., SUM(id.quantity) AS total_sold).
        - For total revenue on a specific date:
          SELECT SUM(total) AS total_revenue
          FROM invoices
          WHERE order_date = '{specific_date}';
        - For total cost on a specific date:
          SELECT COALESCE(SUM(id.quantity * p.purchase_price), 0) AS total_cost
          FROM invoice_details id
          JOIN invoices i ON id.invoice_id = i.invoice_id
          JOIN products p ON id.product_id = p.product_id
          WHERE i.order_date = '{specific_date}';
        - For profit on a specific date:
          SELECT SUM(i.total) - COALESCE(SUM(id.quantity * p.purchase_price), 0) AS profit
          FROM invoices i
          LEFT JOIN invoice_details id ON i.invoice_id = id.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE i.order_date = '{specific_date}';
        - Example: For the question "what is the total profit on May 3, 2025?", generate:
          SELECT SUM(i.total) - COALESCE(SUM(id.quantity * p.purchase_price), 0) AS profit
          FROM invoices i
          LEFT JOIN invoice_details id ON i.invoice_id = id.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE i.order_date = '2025-05-03';
        - For combined financial metrics on a specific date:
          SELECT 
              SUM(i.total) AS total_revenue,
              COALESCE(SUM(id.quantity * p.purchase_price), 0) AS total_cost,
              SUM(i.total) - COALESCE(SUM(id.quantity * p.purchase_price), 0) AS profit
          FROM invoices i
          LEFT JOIN invoice_details id ON i.invoice_id = id.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE i.order_date = '{specific_date}';
        - For best-selling products:
          SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold, MAX(id.unit_price) AS max_price, SUM(id.total_price) AS total_revenue
          FROM invoice_details id
          INNER JOIN products p ON id.product_id = p.product_id
          INNER JOIN invoices i ON id.invoice_id = i.invoice_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN (SELECT MIN(CONCAT(order_date, ' ', order_time)) FROM invoices) AND '{current_sg_datetime}'
          GROUP BY p.product_id, p.product_name
          ORDER BY total_sold DESC, p.product_id ASC
          LIMIT 10;
        - For specific products (if provided), use WHERE p.product_name LIKE '%{product_name}%' or p.product_id = 'id'.
        - For time periods:
          - Today: WHERE i.order_date = '{current_sg_date}'
          - This week: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 7 DAY)
          - This month: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 1 MONTH)
          - This year: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 1 YEAR)
          - All time: WHERE CONCAT(i.order_date, ' ', i.order_time) >= (SELECT MIN(CONCAT(order_date, ' ', order_time)) FROM invoices)
        - For low stock:
          SELECT product_name, stock, reorder_level
          FROM products
          WHERE stock <= reorder_level;
        - Ensure calculations (e.g., SUM, AVG) are accurate, handling edge cases like division by zero.
        - Optimize with LIMIT for large datasets and use indexes where possible.
        - Return only the SQL query, no explanations, no markdown, no backticks.

        **User Question:** {question}
        """
        if product_name:
            template = template.format(product_name=product_name, current_sg_date=current_sg_date, current_sg_datetime=current_sg_datetime, specific_date=specific_date, schema=self.schema, chat_history=" ".join([msg.content for msg in chat_history[-10:]]), question=user_query)
        else:
            template = template.replace("%{product_name}%", "%")  # Remove product filter if not provided
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | self.llm | StrOutputParser()
        try:
            raw_response = chain.invoke({
                "question": user_query,
                "chat_history": " ".join([msg.content for msg in chat_history[-10:]]),
                "schema": self.schema,
                "current_sg_date": current_sg_date,
                "current_sg_datetime": current_sg_datetime,
                "specific_date": specific_date
            })
            sql_query_match = re.search(r'(?is)(SELECT.*?;)', raw_response)
            if sql_query_match:
                sql_query = sql_query_match.group(1).strip()
            else:
                raise ValueError("No SQL query found in the response")
            if not sql_query.endswith(";"):
                sql_query += ";"
            if sql_query.count("SELECT") > 3:
                raise ValueError("Query too complex: Too many subqueries")
            return sql_query, raw_response, specific_date
        except Exception as e:
            logging.error(f"SQL generation error: {str(e)}")
            raise ValueError(f"Failed to generate SQL query: {str(e)}")

    def validate_query(self, query):
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            raise ValueError("Query must start with SELECT")
        if "GROUP BY" in query_upper:
            select_part = query_upper.split("FROM")[0].replace("SELECT", "").strip()
            group_by_part = query_upper.split("GROUP BY")[1].split("ORDER BY")[0] if "ORDER BY" in query_upper else query_upper.split("GROUP BY")[1]
            select_columns = [col.strip().split(" AS ")[0].strip() for col in select_part.split(",")]
            group_by_columns = [col.strip() for col in group_by_part.split(",")]
            for col in select_columns:
                if not any(func in col for func in ["SUM(", "COUNT(", "AVG(", "MAX(", "MIN("]) and col not in group_by_columns:
                    raise ValueError(f"Column {col} in SELECT must be in GROUP BY or aggregated")
        table_alias_map = {}
        table_matches = re.findall(r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)?\b', query_upper, re.IGNORECASE)
        for table, alias in table_matches:
            if alias:
                table_alias_map[alias] = table
            else:
                table_alias_map[table] = table
        for alias, table in table_alias_map.items():
            if table not in [t.upper() for t in self.allowed_tables.keys()]:
                raise ValueError(f"Unauthorized table: {table}")
        select_part = query_upper.split("FROM")[0].replace("SELECT", "").strip()
        columns = [col.strip() for col in select_part.split(",")]
        for col in columns:
            if col.startswith("(") or " AS " in col or any(func in col for func in ["SUM(", "COUNT(", "ROUND(", "COALESCE("]):
                continue
            if "." in col:
                table_alias, col_name = col.split(".")
                if table_alias in table_alias_map:
                    table_name = table_alias_map[table_alias].lower()
                    if table_name in self.allowed_tables and col_name.upper() not in [c.upper() for c in self.allowed_tables[table_name]]:
                        raise ValueError(f"Unauthorized column: {col_name} in table {table_name}")
        if any(kw in query_upper for kw in ["DROP", "ALTER", "TRUNCATE", "INSERT", "UPDATE", "DELETE"]):
            raise ValueError("Query contains prohibited keywords")
        return True

    @retry(tries=3, delay=1, backoff=2)
    def execute_query(self, query):
        payload = {"action": "execute_query", "key": self.api_key, "query": quote(query)}
        try:
            response = requests.get(self.api_url, params=payload, timeout=30)
            status_code = response.status_code
            if status_code != 200:
                return None, f"API returned status {status_code}: {response.text}", status_code
            try:
                data = response.json()
                if data.get("status") == "success":
                    return data["data"], "Success", status_code
                return None, data.get("error", "Unknown error"), status_code
            except json.JSONDecodeError:
                return None, "Invalid JSON response", status_code
        except requests.exceptions.RequestException as e:
            return None, f"Request failed: {str(e)}", 500

    def generate_response(self, user_query, data, chat_history):
        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - If empty results, suggest: "No data found. This may be due to missing records or an invalid time frame. Try a different question."
        - Highlight key insights with **bold**.
        - Use - for lists, ₱ for currency, % for percentages.
        - Format numbers: currency as ₱X,XXX.XX, percentages as XX.XX%.
        - Parse JSON fields into readable format.
        - Ensure calculations match the data exactly (e.g., revenue, profit).
        - Keep concise (<250 words).
        - Suggest follow-up: "Would you like more details or to explore another aspect?"
        """
        chain = (
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | ChatPromptTemplate.from_template(response_template)
            | self.llm
            | StrOutputParser()
        )
        try:
            response = chain.invoke({
                "question": user_query,
                "response": json.dumps(data, indent=2),
                "chat_history": " ".join([msg.content for msg in chat_history[-10:]])
            })
            return response
        except Exception as e:
            logging.error(f"Response generation error: {str(e)}")
            return f"Error generating response: {str(e)}. Please try again."

# Handle user query with enhanced error handling and data presentation
def handle_query(query: str, agent: AISQLAgent):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            singapore_tz = pytz.timezone('Asia/Singapore')
            now_sg = datetime.datetime.now(singapore_tz)
            current_sg_date = now_sg.strftime('%Y-%m-%d')
            current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

            product_name = None
            if "product" in query.lower():
                words = query.split()
                for i, word in enumerate(words):
                    if word.lower() == "product" and i + 1 < len(words):
                        product_name = words[i + 1]
                        break

            sql_query, raw_response, specific_date = agent.generate_sql_query(query, st.session_state.chat_history, current_sg_date, current_sg_datetime, product_name)
            agent.validate_query(sql_query)

            data, api_response, status_code = agent.execute_query(sql_query)
            debug_info = {
                "raw_response": raw_response,
                "cleaned_query": sql_query,
                "api_response": api_response,
                "status_code": status_code,
                "api_data": json.dumps(data, indent=2) if data else "No data"
            }

            if data is None:
                raise ValueError(f"API error: {api_response} (Status: {status_code})")

            natural_response = agent.generate_response(query, data, st.session_state.chat_history)

            if st.session_state.debug_mode:
                with st.expander("Debug Info", expanded=False):
                    st.markdown("### Debug Info")
                    st.write(f"**Raw Response**: {debug_info['raw_response']}")
                    st.write(f"**Cleaned Query**: ```sql\n{debug_info['cleaned_query']}\n```")
                    st.write(f"**API Response**: {debug_info['api_response']}")
                    st.write(f"**API Status Code**: {debug_info['status_code']}")
                    st.write(f"**API Data**: ```json\n{debug_info['api_data']}\n```")

            if data and isinstance(data, list) and len(data) >= 1:
                df = pd.DataFrame(data)
                query_lower = query.lower()

                if "total revenue" in query_lower and "profit" in query_lower:
                    if 'total_revenue' in df.columns and 'profit' in df.columns:
                        total_revenue = float(df['total_revenue'].iloc[0])
                        profit = float(df['profit'].iloc[0])
                        readable_date = datetime.datetime.strptime(specific_date, '%Y-%m-%d').strftime('%B %d, %Y')
                        natural_response = f"For {readable_date}, the total revenue was **₱{total_revenue:,.2f}** and the profit was **₱{profit:,.2f}**. Would you like a detailed breakdown?"
                        st.markdown("### Financial Summary")
                        st.write(f"**Total Revenue**: ₱{total_revenue:,.2f}")
                        st.write(f"**Profit**: ₱{profit:,.2f}")
                        st.download_button("Download Financial Data", df.to_csv(index=False), "financial_data.csv")
                elif "total revenue" in query_lower:
                    if 'total_revenue' in df.columns:
                        total_revenue = float(df['total_revenue'].iloc[0])
                        readable_date = datetime.datetime.strptime(specific_date, '%Y-%m-%d').strftime('%B %d, %Y')
                        natural_response = f"The total revenue on {readable_date} was **₱{total_revenue:,.2f}**. Would you like to see a breakdown by product?"
                        st.markdown("### Total Revenue")
                        st.write(f"**₱{total_revenue:,.2f}**")
                        st.download_button("Download Revenue Data", df.to_csv(index=False), "revenue.csv")
                elif "profit" in query_lower:
                    if 'profit' in df.columns:
                        profit = float(df['profit'].iloc[0])
                        readable_date = datetime.datetime.strptime(specific_date, '%Y-%m-%d').strftime('%B %d, %Y')
                        natural_response = f"The profit on {readable_date} was **₱{profit:,.2f}**. Would you like more details or to explore another aspect?"
                        st.markdown("### Profit")
                        st.write(f"**₱{profit:,.2f}**")
                        st.download_button("Download Profit Data", df.to_csv(index=False), "profit.csv")
                else:
                    for col in df.columns:
                        if df[col].dtype in ['int64', 'float64']:
                            df[col] = df[col].apply(lambda x: f"₱{x:,.2f}" if 'price' in col.lower() or 'total' in col.lower() or 'revenue' in col.lower() else x)
                        elif "date" in col.lower():
                            df[col] = pd.to_datetime(df[col], errors='coerce')
                    if len(df) > 100:
                        st.write("Showing first 10 rows. Download the full data below.")
                        st.dataframe(df.head(10), use_container_width=True)
                        st.download_button("Download Full Data", df.to_csv(index=False), "full_data.csv")
                    else:
                        st.dataframe(df, use_container_width=True)
            else:
                st.warning("No data returned from the query.")
                natural_response = "No data found. This may be due to missing records or an invalid time frame. Try a different question."
        except ValueError as ve:
            natural_response = f"Query error: {str(ve)}. Please try rephrasing your question."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                with st.expander("Debug Info", expanded=False):
                    st.markdown("### Debug Info")
                    st.write(f"**Raw Response**: {raw_response if 'raw_response' in locals() else 'N/A'}")
                    st.write(f"**Cleaned Query**: ```sql\n{sql_query if 'sql_query' in locals() else 'N/A'}\n```")
                    st.write(f"**API Response**: {str(ve)}")
                    st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
                    st.write(f"**API Data**: {json.dumps(data, indent=2) if 'data' in locals() else 'No data'}")
        except requests.exceptions.RequestException as re:
            natural_response = f"API error: {str(re)}. Please check your connection or try again later."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                with st.expander("Debug Info", expanded=False):
                    st.markdown("### Debug Info")
                    st.write(f"**Raw Response**: {raw_response if 'raw_response' in locals() else 'N/A'}")
                    st.write(f"**Cleaned Query**: ```sql\n{sql_query if 'sql_query' in locals() else 'N/A'}\n```")
                    st.write(f"**API Response**: {str(re)}")
                    st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
                    st.write(f"**API Data**: {json.dumps(data, indent=2) if 'data' in locals() else 'No data'}")
        except Exception as e:
            natural_response = f"An unexpected error occurred: {str(e)}. Please contact support."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                with st.expander("Debug Info", expanded=False):
                    st.markdown("### Debug Info")
                    st.write(f"**Raw Response**: {raw_response if 'raw_response' in locals() else 'N/A'}")
                    st.write(f"**Cleaned Query**: ```sql\n{sql_query if 'sql_query' in locals() else 'N/A'}\n```")
                    st.write(f"**API Response**: {str(e)}")
                    st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
                    st.write(f"**API Data**: {json.dumps(data, indent=2) if 'data' in locals() else 'No data'}")
        st.session_state.chat_history.append(AIMessage(content=natural_response))
        with st.chat_message("AI", avatar="dist/img/ai.png"):
            st.markdown(natural_response)

# Initialize session state
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I'm AcaSquad AI. Ask me anything about your SCC School Store.")
    ]
if "debug_mode" not in st.session_state:
    st.session_state.debug_mode = st.secrets.get("DEBUG_MODE", "true").lower() == "true"
if "debug_sql" not in st.session_state:
    st.session_state.debug_sql = st.secrets.get("DEBUG_SQL", "true").lower() == "true"
if "debug_api" not in st.session_state:
    st.session_state.debug_api = st.secrets.get("DEBUG_API", "true").lower() == "true"

# Authentication function
def authenticate(email, password):
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
            st.error(f"Login failed: {data.get('error', 'Invalid credentials')}")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
    return False

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
        AIMessage(content="Hello! I'm AcaSquad AI. Ask me anything about your SCC School Store.")
    ]
    st.success("Chat history cleared. Starting a new conversation!")

# Main application
def main():
    schema = """
    Database Schema:
    - invoices: invoice_id (PK, int), employee_id (FK to employees, int), order_date (date), order_time (time), subtotal (decimal), discount (decimal), total (decimal), paid (decimal), due (decimal), payment_type (varchar, Cash/Card/Check), created_at (datetime), updated_at (datetime)
    - invoice_details: detail_id (PK, int), invoice_id (FK to invoices, int), product_id (FK to products, int), quantity (int), unit_price (decimal), total_price (decimal), created_at (datetime), updated_at (datetime)
    - products: product_id (PK, int), barcode (varchar), product_name (varchar), category_id (FK to categories, int), description (text), stock (int), reorder_level (int), purchase_price (decimal), sale_price (decimal), image (varchar), created_at (datetime), updated_at (datetime)
    - categories: category_id (PK, int), category_name (varchar), created_at (datetime), updated_at (datetime)
    - employees: employee_id (PK, int), first_name (varchar), last_name (varchar), email (varchar), password_hash (varchar), role (varchar, Owner/Admin/Cashier), created_at (datetime), updated_at (datetime)
    - void_logs: void_id (PK, int), invoice_id (FK to invoices, int), void_type (varchar), details (json), status (varchar), created_at (datetime), updated_at (datetime)
    - inventory_logs: log_id (PK, int), product_id (FK to products, int), adjustment_type (varchar), quantity (int), created_at (datetime), updated_at (datetime)
    - user_logins: log_id (PK, int), employee_id (FK to employees, int), login_time (datetime), logout_time (datetime), created_at (datetime), updated_at (datetime)
    - discount_logs: discount_id (PK, int), invoice_id (FK to invoices, int), discount_amount (decimal), created_at (datetime), updated_at (datetime)
    - admin_logs: adminlogs_id (PK, int), admin_id (FK to employees, int), action_type (varchar), details (json), approved_by_owner (int), created_at (datetime), updated_at (datetime)
    - sync_log: log_id (PK, int), table_name (varchar), record_id (int), action (varchar), timestamp (datetime), synced (tinyint)
    """
    allowed_tables = {
        "invoices": ["invoice_id", "employee_id", "order_date", "order_time", "subtotal", "discount", "total", "paid", "due", "payment_type", "created_at", "updated_at"],
        "invoice_details": ["detail_id", "invoice_id", "product_id", "quantity", "unit_price", "total_price", "created_at", "updated_at"],
        "products": ["product_id", "barcode", "product_name", "category_id", "description", "stock", "reorder_level", "purchase_price", "sale_price", "image", "created_at", "updated_at"],
        "categories": ["category_id", "category_name", "created_at", "updated_at"],
        "employees": ["employee_id", "first_name", "last_name", "email", "password_hash", "role", "created_at", "updated_at"],
        "void_logs": ["void_id", "invoice_id", "void_type", "details", "status", "created_at", "updated_at"],
        "inventory_logs": ["log_id", "product_id", "adjustment_type", "quantity", "created_at", "updated_at"],
        "user_logins": ["log_id", "employee_id", "login_time", "logout_time", "created_at", "updated_at"],
        "discount_logs": ["discount_id", "invoice_id", "discount_amount", "created_at", "updated_at"],
        "admin_logs": ["adminlogs_id", "admin_id", "action_type", "details", "approved_by_owner", "created_at", "updated_at"],
        "sync_log": ["log_id", "table_name", "record_id", "action", "timestamp", "synced"]
    }
    agent = AISQLAgent(
        api_url=st.secrets["API_URL"],
        api_key=st.secrets["API_KEY"],
        groq_api_key=st.secrets["GROQ_API_KEY"],
        schema=schema,
        allowed_tables=allowed_tables
    )

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
                st.markdown(f"Logged in as **{st.session_state.user['first_name']} {st.session_state.user['last_name']}** ({st.session_state.user['role']})")
                st.checkbox("Debug Mode", key="debug_mode", value=st.session_state.debug_mode)
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
                        "What is the daily sales trend for this month?",
                        "What is the revenue trend compared to last month?",
                        "What are the top 5 products by revenue this week?",
                        "What is the average transaction value this month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"sales_{uuid.uuid4()}"):
                            handle_query(q, agent)
                with st.expander("📦 Inventory Management"):
                    queries = [
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?",
                        "What are the most recent inventory adjustments?",
                        "Which products are out of stock?",
                        "What is the total stock value based on purchase price?",
                        "Which products have the highest stock levels?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"inv_{uuid.uuid4()}"):
                            handle_query(q, agent)
                with st.expander("👥 Employee Performance"):
                    queries = [
                        "Who is currently logged in?",
                        "What are the total sales by each employee this week?",
                        "Who has the highest number of transactions today?",
                        "Which employee has the highest sales this month?",
                        "What are the login times for employees today?",
                        "Who processed the most invoices this week?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"emp_{uuid.uuid4()}"):
                            handle_query(q, agent)
                with st.expander("💰 Financial Insights"):
                    queries = [
                        "What are the admin overview metrics for this month?",
                        "What is the total amount due from unpaid invoices?",
                        "What is the total discount given this month?",
                        "What is the profit margin for SCC SHIRT this year?",
                        "What is the highest revenue day this month?",
                        "What is the total profit for this month?",
                        "What is the breakdown of payment types this month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"fin_{uuid.uuid4()}"):
                            handle_query(q, agent)
            display_chat_history()
            user_query = st.chat_input("Ask about sales, inventory, employees, or financials...")
            if user_query:
                handle_query(user_query, agent)
        else:
            st.error("Access restricted. Please contact an Admin.")
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
header {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)