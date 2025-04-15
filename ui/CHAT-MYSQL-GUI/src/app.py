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

# Function to validate SQL queries (syntactic check)
def validate_query(query):
    """Validate that the SQL query is safe and executable."""
    allowed_keywords = ["SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"]
    query_upper = query.upper()
    if not query_upper.startswith("SELECT"):
        return False
    return any(kw in query_upper for kw in allowed_keywords)

# Function to check query against schema (semantic validation)
def validate_query_semantics(query, question, schema):
    """Check if the query aligns with the schema and user intent."""
    try:
        query_lower = query.lower()
        question_lower = question.lower()
        
        # Check for date-specific queries
        if "on" in question_lower and "april 14, 2025" in question_lower:
            if "where" not in query_lower or "2025-04-14" not in query_lower:
                return False
        
        # Check for employee transaction queries
        if "employee" in question_lower and "transaction" in question_lower:
            if "employees" not in query_lower or "invoices" not in query_lower or "join" not in query_lower:
                return False
        
        # Check for revenue/profit queries
        if any(kw in question_lower for kw in ["revenue", "profit", "base cost", "total invoice"]):
            if "sum" not in query_lower or "total" not in query_lower:
                return False
        
        # Check for invoice details
        if "invoice" in question_lower and "details" in question_lower:
            if "invoices" not in query_lower:
                return False
        
        # Check for employee login queries
        if "employee" in question_lower and "log" in question_lower:
            if "user_logins" not in query_lower or "employees" not in query_lower:
                return False
        
        # Avoid redundant joins
        join_count = query_lower.count("join")
        required_tables = []
        table_mappings = {
            "sales": ["invoices", "invoice_details"],
            "revenue": ["invoices", "invoice_details"],
            "products": ["products"],
            "inventory": ["products", "inventory_logs"],
            "employee": ["employees", "user_logins"],
            "category": ["categories"],
            "best-selling": ["invoices", "invoice_details", "products"],
            "reorder": ["products"],
            "profit": ["invoices", "invoice_details", "products"]
        }
        for keyword, tables in table_mappings.items():
            if keyword in question_lower:
                required_tables.extend(tables)
        if join_count > len(set(required_tables)) * 2:
            return False
        
        return True
    except Exception:
        return False

# Function to simulate query execution
def simulate_query_execution(query, question, schema):
    """Simulate query execution with schema validation first."""
    if not validate_query_semantics(query, question, schema):
        return False
    
    try:
        # Use EXPLAIN to check query validity
        explain_query = f"EXPLAIN {query}"
        data = fetch_data_from_api("execute_query", {"query": explain_query})
        if data is None:
            return False
        
        # Test with LIMIT 1
        test_query = query.split(";")[0] + " LIMIT 1;"
        data = fetch_data_from_api("execute_query", {"query": test_query})
        return data is not None and (not isinstance(data, list) or len(data) > 0)
    except Exception:
        return False

# Function to rerank query proposals
def rerank_proposals(proposals, question, schema):
    """Rerank query proposals with semantic validation."""
    rerank_template = """
    Rank these SQL queries based on relevance to the question and schema:
    Question: {question}
    Schema: {schema}
    Queries:
    {queries}
    Guidelines:
    - Ensure queries reference correct tables and columns for the intent.
    - Prioritize queries with appropriate aggregations (e.g., SUM for revenue).
    - Penalize queries missing key conditions (e.g., WHERE for dates).
    Provide the best query.
    """
    rerank_prompt = ChatPromptTemplate.from_template(rerank_template)
    chain = (
        rerank_prompt
        | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )
    
    valid_proposals = [
        p for p in proposals
        if validate_query_semantics(p, question, schema)
    ]
    
    if not valid_proposals:
        valid_proposals = proposals
    
    queries_str = "\n".join([f"{i+1}. {p}" for i, p in enumerate(valid_proposals)])
    best_query = chain.invoke({
        "question": question,
        "schema": schema,
        "queries": queries_str
    })
    return best_query.strip()

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

# Function to log user feedback
def log_user_feedback(query, response, feedback):
    """Log user feedback for analysis."""
    feedback_data = {
        "query": query,
        "response": response,
        "feedback": feedback,
        "timestamp": datetime.datetime.now().isoformat()
    }
    try:
        with open("feedback_log.json", "a") as f:
            json.dump(feedback_data, f)
            f.write("\n")
    except Exception as e:
        st.warning(f"Failed to log feedback: {str(e)}")

# Function for fallback queries
def get_fallback_response(question):
    """Generate a fallback response for ambiguous or failed queries."""
    question_lower = question.lower()
    if "employee" in question_lower and "transaction" in question_lower:
        return "Try 'employee with the most transactions on April 14, 2025'.", None
    if any(kw in question_lower for kw in ["revenue", "profit", "base cost", "total invoice"]):
        return "Try 'total revenue and profit for April 14, 2025'.", None
    if "invoice" in question_lower:
        return "Try 'invoices on April 14, 2025'.", None
    if "employee" in question_lower and "log" in question_lower:
        return "Try 'employees logged in on April 14, 2025'.", None
    return "Your query is unclear. Try a predefined query from the sidebar, like 'daily sales trend'.", None

# Function to define SQL chain for query generation
def get_sql_chain():
    """Create a chain to generate SQL queries with execution-guided decoding, reranking, and caching."""
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
    Given the schema and user query, produce a valid SQL query.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use explicit INNER JOINs for data integrity.
    - Group by unique IDs (e.g., product_id, invoice_id) with names.
    - For specific dates (e.g., "April 14, 2025"), use WHERE order_date = '2025-04-14'.
    - For employee transactions, join employees and invoices on employee_id.
    - For revenue, use SUM(i.total); for profit, use SUM(i.total - id.quantity * p.purchase_price).
    - For profit margin, calculate (profit / revenue * 100).
    - Exclude invalid invoices with WHERE i.total > 0.
    - Use DECIMAL for monetary fields, INTEGER for quantities.
    - Return only the SQL query, no explanations.

    **Guidelines:**
    - "Sales" means SUM(id.quantity) unless revenue is specified.
    - Use 'CURDATE()' for today, 'DATE_SUB(CURDATE(), INTERVAL X)' for periods.
    - For discounts, use i.discount.
    - ROUND monetary values to 2 decimals.
    - Verify category counts vs. product counts.

    **User Query:** {question}
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

    @st.cache_data(show_spinner=False)
    def cached_query(_question, _schema, _chat_summary, _current_sg_date, _current_sg_datetime):
        """Cache SQL query results for common questions."""
        proposals = proposal_chain.invoke({
            "question": _question,
            "schema": _schema,
            "chat_summary": _chat_summary,
            "current_sg_date": _current_sg_date,
            "current_sg_datetime": _current_sg_datetime
        })
        return proposals

    def filter_valid_proposals(proposals, question, schema):
        """Filter proposals using execution-guided decoding and semantic validation."""
        valid_proposals = []
        for proposal in proposals.values():
            cleaned_query = proposal.split(";")[0] + ";"
            if (validate_query(cleaned_query) and 
                validate_query_semantics(cleaned_query, question, schema) and 
                simulate_query_execution(cleaned_query, question, schema)):
                valid_proposals.append(cleaned_query)
        return valid_proposals if valid_proposals else [list(proposals.values())[0]]

    aggregator_template = """
    Synthesize the best SQL query from these proposals:
    {valid_proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return ONLY the final SQL query without explanations or formatting.
    The query must:
    1. Start with SELECT
    2. Use explicit INNER JOIN syntax
    3. Include WHERE i.total > 0 for invoice queries
    4. Group by unique IDs (e.g., product_id) alongside names
    5. Contain no comments or markdown
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
            proposals=lambda x: cached_query(
                x["question"],
                schema,
                x["chat_summary"],
                x["current_sg_date"],
                x["current_sg_datetime"]
            ),
            question=lambda x: x["question"],
            chat_history=lambda x: x["chat_history"],
        )
        | RunnablePassthrough.assign(
            valid_proposals=lambda x: filter_valid_proposals(x["proposals"], x["question"], x["schema"])
        )
        | RunnablePassthrough.assign(
            best_query=lambda x: rerank_proposals(x["valid_proposals"], x["question"], x["schema"])
        )
        | aggregator_prompt
        | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
        | StrOutputParser()
    )

# Function to generate AI response
def get_response(user_query: str, chat_history: list):
    """Generate a natural language response and fetch data based on the user's query."""
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve", "overview", "profit", "base cost"
    ]

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

        if not validate_query(query):
            log_data = {"query": user_query, "generated_sql": query, "error": "Syntactic validation failed", "timestamp": datetime.datetime.now().isoformat()}
            with open("query_log.json", "a") as f:
                json.dump(log_data, f)
                f.write("\n")
            return get_fallback_response(user_query)
        
        if not validate_query_semantics(query, user_query, schema):
            log_data = {"query": user_query, "generated_sql": query, "error": "Semantic validation failed", "timestamp": datetime.datetime.now().isoformat()}
            with open("query_log.json", "a") as f:
                json.dump(log_data, f)
                f.write("\n")
            return get_fallback_response(user_query)

        if any(kw in user_query.lower() for kw in ["revenue", "sales", "profit", "inventory", "overview"]):
            fetch_data_from_api.clear()
        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            log_data = {"query": user_query, "generated_sql": query, "error": "No data returned", "timestamp": datetime.datetime.now().isoformat()}
            with open("query_log.json", "a") as f:
                json.dump(log_data, f)
                f.write("\n")
            return get_fallback_response(user_query)

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        1. If results are empty, state: "No data found for this query. This could be due to no records matching the criteria."
        2. For quantities (e.g., total_sold, total_invoices), use 'units', 'items', or 'records'.
        3. For monetary values, use peso sign (₱) and format to 2 decimal places.
        4. Highlight key insights (e.g., top item, highest value).
        5. Use markdown: **bold** for emphasis, - for lists.
        6. If total_discount = 0, note: "No discounts recorded, which is unusual for this period."
        7. If total_categories ≥ total_products, caution: "High category count relative to products; verify category assignments."
        8. Keep concise, under 200 words.
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
        if unique_categories <= 6 and ("percentage" in query_lower or "breakdown" in query_lower):
            return "pie", (categorical_columns[0], numerical_columns[0])
        else:
            return "bar", (categorical_columns[0], numerical_columns[0])
    return None, None

# Function to handle user queries
def handle_query(query: str):
    """Process a user's query, update chat history, and display response with feedback option."""
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
        feedback_key = f"feedback_{len(st.session_state.chat_history)}"
        feedback = st.radio(
            "Was this response helpful?",
            options=["Yes", "No"],
            key=feedback_key,
            horizontal=True
        )
        if feedback == "No":
            feedback_text = st.text_input("Please explain what was wrong:", key=f"text_{feedback_key}")
            if st.button("Submit Feedback", key=f"submit_{feedback_key}"):
                log_user_feedback(query, natural_response, feedback_text)
                st.success("Thank you for your feedback!")
        
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            for col in df.columns:
                if "date" in col.lower():
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                if any(mon in col.lower() for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "discount", "revenue", "profit", "base_cost"]):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                elif col.lower() in ["total_sold", "transaction_count", "login_count", "product_count", "total_invoices"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            chart_type, columns = determine_chart_type(query, df)
            if chart_type:
                with st.spinner("Generating chart..."):
                    st.markdown(f"### {chart_type.capitalize()} Chart")
                    fig, ax = plt.subplots()
                    if chart_type == 'bar':
                        df.plot(kind='bar', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} by {columns[0]}")
                        ax.set_xlabel(columns[0])
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'line':
                        df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                        ax.set_title(f"{columns[1].replace(' (₱)', '')} Over Time")
                        ax.set_xlabel("Date")
                        ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                    elif chart_type == 'pie':
                        ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                        ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '')}")
                    st.pyplot(fig)
                    st.download_button("Download Data", df.to_csv(index=False), "data.csv")
            if len(df) > 0 or len(df.columns) > 1:
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

                with st.expander("📈 Sales Performance"):
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
                        "What are the current stock levels for all products?",
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
                        "What are today’s login and logout times for all employees?",
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
                        "Which invoices had the highest discounts this month?"
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
                        "Show me this week’s inventory changes for all products.",
                        "What are the most recent inventory adjustments?"
                    ]
                    for q in ops_queries:
                        if st.button(q, key=f"ops_{q}"):
                            handle_query(q)

                with st.expander("🔍 Miscellaneous Insights"):
                    misc_queries = [
                        "What are the profit margins for all products?",
                        "What are the total units sold for all products this month?",
                        "What is the sales history for all products this year?",
                        "Which product category has the highest sales this year?",
                        "What is the average price of products in each category?",
                        "Which products should we reorder soon?",
                        "How many products are within 10% of their reorder level?"
                    ]
                    for q in misc_queries:
                        if st.button(q, key=f"misc_{q}"):
                            handle_query(q)

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
