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
                st.write(f"**Data Returned**: {json.dumps(data, indent=2)}")
        except Exception as e:
            natural_response = f"Sorry, an error occurred: {str(e)}. Please try rephrasing your question or contact support."
            data = None
            debug_info = {"raw_query": "N/A", "cleaned_query": "N/A", "api_response": str(e), "status_code": "N/A", "data_returned": "N/A"}
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            # Preprocess data
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["total_sold", "rate", "total", "subtotal", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "profit", "margin", "amount_discounted"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    if "rate" in col.lower() or "total" in col.lower():
                        df[col] = df[col].apply(lambda x: f"₱{x:,.2f}" if pd.notnull(x) else x)
                        df.rename(columns={col: f"{col} (₱)"}, inplace=True)
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots()
                    if chart_type == 'bar':
                        plot_df = df.copy()
                        for col in plot_df.columns:
                            if col.endswith(" (₱)"):
                                plot_df[col] = plot_df[col].str.replace('₱', '').str.replace(',', '').astype(float)
                        plot_df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'line':
                        plot_df = df.copy()
                        for col in plot_df.columns:
                            if col.endswith(" (₱)"):
                                plot_df[col] = plot_df[col].str.replace('₱', '').str.replace(',', '').astype(float)
                        plot_df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'pie':
                        plot_df = df.copy()
                        for col in plot_df.columns:
                            if col.endswith(" (₱)"):
                                plot_df[col] = plot_df[col].str.replace('₱', '').str.replace(',', '').astype(float)
                        ax.pie(plot_df[columns[1]], labels=plot_df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '')}")
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 1 or len(df.columns) > 1:
                st.table(df)
            elif len(df) == 1 and len(df.columns) == 1:
                st.markdown(f"**Result**: {df.iloc[0, 0]}")

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
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        raise ValueError("Query must start with SELECT")
    if any(kw in query_upper for kw in ["INSERT", "UPDATE", "DELETE", "DROP"]):
        raise ValueError("Only SELECT queries are allowed")
    return True

# Define SQL chain
def get_sql_chain():
    schema = """
    Database Schema:
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type (Cash/Card/Check), created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    ...
    """

    template = """
    You are an AI assistant for the SCC School Store Database, generating SQL queries for MariaDB 10.6.21.

    **Database Schema:**
    {schema}

    **Current date in Manila:** {current_manila_date} (YYYY-MM-DD)
    **Current datetime in Manila:** {current_manila_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use 'today' as '{current_manila_date}' (e.g., WHERE order_date = '{current_manila_date}').
    - For time-based queries, use CONCAT(i.order_date, ' ', i.order_time) for precise datetime filtering.
    - For best-selling products, include product_id, product_name, SUM(quantity) as total_sold, MAX(unit_price) as rate, SUM(total_price) as total, GROUP BY id.product_id, ORDER BY SUM(quantity) DESC, LIMIT 10.
    - For revenue, use SUM(i.total) from invoices to account for discounts.
    - For base cost, use SUM(id.quantity * COALESCE(p.purchase_price, 0)) from invoice_details id JOIN products p.
    - For profit, use SUM(i.total - (id.quantity * COALESCE(p.purchase_price, 0))) from invoices i JOIN invoice_details id JOIN products p.
    - Use COALESCE to handle NULL purchase_price values, assuming 0 if NULL.
    - If the query asks for 'all time' or 'from the very first invoice', use the earliest invoice date from invoices.
    - For 'this month', use the full month (e.g., 2025-05-01 to 2025-05-31).
    - Ensure queries are valid for MariaDB 10.6.21.
    - Return only the SQL query, no explanations.

    **User Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "llama-3.3-70b-versatile",  # Prioritize stronger model
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
    5. Uses CONCAT(order_date, ' ', order_time) for datetime filtering
    6. For best-selling products, GROUP BY id.product_id, ORDER BY SUM(quantity) DESC, LIMIT 10
    7. Valid for MariaDB 10.6.21
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)
    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_manila_date=lambda x: x["current_manila_date"],
            current_manila_datetime=lambda x: x["current_manila_datetime"],
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
    debug_info = {"raw_query": "", "cleaned_query": "", "api_response": "", "status_code": "", "data_returned": ""}
    manila_tz = pytz.timezone('Asia/Manila')
    now_manila = datetime.datetime.now(manila_tz)
    current_manila_date = now_manila.strftime('%Y-%m-%d')
    current_manila_datetime = now_manila.strftime('%Y-%m-%d %H:%M:%S')

    # Handle best-selling products query directly via API
    if "best-selling" in user_query.lower() or "best selling" in user_query.lower():
        date_from = date_to = None
        if "this month" in user_query.lower():
            date_from = now_manila.replace(day=1).strftime('%Y-%m-%d 00:00:00')
            date_to = now_manila.replace(day=1, month=now_manila.month+1 if now_manila.month < 12 else 1, year=now_manila.year+1 if now_manila.month == 12 else now_manila.year).replace(day=1).strftime('%Y-%m-%d 00:00:00')
        elif "this week" in user_query.lower():
            date_from = (now_manila - datetime.timedelta(days=now_manila.weekday())).strftime('%Y-%m-%d 00:00:00')
            date_to = (now_manila + datetime.timedelta(days=6-now_manila.weekday())).strftime('%Y-%m-%d 23:59:59')
        elif "this year" in user_query.lower():
            date_from = now_manila.replace(month=1, day=1).strftime('%Y-%m-%d 00:00:00')
            date_to = now_manila.replace(month=12, day=31).strftime('%Y-%m-%d 23:59:59')
        else:
            # Fetch earliest invoice date
            data, _, _ = fetch_data_from_api("execute_query", {"query": "SELECT MIN(CONCAT(order_date, ' ', order_time)) AS min_date FROM invoices;"})
            date_from = data[0]["min_date"] if data and data[0]["min_date"] else '1970-01-01 00:00:00'
            date_to = now_manila.strftime('%Y-%m-%d 23:59:59')

        params = {"date_from": date_from, "date_to": date_to}
        data, api_response, status_code = fetch_data_from_api("get_best_selling_products", params)
        debug_info["api_response"] = api_response
        debug_info["status_code"] = status_code
        debug_info["raw_query"] = "API call: get_best_selling_products"
        debug_info["cleaned_query"] = f"date_from: {date_from}, date_to: {date_to}"
        debug_info["data_returned"] = json.dumps(data, indent=2)

        if data is None:
            return f"Couldn't retrieve best-selling products: {api_response}. Try rephrasing or checking the database.", None, debug_info

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - List top products with product ID, name, quantity sold, rate (₱), and total sales (₱).
        - Highlight insights with **bold**.
        - Use - for lists.
        - Keep concise (<200 words).
        - Suggest follow-up: "Would you like to see sales for a different period or product details?"
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

    # Handle other queries via SQL generation
    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        return f"Your current time and date is {current_manila_datetime} in Manila.", None, debug_info
    else:
        # Check for missing data
        data_check_query = "SELECT COUNT(*) as count FROM products WHERE purchase_price IS NULL;"
        check_data, check_response, check_status = fetch_data_from_api("execute_query", {"query": data_check_query})
        if check_data and check_data[0]["count"] > 0:
            debug_info["api_response"] += f" Warning: {check_data[0]['count']} products have missing purchase_price, which may affect profit calculations."

        sql_chain = get_sql_chain()
        raw_query = sql_chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
            "current_manila_date": current_manila_date,
            "current_manila_datetime": current_manila_datetime
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
            return f"Sorry, the query is invalid: {str(e)}. Please rephrase your question.", None, debug_info

        data, api_response, status_code = fetch_data_from_api("execute_query", {"query": query})
        debug_info["api_response"] = api_response
        debug_info["status_code"] = status_code
        debug_info["data_returned"] = json.dumps(data, indent=2)
        if data is None:
            return f"Couldn't retrieve data: {api_response} (Status: {status_code}). Try rephrasing your query or checking the database.", None, debug_info

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
        - If results are empty, warn about potential missing data.
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

        if not data:
            natural_response += "\n\n**Note**: This may be due to missing data (e.g., purchase prices or sales records). Would you like me to check specific products or periods?"

        return natural_response, data, debug_info

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 1:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    if len(df) == 1 and len(columns) == 1:
        return None, None  # Skip charts for single-value results
    if "best-selling" in query_lower or "best selling" in query_lower:
        if "product_name" in columns and "total_sold" in columns:
            return "bar", ("product_name", "total_sold")
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
