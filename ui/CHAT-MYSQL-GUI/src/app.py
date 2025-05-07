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
import base64

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
        - For datetime filtering, use CONCAT(i.order_date, ' ', i.order_time) for invoices.
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
        - For low stock: 
          SELECT product_name, stock, reorder_level 
          FROM products 
          WHERE stock <= reorder_level;
        - For employee performance:
          SELECT e.employee_id, e.first_name, e.last_name, COUNT(i.invoice_id) AS transactions, ROUND(SUM(i.total), 2) AS total_sales
          FROM invoices i
          INNER JOIN employees e ON i.employee_id = e.employee_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date'
          GROUP BY e.employee_id, e.first_name, e.last_name
          ORDER BY total_sales DESC;
        - For employee details:
          SELECT employee_id, first_name, last_name, email, role
          FROM employees
          WHERE role IN ('Owner', 'Admin', 'Cashier');
        - For invoice details:
          SELECT i.invoice_id, i.order_date, i.order_time, e.first_name, e.last_name, p.product_name, id.quantity, id.unit_price, id.total_price
          FROM invoices i
          INNER JOIN employees e ON i.employee_id = e.employee_id
          INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id
          INNER JOIN products p ON id.product_id = p.product_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date';
        - For void adjustments:
          SELECT JSON_EXTRACT(details, '$.item[*].product_id') AS product_ids,
                 JSON_EXTRACT(details, '$.item[*].original_qty') AS original_qty,
                 JSON_EXTRACT(details, '$.item[*].new_qty') AS new_qty
          FROM void_logs
          WHERE status = 'voided_before_payment';
        - For discounts:
          SELECT i.invoice_id, i.order_date, i.order_time, dl.discount_amount
          FROM invoices i
          INNER JOIN discount_logs dl ON i.invoice_id = dl.invoice_id
          WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN 'start_date' AND 'end_date';
        - For admin logs:
          SELECT al.adminlogs_id, al.action_type, JSON_EXTRACT(al.details, '$.item[*]') AS items, al.approved_by_owner
          FROM admin_logs al
          WHERE al.created_at BETWEEN 'start_date' AND 'end_date';
        - Ensure queries are secure, avoiding SQL injection risks.
        - Optimize for performance with indexes and limiting rows where appropriate.
        - Return only the SQL query, no explanations, no markdown, no backticks.

        **User Question:** {question}
        """
        prompt = ChatPromptTemplate.from_template(template)
        chain = prompt | self.llm | StrOutputParser()
        try:
            raw_response = chain.invoke({
                "question": user_query,
                "chat_history": " ".join([msg.content for msg in chat_history[-10:]]),  # Extended history
                "schema": self.schema,
                "current_sg_date": current_sg_date,
                "current_sg_datetime": current_sg_datetime
            })
            # Extract the raw SQL query
            sql_query_match = re.search(r'(?is)(SELECT.*?;)', raw_response)
            if sql_query_match:
                sql_query = sql_query_match.group(1).strip()
            else:
                raise ValueError("No SQL query found in the response")
            if not sql_query.endswith(";"):
                sql_query += ";"
            # Check query complexity
            if sql_query.count("SELECT") > 3:
                raise ValueError("Query too complex: Too many subqueries")
            return sql_query, raw_response
        except Exception as e:
            logging.error(f"SQL generation error: {str(e)}")
            raise ValueError(f"Failed to generate SQL query: {str(e)}")

    def validate_query(self, query):
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            raise ValueError("Query must start with SELECT")
        # Extract table names
        table_names = re.findall(r'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+[a-zA-Z_][a-zA-Z0-9_]*)?', query_upper)
        for table in table_names:
            if table not in [t.upper() for t in self.allowed_tables.keys()]:
                raise ValueError(f"Unauthorized table: {table}")
        # Validate columns
        select_part = query_upper.split("FROM")[0].replace("SELECT", "").strip()
        columns = [col.strip() for col in select_part.split(",")]
        for col in columns:
            if "." in col:
                table_alias, col_name = col.split(".")
                table_match = re.search(rf'(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+{table_alias}\b', query_upper)
                if table_match:
                    table_name = table_match.group(1).lower()
                    if table_name in self.allowed_tables and col_name.upper() not in [c.upper() for c in self.allowed_tables[table_name]]:
                        raise ValueError(f"Unauthorized column: {col_name} in table {table_name}")
        # Check for dangerous keywords
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
                    df.loc[df['Product ID'] == pid, 'QTY'] = df.loc[df['Product ID'] == pid, 'QTY'] - adjustment
                    df.loc[df['Product ID'] == pid, 'QTY'] = df.loc[df['Product ID'] == pid, 'QTY'].clip(lower=0)
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
    elif numerical_columns and len(numerical_columns) >= 2:
        return "scatter", (numerical_columns[0], numerical_columns[1])
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
            sql_query, raw_response = agent.generate_sql_query(query, st.session_state.chat_history, current_sg_date, current_sg_datetime)
            agent.validate_query(sql_query)

            # Execute query
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

            # Generate natural language response
            natural_response = agent.generate_response(query, data, st.session_state.chat_history)

            # Display debug info if enabled
            if st.session_state.debug_mode:
                with st.expander("Debug Info", expanded=False):
                    st.markdown("### Debug Info")
                    st.write(f"**Raw Response**: {debug_info['raw_response']}")
                    st.write(f"**Cleaned Query**: ```sql\n{debug_info['cleaned_query']}\n```")
                    st.write(f"**API Response**: {debug_info['api_response']}")
                    st.write(f"**API Status Code**: {debug_info['status_code']}")
                    st.write(f"**API Data**: ```json\n{debug_info['api_data']}\n```")

            # Process and display data
            if data and isinstance(data, list) and len(data) >= 1:
                df = pd.DataFrame(data)
                query_lower = query.lower()

                # Handle employee details
                if "employee" in query_lower and "details" in query_lower:
                    if all(col in df.columns for col in ['employee_id', 'first_name', 'last_name', 'email', 'role']):
                        df.rename(columns={
                            'employee_id': 'Employee ID',
                            'first_name': 'First Name',
                            'last_name': 'Last Name',
                            'email': 'Email',
                            'role': 'Role'
                        }, inplace=True)
                        st.markdown("### Registered Employees")
                        if len(df) > 100:
                            st.write("Showing first 10 rows. Download the full data below.")
                            st.dataframe(df.head(10), use_container_width=True)
                            st.download_button("Download Employee Data", df.to_csv(index=False), "employees.csv")
                        else:
                            st.dataframe(df, use_container_width=True)
                    else:
                        st.warning("Required employee data not found in the response.")

                # Handle invoice details
                elif "invoice" in query_lower and "details" in query_lower:
                    if all(col in df.columns for col in ['invoice_id', 'order_date', 'order_time', 'first_name', 'last_name', 'product_name', 'quantity', 'unit_price', 'total_price']):
                        df['unit_price'] = pd.to_numeric(df['unit_price'], errors='coerce').fillna(0)
                        df['total_price'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
                        df.rename(columns={
                            'invoice_id': 'Invoice ID',
                            'order_date': 'Order Date',
                            'order_time': 'Order Time',
                            'first_name': 'Employee First Name',
                            'last_name': 'Employee Last Name',
                            'product_name': 'Product Name',
                            'quantity': 'Quantity',
                            'unit_price': 'Unit Price (₱)',
                            'total_price': 'Total Price (₱)'
                        }, inplace=True)
                        df['Unit Price (₱)'] = df['Unit Price (₱)'].apply(lambda x: f"₱{x:,.2f}")
                        df['Total Price (₱)'] = df['Total Price (₱)'].apply(lambda x: f"₱{x:,.2f}")
                        st.markdown("### Invoice Details")
                        if len(df) > 100:
                            st.write("Showing first 10 rows. Download the full data below.")
                            st.dataframe(df.head(10), use_container_width=True)
                            st.download_button("Download Invoice Data", df.to_csv(index=False), "invoices.csv")
                        else:
                            st.dataframe(df, use_container_width=True)
                    else:
                        st.warning("Required invoice data not found in the response.")

                # Handle product-related queries
                elif any(kw in query_lower for kw in ["product", "sales", "revenue", "stock"]):
                    if all(col in df.columns for col in ['product_id', 'product_name', 'total_sold', 'max_price']):
                        df.rename(columns={
                            'product_id': 'Product ID',
                            'product_name': 'Product Name',
                            'total_sold': 'QTY',
                            'max_price': 'Rate'
                        }, inplace=True)
                        if 'total_revenue' in df.columns:
                            df['total_revenue'] = pd.to_numeric(df['total_revenue'], errors='coerce').fillna(0)
                            df['Total'] = df['total_revenue'].apply(lambda x: f"₱{x:,.2f}")
                            df.drop(columns=['total_revenue'], inplace=True)
                        df = df[['Product ID', 'Product Name', 'QTY', 'Rate', 'Total']].dropna(subset=['Product ID', 'Product Name', 'QTY', 'Rate'])
                        df = adjust_quantities_with_voids(df, agent)
                        for col in df.columns:
                            if "date" in col.lower():
                                df[col] = pd.to_datetime(df[col], errors='coerce')
                            if col == 'Rate':
                                df['Rate'] = pd.to_numeric(df['Rate'], errors='coerce').fillna(0)
                                df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                        chart_type, columns = determine_chart_type(query, df)
                        if chart_type:
                            with st.spinner("Generating chart..."):
                                st.markdown(f"### {chart_type.capitalize()} Chart")
                                fig, ax = plt.subplots(figsize=(10, 6))
                                if chart_type == 'bar':
                                    df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax, color='#1f77b4')
                                    ax.set_title(f"{columns[1]} by {columns[0]}", fontsize=14)
                                    ax.set_xlabel(columns[0], fontsize=12)
                                    ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                                    plt.xticks(rotation=45, ha='right')
                                elif chart_type == 'line':
                                    df[columns[0]] = pd.to_datetime(df[columns[0]], errors='coerce')
                                    df = df.sort_values(columns[0])
                                    df.plot(kind='line', x=columns[0], y=columns[1], ax=ax, color='#ff7f0e')
                                    ax.set_title(f"{columns[1]} Over Time", fontsize=14)
                                    ax.set_xlabel("Date", fontsize=12)
                                    ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                                    plt.xticks(rotation=45)
                                elif chart_type == 'pie':
                                    ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%', colors=plt.cm.Paired.colors)
                                    ax.set_title(f"Distribution of {columns[1]}", fontsize=14)
                                elif chart_type == 'scatter':
                                    df.plot(kind='scatter', x=columns[0], y=columns[1], ax=ax, color='#2ca02c')
                                    ax.set_title(f"{columns[1]} vs {columns[0]}", fontsize=14)
                                    ax.set_xlabel(columns[0], fontsize=12)
                                    ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                                plt.tight_layout()
                                plt.savefig('chart.png', dpi=300, bbox_inches='tight')
                                st.pyplot(fig)
                                plt.close(fig)
                                st.download_button("Download Chart Data", df.to_csv(index=False), "chart_data.csv")
                        if len(df) > 100:
                            st.write("Showing first 10 rows. Download the full data below.")
                            st.dataframe(df.head(10), use_container_width=True)
                            st.download_button("Download Full Data", df.to_csv(index=False), "full_data.csv")
                        else:
                            st.dataframe(df, use_container_width=True)
                    else:
                        # Handle generic numerical data
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
                # Generate chart for generic data if applicable
                chart_type, columns = determine_chart_type(query, df)
                if chart_type:
                    with st.spinner("Generating chart..."):
                        st.markdown(f"### {chart_type.capitalize()} Chart")
                        fig, ax = plt.subplots(figsize=(10, 6))
                        if chart_type == 'bar':
                            df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax, color='#1f77b4')
                            ax.set_title(f"{columns[1]} by {columns[0]}", fontsize=14)
                            ax.set_xlabel(columns[0], fontsize=12)
                            ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                            plt.xticks(rotation=45, ha='right')
                        elif chart_type == 'line':
                            df[columns[0]] = pd.to_datetime(df[columns[0]], errors='coerce')
                            df = df.sort_values(columns[0])
                            df.plot(kind='line', x=columns[0], y=columns[1], ax=ax, color='#ff7f0e')
                            ax.set_title(f"{columns[1]} Over Time", fontsize=14)
                            ax.set_xlabel("Date", fontsize=12)
                            ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                            plt.xticks(rotation=45)
                        elif chart_type == 'pie':
                            ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%', colors=plt.cm.Paired.colors)
                            ax.set_title(f"Distribution of {columns[1]}", fontsize=14)
                        elif chart_type == 'scatter':
                            df.plot(kind='scatter', x=columns[0], y=columns[1], ax=ax, color='#2ca02c')
                            ax.set_title(f"{columns[1]} vs {columns[0]}", fontsize=14)
                            ax.set_xlabel(columns[0], fontsize=12)
                            ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'), fontsize=12)
                        plt.tight_layout()
                        plt.savefig('chart.png', dpi=300, bbox_inches='tight')
                        st.pyplot(fig)
                        plt.close(fig)
                        st.download_button("Download Chart Data", df.to_csv(index=False), "chart_data.csv")
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
                st.checkbox("Debug SQL Queries", key="debug_sql", value=st.session_state.debug_sql)
                st.checkbox("Debug API Responses", key="debug_api", value=st.session_state.debug_api)
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
                with st.expander("🔍 Admin Logs"):
                    queries = [
                        "What are the pending admin requests?",
                        "Which admin actions were approved this month?",
                        "What are the details of the latest admin logs?",
                        "Which products were updated by admins this week?"
                    ]
                    for q in queries:
                        if st.button(q, key=f"admin_{uuid.uuid4()}"):
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