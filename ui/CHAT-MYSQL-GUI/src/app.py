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
    st.session_state.debug_mode = True  # Enabled by default

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

# Adjust quantities based on void_logs
def adjust_quantities_with_voids(df):
    void_data, _, _ = fetch_data_from_api("execute_query", {
        "query": """
        SELECT JSON_EXTRACT(details, '$.item[*].product_id') AS product_ids,
               JSON_EXTRACT(details, '$.item[*].original_qty') AS original_qty,
               JSON_EXTRACT(details, '$.item[*].new_qty') AS new_qty
        FROM void_logs
        WHERE status = 'voided_before_payment'
        """
    })
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
        except Exception as e:
            natural_response = f"An error occurred: {str(e)}. Please try rephrasing your question."
            data = None
            debug_info = {"raw_query": "N/A", "cleaned_query": "N/A", "api_response": str(e), "status_code": "N/A"}
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            if query.lower().startswith("what are the admin overview metrics"):
                # Process Admin Overview metrics
                if all(col in df.columns for col in ['total_invoices', 'avg_sales_value', 'total_revenue', 'base_cost', 'low_stock_count', 'top_product']):
                    # Calculate Profit and Profit Margin
                    df['profit'] = df['total_revenue'] - df['base_cost']
                    df['profit_margin'] = df.apply(
                        lambda row: (row['profit'] / row['total_revenue'] * 100) if row['total_revenue'] > 0 else 0, axis=1
                    )
                    # Format monetary columns
                    for col in ['avg_sales_value', 'total_revenue', 'base_cost', 'profit']:
                        df[col] = df[col].apply(lambda x: f"₱{x:,.2f}")
                    df['profit_margin'] = df['profit_margin'].apply(lambda x: f"{x:.1f}%")
                    # Rename columns for display
                    df.rename(columns={
                        'total_invoices': 'Total Invoices',
                        'avg_sales_value': 'Average Sales Value',
                        'total_revenue': 'Total Revenue',
                        'base_cost': 'Base Cost',
                        'low_stock_count': 'Low Stock Products',
                        'top_product': 'Top-Selling Product',
                        'profit': 'Profit',
                        'profit_margin': 'Profit Margin'
                    }, inplace=True)
                    # Display metrics in a card-like layout
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
                    # Download button for data
                    st.download_button("Download Admin Overview Data", df.to_csv(index=False), "admin_overview.csv")
            elif "total revenue" in query.lower():
                # Process Total Revenue query
                if 'total_revenue' in df.columns:
                    df['total_revenue'] = df['total_revenue'].apply(lambda x: f"₱{x:,.2f}")
                    st.markdown("### Total Revenue")
                    st.markdown(f"**Total Revenue**: {df['total_revenue'].iloc[0]}")
                    st.download_button("Download Total Revenue Data", df.to_csv(index=False), "total_revenue.csv")
                else:
                    st.warning("No total revenue data found in the response.")
            else:
                # Handle other queries (e.g., best-selling products)
                if all(col in df.columns for col in ['product_id', 'product_name', 'total_sold', 'max_price']):
                    df.rename(columns={
                        'product_id': 'Product ID',
                        'product_name': 'Product Name',
                        'total_sold': 'QTY',
                        'max_price': 'Rate'
                    }, inplace=True)
                    if 'total_revenue' in df.columns:
                        df.drop(columns=['total_revenue'], inplace=True)
                    df = df[['Product ID', 'Product Name', 'QTY', 'Rate']].dropna(subset=['Product ID', 'Product Name', 'QTY', 'Rate'])
                    df = adjust_quantities_with_voids(df)
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
                            st.pyplot(fig)
                            st.download_button("Download Data", df.to_csv(index=False), "data.csv")
                    if len(df) > 1 or len(df.columns) > 1:
                        st.table(df)
                else:
                    st.warning("Unexpected data format. Please check the query or data source.")

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
            return None, "Empty response from API", status_code
        data = response.json()
        if data.get("status") == "success":
            return data["data"], "Success", status_code
        else:
            return None, data.get("error", "Unknown error"), status_code
    except requests.RequestException as e:
        return None, str(e), "N/A"

# Validate SQL query
def validate_query(query):
    allowed_keywords = [
        "SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT",
        "SUM", "COUNT", "AVG", "MIN", "MAX", "JSON_EXTRACT", "BETWEEN", "LIKE", "IN", "AS"
    ]
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        raise ValueError("Query must start with SELECT")
    if not any(kw in query_upper for kw in allowed_keywords[1:]):
        raise ValueError("Query must contain at least one of: " + ", ".join(allowed_keywords[1:]))
    return True

# Define SQL chain
def get_sql_chain():
    schema = """
    Database Schema:
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash/Card/Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - void_logs: void_id (PK), invoice_id (FK to invoices), void_type, details (JSON), status, created_at, updated_at
    ...
    """

    template = """
    You are an AI assistant for the SCC School Store Database, generating SQL queries for MariaDB 10.6.21.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - For best-selling products, use:
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold, MAX(id.unit_price) AS max_price
      FROM invoice_details id
      JOIN products p ON id.product_id = p.product_id
      JOIN invoices i ON id.invoice_id = i.invoice_id
      WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN '2025-02-14 00:00:00' AND '2025-05-02 19:51:00'
      GROUP BY p.product_id, p.product_name
      ORDER BY total_sold DESC, p.product_id ASC
      LIMIT 10
    - For admin overview metrics, use:
      WITH invoice_stats AS (
          SELECT 
              COUNT(invoice_id) AS total_invoices,
              ROUND(AVG(total), 2) AS avg_sales_value,
              SUM(total) AS total_revenue
          FROM invoices
          WHERE total > 0
          AND CONCAT(order_date, ' ', order_time) BETWEEN '2025-02-14 00:00:00' AND '2025-05-02 19:51:00'
      ),
      cost_stats AS (
          SELECT 
              COALESCE(SUM(id.quantity * p.purchase_price), 0) AS base_cost
          FROM invoices i
          LEFT JOIN invoice_details id ON id.invoice_id = i.invoice_id
          LEFT JOIN products p ON id.product_id = p.product_id
          WHERE i.total > 0
          AND CONCAT(i.order_date, ' ', i.order_time) BETWEEN '2025-02-14 00:00:00' AND '2025-05-02 19:51:00'
      )
      SELECT 
          i_stats.total_invoices,
          i_stats.avg_sales_value,
          i_stats.total_revenue,
          c_stats.base_cost,
          (SELECT COUNT(*) 
           FROM products p 
           WHERE p.stock <= p.reorder_level) AS low_stock_count,
          (SELECT p.product_name 
           FROM invoice_details id2
           INNER JOIN products p ON id2.product_id = p.product_id
           INNER JOIN invoices i2 ON id2.invoice_id = i2.invoice_id
           WHERE i2.total > 0
           AND CONCAT(i2.order_date, ' ', i.order_time) BETWEEN '2025-02-14 00:00:00' AND '2025-05-02 19:51:00'
           GROUP BY p.product_id, p.product_name
           ORDER BY SUM(id2.quantity) DESC
           LIMIT 1) AS top_product
      FROM invoice_stats i_stats
      CROSS JOIN cost_stats c_stats
    - For total revenue, use:
      SELECT SUM(total) AS total_revenue
      FROM invoices
      WHERE total > 0
      AND CONCAT(order_date, ' ', order_time) BETWEEN '2025-02-14 00:00:00' AND '2025-05-02 19:51:00'
    - Use 'today' as '{current_sg_date}' for daily queries.
    - For revenue, use SUM(i.total) from invoices to account for discounts.
    - For base cost, use SUM(id.quantity * COALESCE(p.purchase_price, 0)) from invoice_details id JOIN products p.
    - For profit, use SUM(i.total - (id.quantity * COALESCE(p.purchase_price, 0))) from invoices i JOIN invoice_details id JOIN products p.
    - Use COALESCE to handle NULL purchase_price values, assuming 0 if NULL.
    - If the query asks for 'all time' or 'from the very first invoice', do NOT add a date filter unless specified.
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
    4. Uses COALESCE for purchase_price in profit calculations
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
            chat_history=lambda x: x["chat_history"]
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
        "profit", "margin", "overview", "metrics"
    ]
    debug_info = {"raw_query": "", "cleaned_query": "", "api_response": "", "status_code": ""}
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

        # Debug: Show queries
        if st.session_state.debug_mode:
            st.write(f"Raw query: {raw_query}")
            st.write(f"Cleaned query: {query}")

        # Validate query
        try:
            validate_query(query)
        except ValueError as e:
            debug_info["api_response"] = str(e)
            return f"Invalid SQL query: {str(e)}. Please rephrase your question.", None, debug_info

        data, api_response, status_code = fetch_data_from_api("execute_query", {"query": query})
        debug_info["api_response"] = api_response
        debug_info["status_code"] = status_code
        if data is None:
            return f"Couldn't retrieve data. API error: {api_response} (Status: {status_code}). Try rephrasing or adjusting your query.", None, debug_info

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - If empty results, check if the query involves profit and suggest: "No profit data found. This may be due to missing purchase price information or no sales records. Try checking specific products or time frames."
        - Highlight insights with **bold**.
        - Use - for lists, ₱ for money.
        - Parse JSON fields (e.g., amount_discounted) into readable format.
        - Keep concise (<200 words).
        - Suggest follow-up: "Would you like more details or to check specific products?"
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

        return natural_response, data, debug_info

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2 or len(df) < 2:
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
                st.checkbox("Debug Mode", key="debug_mode", value=True)
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
                        "What are the admin overview metrics for the selected period?",
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
