import streamlit as st
import pandas as pd
import requests
import json
from urllib.parse import quote
import datetime
import pytz
from langchain.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import plotly.express as px

# --- Session State Initialization ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_query" not in st.session_state:
    st.session_state.last_query = ""
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None

# --- Utility Functions ---

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_data_from_api(action: str, params: dict = None) -> dict:
    """Fetch data from the API with enhanced error handling."""
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
        response.raise_for_status()  # Raise an exception for HTTP errors
        try:
            data = response.json()
        except json.JSONDecodeError:
            st.error("Received invalid data from the server.")
            return None

        if data.get("status") == "success":
            return data["data"]
        else:
            st.error(f"API Error: {data.get('error', 'Unknown error')}")
            return None
    except requests.Timeout:
        st.error("Request timed out. Please try again later.")
        return None
    except requests.RequestException as e:
        st.error(f"Connection error: {str(e)}")
        return None

def get_sql_chain():
    """Generate SQL queries using a single high-performing model."""
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

    **Conversation History:** {chat_history}

    **Instructions:**
    - When the user mentions "today," use the current date in Singapore, e.g., WHERE order_date = '{current_sg_date}'.
    - If the user specifies a time range up to the current time, use appropriate conditions.
    - Use appropriate joins when data from multiple tables is needed.
    - Consider foreign key relationships between tables.
    - Use aggregate functions if the question implies summarization.
    - Filter data based on conditions mentioned in the question.
    - Order results if the question suggests a specific order.
    - Assume the most common interpretation if the question is ambiguous.
    - Avoid referencing non-existent tables or columns.
    - Provide only the SQL query as output, without explanations.

    **User Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    llm = ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])

    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda x: x["current_sg_date"],
            current_sg_datetime=lambda x: x["current_sg_datetime"],
        )
        | prompt
        | llm
        | StrOutputParser()
    )

def get_response(user_query: str, chat_history: list):
    """Generate a response and fetch data with SQL validation and edge case handling."""
    time_keywords = ["current time", "what time is it", "date and time", "today's date", "now", "time today", "date today"]
    data_keywords = ["sales", "invoice", "details", "product", "category", "stock", "revenue", "order", "employee", "payment", "quantity", "price", "total", "subtotal", "discount", "due", "paid", "inventory", "log", "detail", "list", "show", "provide", "get", "fetch", "retrieve"]

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

        # SQL Query Validation
        if not query.lower().startswith("select"):
            st.error("Only SELECT queries are allowed.")
            return "Only SELECT queries are allowed.", None

        forbidden_keywords = ["drop", "delete", "update", "insert"]
        if any(keyword in query.lower() for keyword in forbidden_keywords):
            st.error("Query contains forbidden keywords.")
            return "Query contains forbidden keywords.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if not data:
            return "Couldn't retrieve data. Please try again or rephrase your question.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        1. If the query is about future dates, mention that future data cannot be predicted.
        2. If results are empty, suggest possible reasons or alternative queries.
        3. Be clear and concise.
        4. Highlight key numbers or trends.
        5. Use bullet points for lists.
        6. Mention any data limitations.
        7. Keep under 200 words.
        8. Use markdown formatting to enhance readability.
        9. Use the peso sign (₱) for monetary values.
        10. Avoid referencing non-existent data.
        11. For follow-up questions, reference the previous query and results.
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

def determine_chart_type(query, df):
    """Determine chart type based on query and data characteristics."""
    if df.empty or len(df.columns) < 2:
        return None, None

    columns = df.columns.tolist()
    query_lower = query.lower()

    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()

    if date_columns and numerical_columns:
        if any(word in query_lower for word in ["trend", "over time", "history"]):
            return "line", (date_columns[0], numerical_columns[0])

    if categorical_columns and numerical_columns:
        if any(word in query_lower for word in ["distribution", "share", "percentage", "breakdown"]):
            return "pie", (categorical_columns[0], numerical_columns[0])
        elif any(word in query_lower for word in ["top", "best", "most", "ranking"]):
            return "bar", (categorical_columns[0], numerical_columns[0])
        return "bar", (categorical_columns[0], numerical_columns[0])

    if date_columns and numerical_columns:
        return "line", (date_columns[0], numerical_columns[0])

    return None, None

def authenticate(email: str, password: str) -> bool:
    """Authenticate user with email and password."""
    params = {"email": email, "password": password}
    user_data = fetch_data_from_api("authenticate", params)
    if user_data:
        st.session_state.authenticated = True
        st.session_state.user_role = user_data.get("role")
        st.success(f"Welcome, {user_data.get('first_name')} {user_data.get('last_name')}!")
        return True
    else:
        st.error("Authentication failed. Check your credentials.")
        return False

def handle_query(user_query: str):
    """Process user query and display results with charts."""
    with st.spinner("Processing your query..."):
        response, data = get_response(user_query, st.session_state.chat_history)
        st.markdown(response)

        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            # Filter sensitive columns
            sensitive_columns = ["password_hash", "ip_address"]
            df = df.drop(columns=[col for col in sensitive_columns if col in df.columns], errors='ignore')
            # Rename monetary columns with peso sign
            monetary_columns = ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due"]
            for col in monetary_columns:
                if col in df.columns:
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)

            st.dataframe(df)  # Interactive table

            chart_type, columns = determine_chart_type(user_query, df)
            if chart_type:
                st.markdown(f"### {chart_type.capitalize()} Chart")
                try:
                    if chart_type == "bar":
                        fig = px.bar(df, x=columns[0], y=columns[1], title=f"{columns[1]} by {columns[0]}")
                    elif chart_type == "line":
                        fig = px.line(df, x=columns[0], y=columns[1], title=f"{columns[1]} over {columns[0]}")
                    elif chart_type == "pie":
                        fig = px.pie(df, names=columns[0], values=columns[1], title=f"Distribution of {columns[1]}")
                    st.plotly_chart(fig)
                except Exception as e:
                    st.write(f"Chart rendering failed: {str(e)}")

        st.session_state.chat_history.append({"role": "user", "content": user_query})
        st.session_state.chat_history.append({"role": "assistant", "content": response})

# --- Streamlit App Layout ---

st.title("SCC School Store Database Chat Interface")
st.sidebar.header("Navigation")

if not st.session_state.authenticated:
    st.sidebar.subheader("Login")
    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        authenticate(email, password)
else:
    st.sidebar.success(f"Logged in as {st.session_state.user_role}")
    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.user_role = None
        st.session_state.chat_history = []
        st.success("Logged out successfully.")

    # Sidebar Quick Queries
    with st.sidebar.expander("📊 Quick Queries"):
        if st.button("Total sales today"):
            handle_query("What are the total sales today?")
        if st.button("Top 5 products by sales"):
            handle_query("What are the top 5 products by sales this month?")

    with st.sidebar.expander("🔐 User Activity"):
        if st.button("Who is currently logged in?"):
            handle_query("Who is currently logged in?")
        if st.button("Login activity today"):
            handle_query("Show login activity for today")

    # Main Chat Interface
    st.subheader("Ask a Question")
    user_query = st.text_input("Enter your question about the database:")
    if st.button("Submit"):
        if user_query:
            handle_query(user_query)
        else:
            st.warning("Please enter a question.")

    # Display Chat History
    if st.session_state.chat_history:
        st.subheader("Chat History")
        for chat in st.session_state.chat_history:
            if chat["role"] == "user":
                st.markdown(f"**You:** {chat['content']}")
            else:
                st.markdown(f"**Assistant:** {chat['content']}")
