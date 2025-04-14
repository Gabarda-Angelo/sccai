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
                if any(mon in col for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                elif col.lower() == "total_sold":
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
                        ax.set_ylabel("Units Sold" if columns[1].lower() == "total_sold" else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel("Units Sold" if columns[1].lower() == "total_sold" else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '')}")
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 1 or len(df.columns) > 1:
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
            with open("error_log.txt", "a") as f:
                f.write(f"{datetime.datetime.now()}: Empty API response for query '{st.session_state.last_query}'\n")
            return None

        try:
            data = response.json()
        except json.JSONDecodeError:
            st.error(f"Invalid JSON response: {response.text[:200]}...")
            with open("error_log.txt", "a") as f:
                f.write(f"{datetime.datetime.now()}: Invalid JSON for query '{st.session_state.last_query}'\n")
            return None

        if data.get("status") == "success":
            return data["data"]
        else:
            error_msg = data.get("error", "Unknown error")
            st.error(f"API Error: {error_msg}")
            with open("error_log.txt", "a") as f:
                f.write(f"{datetime.datetime.now()}: API error for query '{st.session_state.last_query}': {error_msg}\n")
            return None
    except requests.RequestException as e:
        st.error(f"Connection error: {str(e)}")
        with open("error_log.txt", "a") as f:
            f.write(f"{datetime.datetime.now()}: Connection error for query '{st.session_state.last_query}': {str(e)}\n")
        return None

# Function to validate SQL queries
def validate_query(query):
    """Validate that the SQL query is safe and executable."""
    allowed_keywords = ["SELECT", "FROM", "WHERE", "INNER JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT"]
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        return False
    if "INNER JOIN" in query_upper and "ON" not in query_upper:
        return False  # Ensure JOINs have ON clauses
    return all(any(kw in query_upper for kw in allowed_keywords) for line in query_upper.split("\n") if line.strip())

# Function to define SQL chain for query generation
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
    You are an AI assistant generating SQL queries for the SCC School Store Database.
    Based on the schema, create an accurate SQL query for the user's question.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use INNER JOINs for valid records.
    - Ensure invoices are valid (i.total > 0).
    - Calculations:
      - Revenue: SUM(id.quantity * id.unit_price)
      - Profit: SUM((id.unit_price - p.purchase_price) * id.quantity)
      - Profit Margin: ((p.sale_price - p.purchase_price) / p.sale_price) * 100
      - Base Cost: SUM(p.purchase_price * id.quantity)
      - Quantity Sold: SUM(id.quantity)
    - Group by product_id, product_name for product-based queries.
    - Handle time ranges:
      - 'all time': i.order_date >= (SELECT MIN(order_date) FROM invoices)
      - 'today': i.order_date = '{current_sg_date}'
      - 'this month': i.order_date BETWEEN DATE_SUB('{current_sg_date}', INTERVAL DAY('{current_sg_date}')-1 DAY) AND '{current_sg_date}'
      - Specific range: i.order_date BETWEEN 'start_date' AND 'end_date'
    - Use DECIMAL for monetary fields, INTEGER for quantities.
    - Return only the SQL query, no explanations.

    **Examples:**
    - Best-selling products:
      SELECT p.product_id, p.product_name, SUM(id.quantity) AS total_sold
      FROM invoice_details id
      INNER JOIN products p ON id.product_id = p.product_id
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id
      WHERE i.total > 0
      GROUP BY p.product_id, p.product_name
      ORDER BY total_sold DESC
      LIMIT 5;
    - Total revenue today:
      SELECT SUM(id.quantity * id.unit_price) AS total_revenue
      FROM invoice_details id
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id
      WHERE i.order_date = '{current_sg_date}' AND i.total > 0;
    - Profit for SCC SHIRT:
      SELECT p.product_id, p.product_name, SUM((id.unit_price - p.purchase_price) * id.quantity) AS total_profit
      FROM invoice_details id
      INNER JOIN products p ON id.product_id = p.product_id
      INNER JOIN invoices i ON id.invoice_id = i.invoice_id
      WHERE p.product_name = 'SCC SHIRT' AND i.total > 0;

    **User Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "qwen-2.5-coder-32b",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.3-70b-versatile",
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
    Synthesize the best SQL query from:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return ONLY the SQL query. Ensure:
    1. Starts with SELECT
    2. Uses INNER JOINs
    3. Groups by product_id, product_name for product queries
    4. Includes WHERE i.total > 0
    5. No comments or markdown
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
        | ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
# Function to generate AI response
def get_response(user_query: str, chat_history: list):
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve", "profit", "margin", "cost"
    ]

    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        natural_response = f"The current time and date in Singapore is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
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
            fallback_chain = (
                ChatPromptTemplate.from_template(
                    "No valid query could be generated for: {question}. Try rephrasing, e.g., 'Show total sales for today' or 'List best-selling products this month'."
                )
                | ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
                | StrOutputParser()
            )
            natural_response = fallback_chain.invoke({"question": user_query})
            return natural_response, None

        if "best-selling" in user_query.lower() or "revenue" in user_query.lower():
            fetch_data_from_api.clear()
        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None or not data:
            fallback_chain = (
                ChatPromptTemplate.from_template(
                    "No data found for: {question}. Try a broader time frame (e.g., 'this year') or check product names."
                )
                | ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
                | StrOutputParser()
            )
            natural_response = fallback_chain.invoke({"question": user_query})
            return natural_response, None

        # Validate and format data
        df = pd.DataFrame(data)
        for col in df.columns:
            if any(mon in col.lower() for mon in ["revenue", "profit", "cost", "price", "total", "subtotal", "paid", "due"]):
                df[col] = pd.to_numeric(df[col], errors='coerce').round(2)
            elif "quantity" in col.lower() or "sold" in col.lower():
                df[col] = pd.to_numeric(df[col], errors='coerce', downcast='integer')

        response_template = """
        Based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - If empty, say: "No data found. Try a broader time frame or different product."
        - Quantities: Use "X units sold".
        - Monetary values: Use "₱X pesos" (e.g., revenue, profit).
        - Highlight insights (e.g., top product, highest value).
        - Use markdown: **bold** for emphasis, - for lists.
        - Keep concise (<200 words).
        - No customer names, only cashier names.
        - Give accurate and correct response from the database data.
        - Include the time stamp period (e.g, we get this data from: (Period: 2025-02-14 00:00:00 - 2025-04-14 08:39:04))
        """

        chain = (
            RunnablePassthrough.assign(
                response=lambda _: json.dumps(data, indent=2)
            )
            | ChatPromptTemplate.from_template(response_template)
            | ChatGroq(model="meta-llama/llama-4-maverick-17b-128e-instruct", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
            | StrOutputParser()
        )

        natural_response = chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
        })

        return natural_response, data
# Function to determine chart type for data visualization
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        return None, None

    columns = df.columns.tolist()
    query_lower = query.lower()

    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()

    # Prioritize financial metrics
    financial_cols = [col for col in numerical_columns if any(k in col.lower() for k in ["revenue", "profit", "cost", "price", "total"])]
    quantity_cols = [col for col in numerical_columns if any(k in col.lower() for k in ["quantity", "sold"])]

    if date_columns and (financial_cols or quantity_cols):
        num_col = financial_cols[0] if financial_cols else quantity_cols[0] if quantity_cols else numerical_columns[0]
        return "line", (date_columns[0], num_col)
    elif categorical_columns and (financial_cols or quantity_cols):
        num_col = financial_cols[0] if financial_cols else quantity_cols[0] if quantity_cols else numerical_columns[0]
        unique_categories = len(df[categorical_columns[0]].unique())
        if unique_categories <= 6 and ("percentage" in query_lower or "margin" in query_lower):
            return "pie", (categorical_columns[0], num_col)
        else:
            return "bar", (categorical_columns[0], num_col)
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
                with st.expander("📈 Sales Performance", expanded=True):
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
                        "What is the current stock level for [specific product]?",
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
                        "What are the login and logout times for [specific employee] today?",
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
                        "Which products have the highest discounts applied?"
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
                        "Show me the inventory changes for [specific product] this week.",
                        "What are the most recent inventory adjustments?"
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q}"):
                            handle_query(q)

                with st.expander("🔍 Miscellaneous Insights"):
                    misc_queries = [
                        "What is the profit margin for [specific product]?",
                        "How many units of [specific product] were sold this month?",
                        "What is the sales history for [specific product]?",
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
