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
    """Process a user's query, update chat history, and display response with time period."""
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
                if any(mon in col for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "profit", "profit_margin"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)" if "margin" not in col.lower() else f"{col} (%)"}, inplace=True)
            
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots()
                    if chart_type == 'bar':
                        df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)').replace(' (%)', ' (%)'))
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)').replace(' (%)', ' (%)'))
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1]}")
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
@st.cache_data(ttl=300)  # Cache for 5 minutes
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
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return False
    if "FROM" not in query_upper:
        return False
    return True

# Function to validate calculations
def validate_calculations(data, query):
    """Validate numerical calculations in the API response."""
    if not data or not isinstance(data, list):
        return True  # No data to validate

    df = pd.DataFrame(data)
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns

    query_lower = query.lower()
    for col in numerical_columns:
        # Check for negative values in monetary fields
        if any(term in col.lower() for term in ["subtotal", "total", "price", "paid", "profit"]) and (df[col] < 0).any():
            st.warning(f"Warning: Negative values found in {col}, which may indicate an error.")
            return False

        # Verify sums/averages for specific queries
        if any(term in query_lower for term in ["total", "revenue", "profit"]) and any(term in col.lower() for term in ["total", "sum", "profit"]):
            total = df[col].sum()
            if total == 0 and len(df) > 0:
                st.warning(f"Warning: Sum of {col} is zero, which may be unexpected.")
                return False

    return True

# Function to define SQL chain for query generation
def get_sql_chain():
    """Create a chain to generate SQL queries with precise calculations and time period clarity."""
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at
    - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address

    Notes:
    - 'Profit' is calculated as (p.sale_price - p.purchase_price) * id.quantity for each product in invoice_details.
    - 'Profit margin' is ((p.sale_price - p.purchase_price) / p.sale_price) * 100 as a percentage.
    - 'Base cost' refers to p.purchase_price * id.quantity.
    - 'Revenue' is the sum of i.total from invoices or id.total_price from invoice_details.
    """

    template = """
    You are an AI assistant generating SQL queries for the SCC School Store Database.
    Based on the schema, create an accurate SQL query to answer the user's question, focusing on precise calculations and clear time periods.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (format: YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (format: YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use 'today' as '{current_sg_date}' for queries mentioning 'today' (e.g., WHERE order_date = '{current_sg_date}').
    - For 'this month', use dates from '{current_sg_date}' with day '01' to '{current_sg_date}'.
    - For 'this week', use dates from the Monday before '{current_sg_date}' to '{current_sg_date}'.
    - If no time period is specified (e.g., 'best selling products'), assume all time (no date filter).
    - For calculations (e.g., SUM, AVG), use COALESCE(value, 0) and ROUND(value, 2) for monetary values.
    - Use explicit JOINs with table aliases (e.g., invoices i JOIN invoice_details id ON i.invoice_id = id.invoice_id).
    - Return a JSON object with:
      - 'query': The SQL query (ending with semicolon).
      - 'time_period': A description (e.g., 'today (2025-04-13)', 'all time', 'this month (2025-04-01 to 2025-04-13)').
    - Avoid non-existent tables/columns.
    - Ensure queries are safe (SELECT only).
    - For 'profit', calculate (p.sale_price - p.purchase_price) * id.quantity.
    - For 'profit margin', calculate ((p.sale_price - p.purchase_price) / p.sale_price) * 100.

    **User Question:** {question}

    **Example Output:**
    {
      "query": "SELECT p.product_name, SUM(id.quantity) as total_sold FROM products p JOIN invoice_details id ON p.product_id = id.product_id GROUP BY p.product_name ORDER BY total_sold DESC LIMIT 5;",
      "time_period": "all time"
    }
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
    Synthesize the best SQL query and time period from these proposals:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return a JSON object and nothing else:
    {
      "query": "SELECT ...;",
      "time_period": "e.g., today (2025-04-13) or all time"
    }

    Ensure:
    1. Query starts with SELECT and uses explicit JOINs.
    2. Calculations use ROUND(value, 2) and COALESCE(value, 0).
    3. Time period matches the question or defaults to 'all time'.
    4. No comments, markdown, or extra text in the query.
    5. Handle 'profit' as (sale_price - purchase_price) * quantity.
    6. Handle 'profit margin' as ((sale_price - purchase_price) / sale_price) * 100.

    **Example Output:**
    {
      "query": "SELECT p.product_name, SUM(id.quantity) as total_sold FROM products p JOIN invoice_details id ON p.product_id = id.product_id GROUP BY p.product_name ORDER BY total_sold DESC LIMIT 5;",
      "time_period": "all time"
    }
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
    """Generate a response with time period and validated calculations."""
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve", "profit", "cost", "margin"
    ]

    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        natural_response = f"The current time and date is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
        return natural_response, None
    else:
        singapore_tz = pytz.timezone('Asia/Singapore')
        now_sg = datetime.datetime.now(singapore_tz)
        current_sg_date = now_sg.strftime('%Y-%m-%d')
        current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

        sql_chain = get_sql_chain()
        raw_response = sql_chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
            "current_sg_date": current_sg_date,
            "current_sg_datetime": current_sg_datetime
        })

        # Parse JSON response with regex to handle extra text
        try:
            json_match = re.search(r'\{.*?\}', raw_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                response_dict = json.loads(json_str)
                query = response_dict.get("query", "").split(";")[0] + ";"
                time_period = response_dict.get("time_period", "unspecified period")
            else:
                raise json.JSONDecodeError("No JSON object found", raw_response, 0)
        except json.JSONDecodeError:
            st.write(f"Debug: Raw aggregator response: {raw_response}")
            query = raw_response.split(";")[0] + ";" if ";" in raw_response else raw_response
            time_period = "unspecified period"

        # Clean query
        query = query.replace("```sql", "").replace("```", "").strip()
        query = "\n".join(
            [line for line in query.split("\n") if not line.strip().startswith(("--", "#", "/*"))]
        )

        # Debug output
        st.write(f"Debug: Generated SQL query: {query}")

        if not validate_query(query):
            st.write("Debug: Query validation failed.")
            return "Failed to generate a valid database query. Please try again.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return f"Couldn't retrieve data for {time_period}. Please try again or rephrase your question.", None

        # Validate calculations
        if not validate_calculations(data, user_query):
            return f"Calculation error detected in the data for {time_period}. Please verify your query.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **Time Period:** {time_period}
        - **History:** {chat_history}

        **Guidelines:**
        1. Start with: "For {time_period}, ..."
        2. If results are empty, say: "No data found for {time_period}. Try a broader time frame or different product."
        3. Highlight key insights (e.g., highest/lowest values, trends).
        4. Use markdown: **bold** for emphasis, - for lists.
        5. Include peso sign (₱) for monetary values, percentage (%) for margins.
        6. Keep concise, under 200 words.
        """

        chain = (
            RunnablePassthrough.assign(
                response=lambda _: json.dumps(data, indent=2),
                time_period=lambda _: time_period
            )
            | ChatPromptTemplate.from_template(response_template)
            | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
            | StrOutputParser()
        )

        natural_response = chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
            "time_period": time_period
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
        if unique_categories <= 6 and any(term in query_lower for term in ["percentage", "margin", "distribution"]):
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
