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
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, filename='app.log', filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
if "last_query" not in st.session_state:
    st.session_state.last_query = None

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
            error_msg = data.get('error', 'Invalid credentials')
            st.error(f"Login failed: {error_msg}")
            logging.error(f"Authentication failed: {error_msg}")
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        logging.error(f"Authentication exception: {str(e)}")
    return False

# Fetch data from API with caching
@st.cache_data(ttl=300)
def fetch_data_from_api(action: str, params: dict = None) -> dict:
    try:
        payload = {"action": action, "key": st.secrets["API_KEY"]}
        if params:
            if "query" in params:
                st.session_state.last_query = params["query"]
                params["query"] = quote(params["query"])
            payload.update(params)
        response = requests.get(st.secrets["API_URL"], params=payload, timeout=15)
        if not response.text.strip():
            st.error("Received empty response from API")
            logging.error("Empty API response")
            return None
        data = response.json()
        if data.get("status") == "success":
            return data["data"]
        else:
            error_msg = data.get('error', 'Unknown error')
            st.error(f"API Error: {error_msg}")
            logging.error(f"API error: {error_msg}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        logging.error(f"API connection error: {str(e)}")
        return None

# Validate SQL queries
def validate_query(query):
    try:
        query_upper = query.upper().strip()
        # Allow SELECT queries only
        if not query_upper.startswith("SELECT"):
            logging.warning(f"Invalid query (non-SELECT): {query}")
            return False
        # Block dangerous keywords
        disallowed = ["DELETE", "UPDATE", "INSERT", "DROP", "ALTER", "TRUNCATE", "EXECUTE", "CREATE"]
        if any(kw in query_upper for kw in disallowed):
            logging.warning(f"Invalid query (contains disallowed keyword): {query}")
            return False
        # Basic syntax check (ends with semicolon, balanced quotes)
        if not query.strip().endswith(';'):
            logging.warning(f"Invalid query (no semicolon): {query}")
            return False
        return True
    except Exception as e:
        logging.error(f"Query validation error: {str(e)} - Query: {query}")
        return False

# SQL chain for query generation
def get_sql_chain():
    schema = """
    Database Schema:
    - categories: category_id (PK, int), category_name (varchar), created_at (datetime), updated_at (timestamp)
    - employees: employee_id (PK, int), first_name (varchar), last_name (varchar), role (enum 'Owner','Admin','Cashier'), email (varchar), password_hash (varchar), created_at (datetime), updated_at (timestamp)
    - inventory_logs: log_id (PK, int), product_id (FK to products, int), change_type (enum 'Sale','Restock','Adjustment'), quantity (int), log_date (datetime), notes (text), created_at (timestamp), updated_at (timestamp)
    - invoices: invoice_id (PK, int), employee_id (FK to employees, int), order_date (date), order_time (time), subtotal (decimal), discount (decimal), total (decimal), paid (decimal), due (decimal), payment_type (enum 'Cash','Card','Check'), created_at (datetime), updated_at (timestamp)
    - invoice_details: detail_id (PK, int), invoice_id (FK to invoices, int), product_id (FK to products, int), quantity (int, >0), unit_price (decimal), total_price (decimal), created_at (timestamp), updated_at (timestamp)
    - products: product_id (PK, int), barcode (varchar, unique), product_name (varchar), category_id (FK to categories, int), description (text), stock (int, >=0), reorder_level (int), purchase_price (decimal, >=0), sale_price (decimal, >=purchase_price), image (varchar), created_at (datetime), updated_at (datetime)
    - user_logins: log_id (PK, int), employee_id (FK to employees, int), login_time (datetime), logout_time (datetime), ip_address (varchar), created_at (timestamp), updated_at (timestamp)
    - sync_log: id (PK, int), table_name (varchar), record_id (int), action (enum 'INSERT','UPDATE','DELETE'), timestamp (datetime), synced (tinyint)
    """

    template = """
    You are an expert SQL query generator for the SCC School Store Database.
    Based on the schema, create a precise SQL query to answer the user's question.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Write SELECT queries only, starting with SELECT and ending with a semicolon.
    - Use explicit INNER JOINs with table aliases (e.g., invoices i, invoice_details id, products p).
    - For quantities, use id.quantity; for revenue, use id.total_price.
    - Calculate metrics as follows:
      - Total invoices: COUNT(DISTINCT i.invoice_id)
      - Average sales: ROUND(AVG(i.total), 2)
      - Total revenue: SUM(id.total_price)
      - Base cost: COALESCE(SUM(id.quantity * p.purchase_price), 0)
      - Profit: SUM(id.total_price) - COALESCE(SUM(id.quantity * p.purchase_price), 0)
      - Profit margin: ((SUM(id.total_price) - COALESCE(SUM(id.quantity * p.purchase_price), 0)) / NULLIF(SUM(id.total_price), 0)) * 100
      - Low stock: COUNT(DISTINCT p.product_id) WHERE p.stock <= p.reorder_level
      - Top product: p.product_name with highest SUM(id.quantity)
    - For best-selling products:
      - SELECT p.product_id, p.product_name, SUM(id.quantity) AS units_sold, SUM(id.total_price) AS total_revenue
      - GROUP BY p.product_id, p.product_name
      - ORDER BY units_sold DESC
      - LIMIT 5
    - Apply time filters using CONCAT(i.order_date, ' ', i.order_time):
      - "today": '{current_sg_date} 00:00:00' to '{current_sg_date} 23:59:59'
      - "this month": '{current_sg_date}' LIKE 'YYYY-MM%'
      - "this year": '{current_sg_date}' LIKE 'YYYY%'
    - Use COALESCE for NULL handling in aggregations.
    - Avoid double-counting with DISTINCT where needed.
    - If no period is specified, include all records unless question implies a period (e.g., "today").
    - Handle edge cases (e.g., no sales) with meaningful results (e.g., 0 for sums).
    - Do not include comments or markdown in the query.

    **User Question:** {question}

    **Output:** A single SQL query.
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "llama3-8b-8192",
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
    Synthesize the best SQL query from the following proposals:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    **Instructions:**
    - Return a single SELECT query, ending with a semicolon.
    - Ensure it:
      - Uses INNER JOINs with aliases (i, id, p)
      - Calculates quantities via id.quantity
      - Uses id.total_price for revenue
      - Matches metrics: invoices, revenue, cost, profit, margin
      - Applies time filters correctly
      - Handles NULLs with COALESCE
      - Avoids double-counting
    - Fix any syntax errors or schema misalignments.
    - If all proposals fail, generate a new query based on the question and schema.

    **Output:** Only the final SQL query.
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

# Generate AI response
def get_response(user_query: str, chat_history: list):
    time_keywords = ["current time", "what time is it", "date and time", "today's date", "now"]
    data_keywords = ["sales", "invoice", "product", "revenue", "profit", "cost", "margin", "stock", "quantity"]

    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        logging.info(f"Time query: {user_query} - Response: {current_time}")
        return f"Current time and date: {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None
    else:
        singapore_tz = pytz.timezone('Asia/Singapore')
        now_sg = datetime.datetime.now(singapore_tz)
        current_sg_date = now_sg.strftime('%Y-%m-%d')
        current_sg_datetime = now_sg.strftime('%Y-%m-%d %H:%M:%S')

        sql_chain = get_sql_chain()
        try:
            raw_query = sql_chain.invoke({
                "question": user_query,
                "chat_history": chat_history,
                "current_sg_date": current_sg_date,
                "current_sg_datetime": current_sg_datetime
            })
            query = raw_query.strip()
            if not query.endswith(';'):
                query += ';'
            logging.info(f"Generated SQL query: {query}")
        except Exception as e:
            logging.error(f"SQL generation error: {str(e)} - Question: {user_query}")
            return "Failed to generate a valid SQL query. Please try again.", None

        if not validate_query(query):
            logging.warning(f"Query validation failed: {query}")
            return "Invalid database query generated. Please rephrase your question.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            logging.error(f"No data returned for query: {query}")
            return "Couldn't retrieve data. Please try again.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - If results are empty, state: "No data found for the specified period or item."
        - Distinguish quantities ("X units") from monetary values ("₱Y pesos").
        - For best-selling products:
          - List top 5 by units_sold
          - Format: "- **Product Name**: X units, ₱Y pesos"
          - Include insights (e.g., "leads in units", "highest revenue")
        - For overview queries, include:
          - Total invoices: X transactions
          - Average sales value: ₱Y pesos
          - Total revenue: ₱Z pesos
          - Base cost: ₱A pesos
          - Profit: ₱B pesos
          - Profit margin: C%
          - Top product: Name (D units)
          - Low stock: E items
        - Use markdown: **bold** for emphasis, - for lists.
        - Keep concise, under 200 words.
        - Format monetary values with "₱" and 2 decimals.
        """

        chain = (
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | ChatPromptTemplate.from_template(response_template)
            | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
            | StrOutputParser()
        )
        try:
            natural_response = chain.invoke({
                "question": user_query,
                "chat_history": chat_history,
            })
            logging.info(f"Natural response generated: {natural_response}")
        except Exception as e:
            logging.error(f"Response generation error: {str(e)}")
            natural_response = "Error processing the response. Please try again."
        return natural_response, data

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        logging.info("No chart generated: Empty dataframe or insufficient columns")
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()

    if "quantity" in query_lower or "sold" in query_lower:
        numerical_cols = [col for col in numerical_columns if "quantity" in col.lower() or "units" in col.lower()]
    elif any(kw in query_lower for kw in ["revenue", "total", "profit", "cost"]):
        numerical_cols = [col for col in numerical_columns if any(kw in col.lower() for kw in ["total", "revenue", "profit", "cost"])]
    else:
        numerical_cols = numerical_columns

    if date_columns and numerical_cols:
        logging.info(f"Chart type: Line - Columns: {date_columns[0]}, {numerical_cols[0]}")
        return "line", (date_columns[0], numerical_cols[0])
    elif categorical_columns and numerical_cols:
        logging.info(f"Chart type: Bar - Columns: {categorical_columns[0]}, {numerical_cols[0]}")
        return "bar", (categorical_columns[0], numerical_cols[0])
    logging.info("No suitable chart type determined")
    return None, None

# Handle user queries
def handle_query(query: str):
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)
    with st.spinner("Analyzing your query..."):
        try:
            natural_response, data = get_response(query, st.session_state.chat_history)
        except Exception as e:
            natural_response = f"Error: {str(e)}"
            data = None
            logging.error(f"Query handling error: {str(e)} - Query: {query}")
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["total", "price", "cost", "profit", "revenue"]):
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
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1]} Over Time")
                    ax.set_xlabel(columns[0])
                    ax.set_ylabel(columns[1].replace(' (₱)', ' (Pesos)'))
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
    st.success("Chat history cleared.")
    logging.info("Chat history cleared")

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
                if st.button("Logout"):
                    st.session_state.authenticated = False
                    st.session_state.user = None
                    st.rerun()
                if st.button("Clear Chat"):
                    clear_chat()
                    st.rerun()
                with st.expander("📈 Sales Performance", expanded=True):
                    sales_queries = [
                        "What are the best-selling products of all time?",
                        "What are the top 5 best-selling products this month?",
                        "What is the total revenue this year?"
                    ]
                    for q in sales_queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q)
                with st.expander("📦 Inventory Management"):
                    inventory_queries = [
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?"
                    ]
                    for q in inventory_queries:
                        if st.button(q, key=f"inv_{q}"):
                            handle_query(q)
                with st.expander("👥 Employee Performance"):
                    employee_queries = [
                        "Who is the top-performing employee this month?"
                    ]
                    for q in employee_queries:
                        if st.button(q, key=f"emp_{q}"):
                            handle_query(q)
                with st.expander("💰 Financial Insights"):
                    financial_queries = [
                        "Give the overall total revenue, profit, base cost, and profit margin of the store.",
                        "What is the average transaction value this month?"
                    ]
                    for q in financial_queries:
                        if st.button(q, key=f"fin_{q}"):
                            handle_query(q)
            display_chat_history()
            user_query = st.chat_input("Type a message...")
            if user_query:
                handle_query(user_query)
        else:
            st.error("Access denied. Please contact the Admin.")
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
