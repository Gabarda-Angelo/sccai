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

    def generate_sql_query(self, user_query, chat_history, current_sg_date, current_sg_datetime):
        template = """
        You are an AI SQL Agent for the SCC School Store Database, generating precise SQL queries for MariaDB 10.6.21.

        **Database Schema:**
        {schema}

        **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
        **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

        **Conversation History:** {chat_history}

        **Instructions:**
        - Generate SQL queries valid for MariaDB 10.6.21, optimized for performance.
        - Use 'today' as '{current_sg_date}' for daily queries.
        - For date ranges, use BETWEEN 'start_date' AND 'end_date' or explicit comparisons.
        - Handle NULL values with COALESCE (e.g., COALESCE(p.purchase_price, 0)).
        - Use appropriate JOINs (INNER JOIN for required matches, LEFT JOIN for optional data).
        - For aggregations, use SUM, COUNT, AVG, ROUND as needed.
        - Alias all computed columns clearly (e.g., SUM(id.quantity) AS total_sold).
        - For best-selling products:
          SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold, MAX(id.unit_price) AS max_price, SUM(id.total_price) AS total_revenue
          FROM invoice_details id
          INNER JOIN products p ON id.product_id = p.product_id
          INNER JOIN invoices i ON id.invoice_id = i.invoice_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN (SELECT MIN(CONCAT(order_date, ' ', order_time)) FROM invoices) AND '{current_sg_datetime}'
          GROUP BY p.product_id, p.product_name
          ORDER BY total_sold DESC, p.product_id ASC
          LIMIT 10;
        - For profit calculations:
          SELECT ROUND(SUM(i.total) - COALESCE(SUM(id.quantity * p.purchase_price), 0), 2) AS profit
          FROM invoices i
          LEFT JOIN invoice_details id ON id.invoice_id = i.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date';
        - For profit margin:
          SELECT ROUND(
            CASE WHEN SUM(i.total) > 0
                 THEN ((SUM(i.total) - COALESCE(SUM(id.quantity * p.purchase_price), 0)) / SUM(i.total) * 100)
                 ELSE 0
            END, 2) AS profit_margin
          FROM invoices i
          LEFT JOIN invoice_details id ON id.invoice_id = i.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date';
        - For specific products, use WHERE p.product_name LIKE '%name%' or p.product_id = id.
        - For time periods:
          - Today: WHERE i.order_date = '{current_sg_date}'
          - This week: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 7 DAY)
          - This month: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 1 MONTH)
          - This year: WHERE i.order_date >= DATE_SUB('{current_sg_date}', INTERVAL 1 YEAR)
          - All time: WHERE CONCAT(i.order_date, ' ', i.order_time) >= (SELECT MIN(CONCAT(order_date, ' ', order_time)) FROM invoices)
        - For low stock: SELECT product_name, stock FROM products WHERE stock <= reorder_level
        - For employee performance:
          SELECT e.first_name, e.last_name, COUNT(i.invoice_id) AS transactions, SUM(i.total) AS total_sales
          FROM invoices i
          INNER JOIN employees e ON i.employee_id = e.employee_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date'
          GROUP BY e.employee_id
          ORDER BY total_sales DESC
        - Handle void_logs by adjusting quantities where status = 'voided_before_payment'.
        - Ensure queries are secure, avoiding SQL injection risks.
        - Return only the SQL query, no explanations or additional text.

        **User Question:** {question}
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | self.llm | StrOutputParser()
        try:
            raw_query = chain.invoke({
                "question": user_query,
                "chat_history": " ".join([msg.content for msg in chat_history[-5:]]),
                "schema": self.schema,
                "current_sg_date": current_sg_date,
                "current_sg_datetime": current_sg_datetime
            })
        except Exception as e:
            raise ValueError(f"Failed to generate SQL query: {str(e)}")
        
        sql_query = raw_query.strip()
        if not sql_query:
            raise ValueError("No valid SQL query extracted")
        if not sql_query.endswith(";"):
            sql_query += ";"
        return sql_query, raw_query

    def validate_query(self, query):
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            raise ValueError("Query must start with SELECT")
        for table in self.allowed_tables.keys():
            if table.upper() in query_upper:
                select_part = query_upper.split("FROM")[0].replace("SELECT", "").strip()
                columns = [col.strip() for col in select_part.split(",")]
                for col in columns:
                    if "." in col:
                        table_name, col_name = col.split(".")
                        if table_name.upper() not in [t.upper() for t in self.allowed_tables.keys()]:
                            raise ValueError(f"Unauthorized table: {table_name}")
                        if col_name.upper() not in [c.upper() for c in self.allowed_tables[table_name.lower()]]:
                            raise ValueError(f"Unauthorized column: {col_name} in table {table_name}")
        return True

    @retry(tries=3, delay=1, backoff=2)
    def execute_query(self, query):
        payload = {"action": "execute_query", "key": self.api_key, "query": quote(query)}
        try:
            response = requests.get(self.api_url, params=payload, timeout=15)
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
        - Format numbers: currency as ₱X,XXX.XX, percentages as XX.X%.
        - Parse JSON fields into readable format.
        - Keep concise (<200 words).
        - Suggest follow-up: "Would you like more details or to explore another aspect?"
        """
        chain = (
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | ChatPromptTemplate.from_template(response_template)
            | self.llm
            | StrOutputParser()
        )
        return chain.invoke({
            "question": user_query,
            "response": json.dumps(data, indent=2),
            "chat_history": " ".join([msg.content for msg in chat_history[-5:]])
        })

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

# Adjust quantities based on void_logs
def adjust_quantities_with_voids(df, agent):
    void_data, _, _ = agent.execute_query("""
        SELECT JSON_EXTRACT(details, '$.item[*].product_id') AS product_ids,
               JSON_EXTRACT(details, '$.item[*].original_qty') AS original_qty,
               JSON_EXTRACT(details, '$.item[*].new_qty') AS new_qty
        FROM void_logs
        WHERE status = 'voided_before_payment';
    """)
    if void_data and 'Product ID' in df.columns:
        for void in void_data:
            product_ids = json.loads(void['product_ids']) if void['product_ids'] else []
            original_qty = json.loads(void['original_qty']) if void['original_qty'] else []
            new_qty = json.loads(void['new_qty']) if void['new_qty'] else []
            for pid, oq, nq in zip(product_ids, original_qty, new_qty):
                if pid in df['Product ID'].values:
                    adjustment = oq - nq
                    df.loc[df['Product ID'] == pid, 'QTY'] -= adjustment
    return df

# Determine chart type based on query and data
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2 or len(df) < 1:
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
        if unique_categories <= 6 and "percentage" in query_lower:
            return "pie", (categorical_columns[0], numerical_columns[0])
        else:
            return "bar", (categorical_columns[0], numerical_columns[0])
    return None, None

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

            # Generate and validate SQL query
            sql_query, raw_query = agent.generate_sql_query(query, st.session_state.chat_history, current_sg_date, current_sg_datetime)
            agent.validate_query(sql_query)

            # Execute query
            data, api_response, status_code = agent.execute_query(sql_query)
            debug_info = {
                "raw_query": raw_query,
                "cleaned_query": sql_query,
                "api_response": api_response,
                "status_code": status_code
            }

            if data is None:
                raise ValueError(f"API error: {api_response} (Status: {status_code})")

            # Generate natural language response
            natural_response = agent.generate_response(query, data, st.session_state.chat_history)

            # Display debug info if enabled
            if st.session_state.debug_mode:
                st.markdown("### Debug Info")
                st.write(f"**Raw Query**: {debug_info['raw_query']}")
                st.write(f"**Cleaned Query**: {debug_info['cleaned_query']}")
                st.write(f"**API Response**: {debug_info['api_response']}")
                st.write(f"**API Status Code**: {debug_info['status_code']}")

            # Process and display data
            if data and isinstance(data, list) and len(data) >= 1:
                df = pd.DataFrame(data)
                query_lower = query.lower()

                # Handle admin overview metrics
                if query_lower.startswith("what are the admin overview metrics"):
                    if all(col in df.columns for col in ['total_invoices', 'avg_sales_value', 'total_revenue', 'base_cost', 'profit', 'profit_margin', 'low_stock_count', 'top_product']):
                        for col in ['avg_sales_value', 'total_revenue', 'base_cost', 'profit']:
                            df[col] = df[col].apply(lambda x: f"₱{x:,.2f}")
                        df['profit_margin'] = df['profit_margin'].apply(lambda x: f"{x:.1f}%")
                        df.rename(columns={
                            'total_invoices': 'Total Invoices',
                            'avg_sales_value': 'Average Sales Value',
                            'total_revenue': 'Total Revenue',
                            'base_cost': 'Base Cost',
                            'profit': 'Profit',
                            'profit_margin': 'Profit Margin',
                            'low_stock_count': 'Low Stock Products',
                            'top_product': 'Top-Selling Product'
                        }, inplace=True)
                        st.markdown("### Admin Overview")
                        cols = st.columns(4)
                        for i, col in enumerate(['Average Sales Value', 'Total Invoices', 'Total Revenue', 'Top-Selling Product']):
                            with cols[i]:
                                st.markdown(f"**{col}**")
                                st.markdown(df[col].iloc[0])
                        cols = st.columns(4)
                        for i, col in enumerate(['Base Cost', 'Profit', 'Profit Margin', 'Low Stock Products']):
                            with cols[i]:
                                st.markdown(f"**{col}**")
                                value = df[col].iloc[0]
                                if col == 'Low Stock Products':
                                    value = f"{value} item(s)"
                                st.markdown(value)
                        st.download_button("Download Admin Overview Data", df.to_csv(index=False), "admin_overview.csv")
                    else:
                        st.warning("Required columns missing in admin overview data.")

                # Handle financial metrics
                elif any(keyword in query_lower for keyword in ["total revenue", "total profit", "base cost", "profit margin", "total invoices"]):
                    if all(col in df.columns for col in ['total_revenue', 'base_cost', 'profit', 'profit_margin']):
                        for col in ['total_revenue', 'base_cost', 'profit']:
                            df[col] = df[col].apply(lambda x: f"₱{x:,.2f}")
                        df['profit_margin'] = df['profit_margin'].apply(lambda x: f"{x:.1f}%")
                        if "total revenue" in query_lower:
                            st.markdown("### Total Revenue")
                            st.markdown(f"**Total Revenue**: {df['total_revenue'].iloc[0]}")
                            st.download_button("Download Total Revenue Data", df[['total_revenue']].to_csv(index=False), "total_revenue.csv")
                        elif "total profit" in query_lower:
                            st.markdown("### Total Profit")
                            st.markdown(f"**Total Profit**: {df['profit'].iloc[0]}")
                            st.download_button("Download Total Profit Data", df[['profit']].to_csv(index=False), "total_profit.csv")
                        elif "base cost" in query_lower:
                            st.markdown("### Base Cost")
                            st.markdown(f"**Base Cost**: {df['base_cost'].iloc[0]}")
                            st.download_button("Download Base Cost Data", df[['base_cost']].to_csv(index=False), "base_cost.csv")
                        elif "profit margin" in query_lower:
                            st.markdown("### Profit Margin")
                            st.markdown(f"**Profit Margin**: {df['profit_margin'].iloc[0]}")
                            st.download_button("Download Profit Margin Data", df[['profit_margin']].to_csv(index=False), "profit_margin.csv")
                        elif "total invoices" in query_lower:
                            st.markdown("### Total Invoices")
                            st.markdown(f"**Total Invoices**: {df['total_invoices'].iloc[0]}")
                            st.download_button("Download Total Invoices Data", df[['total_invoices']].to_csv(index=False), "total_invoices.csv")
                    else:
                        st.warning("Required financial data not found in the response.")

                # Handle product-related queries
                else:
                    if all(col in df.columns for col in ['product_id', 'product_name', 'total_sold', 'max_price']):
                        df.rename(columns={
                            'product_id': 'Product ID',
                            'product_name': 'Product Name',
                            'total_sold': 'QTY',
                            'max_price': 'Rate'
                        }, inplace=True)
                        if 'total_revenue' in df.columns:
                            df['Total'] = df['total_revenue'].apply(lambda x: f"₱{x:,.2f}")
                            df.drop(columns=['total_revenue'], inplace=True)
                        df = df[['Product ID', 'Product Name', 'QTY', 'Rate', 'Total']].dropna(subset=['Product ID', 'Product Name', 'QTY', 'Rate'])
                        df = adjust_quantities_with_voids(df, agent)
                        for col in df.columns:
                            if "date" in col.lower():
                                df[col] = pd.to_datetime(df[col], errors='coerce')
                            if col == 'Rate':
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
                                plt.savefig('chart.png')
                                st.pyplot(fig)
                                st.download_button("Download Chart Data", df.to_csv(index=False), "chart_data.csv")
                        if len(df) > 100:
                            st.write("Showing first 10 rows. Download the full data below.")
                            st.table(df.head(10))
                            st.download_button("Download Full Data", df.to_csv(index=False), "full_data.csv")
                        else:
                            st.table(df)
                    else:
                        if len(df) > 100:
                            st.write("Showing first 10 rows. Download the full data below.")
                            st.table(df.head(10))
                            st.download_button("Download Full Data", df.to_csv(index=False), "full_data.csv")
                        else:
                            st.table(df)
            else:
                st.warning("No data returned from the query.")
                natural_response = "No data found. This may be due to missing records or an invalid time frame. Try a different question."
        except ValueError as ve:
            natural_response = f"Query generation error: {str(ve)}. Please try rephrasing your question."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                st.markdown("### Debug Info")
                st.write(f"**Raw Query**: {raw_query if 'raw_query' in locals() else 'N/A'}")
                st.write(f"**Cleaned Query**: {sql_query if 'sql_query' in locals() else 'N/A'}")
                st.write(f"**API Response**: {str(ve)}")
                st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
        except requests.exceptions.RequestException as re:
            natural_response = f"API error: {str(re)}. Please check your connection or try again later."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                st.markdown("### Debug Info")
                st.write(f"**Raw Query**: {raw_query if 'raw_query' in locals() else 'N/A'}")
                st.write(f"**Cleaned Query**: {sql_query if 'sql_query' in locals() else 'N/A'}")
                st.write(f"**API Response**: {str(re)}")
                st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
        except Exception as e:
            natural_response = f"An unexpected error occurred: {str(e)}. Please contact support."
            logging.error(natural_response)
            if st.session_state.debug_mode:
                st.markdown("### Debug Info")
                st.write(f"**Raw Query**: {raw_query if 'raw_query' in locals() else 'N/A'}")
                st.write(f"**Cleaned Query**: {sql_query if 'sql_query' in locals() else 'N/A'}")
                st.write(f"**API Response**: {str(e)}")
                st.write(f"**API Status Code**: {status_code if 'status_code' in locals() else 'N/A'}")
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
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash/Card/Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, email, password_hash, role (Owner/Admin/Cashier), created_at, updated_at
    - void_logs: void_id (PK), invoice_id (FK to invoices), void_type, details (JSON), status, created_at, updated_at
    - inventory_logs: log_id (PK), product_id (FK to products), adjustment_type, quantity, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, created_at, updated_at
    - discount_logs: discount_id (PK), invoice_id (FK to invoices), discount_amount, created_at, updated_at
    - admin_logs: adminlogs_id (PK), admin_id (FK to employees), action_type, details (JSON), approved_by_owner, created_at, updated_at
    - sync_log: log_id (PK), table_name, record_id, action, timestamp, synced
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
                st.markdown(f"Logged in as {st.session_state.user['first_name']} {st.session_state.user['last_name']} ({st.session_state.user['role']})")
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
                        "What is the revenue trend compared to last month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q, agent)
                with st.expander("📦 Inventory Management"):
                    queries = [
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?",
                        "What are the most recent inventory adjustments?",
                        "Which products are out of stock?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"inv_{q}"):
                            handle_query(q, agent)
                with st.expander("👥 Employee Performance"):
                    queries = [
                        "Who is currently logged in?",
                        "What are the total sales by each employee this week?",
                        "Who has the highest number of transactions today?",
                        "Which employee has the highest sales this month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"emp_{q}"):
                            handle_query(q, agent)
                with st.expander("💰 Financial Insights"):
                    queries = [
                        "What are the admin overview metrics for this month?",
                        "What is the total amount due from unpaid invoices?",
                        "What is the total discount given this month?",
                        "What is the profit margin for SCC SHIRT this year?",
                        "What is the highest revenue day this month?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"fin_{q}"):
                            handle_query(q, agent)
            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query, agent)
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