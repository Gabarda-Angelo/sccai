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
if "last_query" not in st.session_state:
    st.session_state.last_query = None

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
            return None
        data = response.json()
        if data.get("status") == "success":
            return data["data"]
        else:
            st.error(f"API Error: {data.get('error', 'Unknown error')}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

# Validate SQL queries
def validate_query(query):
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return False
    disallowed = ["DELETE", "UPDATE", "INSERT", "DROP", "ALTER", "TRUNCATE"]
    return not any(kw in query_upper for kw in disallowed)

# SQL chain for query generation
def get_sql_chain():
    schema = """
    Database Schema:
    - categories: category_id (PK), category_name, created_at, updated_at
    - employees: employee_id (PK), first_name, last_name, role, email, password_hash, created_at, updated_at
    - inventory_logs: log_id (PK), product_id (FK to products), change_type, quantity, log_date, notes, created_at, updated_at
    - invoices: invoice_id (PK), employee_id (FK to employees), order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at, updated_at
    - invoice_details: detail_id (PK), invoice_id (FK to invoices), product_id (FK to products), quantity, unit_price, total_price, created_at, updated_at
    - products: product_id (PK), barcode, product_name, category_id (FK to categories), description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
    - user_logins: log_id (PK), employee_id (FK to employees), login_time, logout_time, ip_address, created_at, updated_at
    - sync_log: id (PK), table_name, record_id, action, timestamp, synced
    """

    template = """
    You are an AI assistant generating SQL queries for the SCC School Store Database.
    Based on the schema, create an accurate SQL query to answer the user's question.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use explicit INNER JOINs with table aliases (e.g., invoices i INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id).
    - For quantities, use invoice_details.quantity; for revenue, use invoice_details.total_price.
    - Calculate totals as SUM(id.total_price); base cost as SUM(id.quantity * p.purchase_price).
    - For overview stats, include:
      - Total invoices: COUNT(DISTINCT i.invoice_id)
      - Average sales: ROUND(AVG(i.total), 2)
      - Total revenue: SUM(id.total_price)
      - Base cost: COALESCE(SUM(id.quantity * p.purchase_price), 0)
      - Profit: SUM(id.total_price) - COALESCE(SUM(id.quantity * p.purchase_price), 0)
      - Profit margin: ((SUM(id.total_price) - COALESCE(SUM(id.quantity * p.purchase_price), 0)) / SUM(id.total_price)) * 100
      - Low stock: COUNT(p.stock <= p.reorder_level)
      - Top product: Product with highest SUM(id.quantity)
    - For best-selling products, group by p.product_id, p.product_name, sum id.quantity, and order by quantity DESC.
    - Apply time filters using CONCAT(i.order_date, ' ', i.order_time) for periods (e.g., today: '{current_sg_date} 00:00:00' to '{current_sg_date} 23:59:59').
    - Use COALESCE for NULL handling in aggregations.
    - Avoid double-counting with DISTINCT where needed.
    - If no period is specified, include all records.
    - Ensure query starts with SELECT and contains no comments.
    - Handle edge cases (e.g., no sales) with meaningful results.

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

    Return ONLY the final SQL query. Ensure it:
    - Starts with SELECT
    - Uses INNER JOINs with aliases
    - Calculates quantities as invoice_details.quantity
    - Uses invoice_details.total_price for revenue
    - Avoids double-counting
    - Aligns with overview stats (invoices, revenue, cost, profit, margin)
    - Applies time filters correctly
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
        return f"Current time and date: {current_time.strftime('%Y-%m-%d %H:%M:%S')}.", None
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

        if not validate_query(query):
            return "Invalid database query generated. Please rephrase your question.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return "Couldn't retrieve data. Please try again.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        - If results are empty, state: "No data found for the specified period or item."
        - Distinguish quantities ("X units") from monetary values ("₱Y pesos").
        - For best-selling products, list top 5 by quantity, including revenue (₱).
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
        """

        chain = (
            RunnablePassthrough.assign(response=lambda _: json.dumps(data, indent=2))
            | ChatPromptTemplate.from_template(response_template)
            | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
            | StrOutputParser()
        )
        natural_response = chain.invoke({
            "question": user_query,
            "chat_history": chat_history,
        })
        return natural_response, data

# Determine chart type
def determine_chart_type(query, df):
    if df.empty or len(df.columns) < 2:
        return None, None
    columns = df.columns.tolist()
    query_lower = query.lower()
    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()

    if "quantity" in query_lower or "sold" in query_lower:
        numerical_cols = [col for col in numerical_columns if "quantity" in col.lower()]
    elif any(kw in query_lower for kw in ["revenue", "total", "profit", "cost"]):
        numerical_cols = [col for col in numerical_columns if any(kw in col.lower() for kw in ["total", "revenue", "profit", "cost"])]
    else:
        numerical_cols = numerical_columns

    if date_columns and numerical_cols:
        return "line", (date_columns[0], numerical_cols[0])
    elif categorical_columns and numerical_cols:
        return "bar", (categorical_columns[0], numerical_cols[0])
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
    st.session_state.chat_history.append(AIMessage(content=natural_response))
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col for mon in ["total", "price", "cost", "profit"]):
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
                        "What is the total revenue this year?",
                        "What is the revenue breakdown by product category?"
                    ]
                    for q in sales_queries:
                        if st.button(q, key=f"sales_{q}"):
                            handle_query(q)
                with st.expander("📦 Inventory Management"):
                    inventory_queries = [
                        "Which products are below the reorder level?",
                        "What is the current stock level for SCC SHIRT?",
                        "What is the total value of current inventory?"
                    ]
                    for q in inventory_queries:
                        if st.button(q, key=f"inv_{q}"):
                            handle_query(q)
                with st.expander("👥 Employee Performance"):
                    employee_queries = [
                        "Who is the top-performing employee this month?",
                        "What are the total sales by each employee this week?"
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
                with st.expander("🏪 Store Operations"):
                    ops_queries = [
                        "What is the busiest hour of the day for sales?",
                        "What is the average number of transactions per day?"
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q}"):
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
