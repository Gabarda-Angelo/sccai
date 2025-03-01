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
            json={"email": email, "password": password},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success" and "data" in data:
            st.session_state.authenticated = True
            st.session_state.user = data["data"]
            st.success("Login Successful!")
            return True
        else:
            error_message = data.get("error", "Invalid credentials")
            st.error(f"Login failed: {error_message}")
    except requests.ConnectionError:
        st.error("Network error: Unable to connect to the authentication server.")
    except requests.Timeout:
        st.error("Request timed out. Please try again later.")
    except requests.HTTPError as e:
        st.error(f"HTTP error: {e.response.status_code} - {e.response.reason}")
    except json.JSONDecodeError:
        st.error("Invalid response from server. Please try again.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
    return False

# Function to fetch data from API
def fetch_data_from_api(action: str, params: dict = None) -> dict:
    """Fetch data from the API based on the specified action and parameters."""
    try:
        payload = {"action": action, "key": st.secrets["API_KEY"]}
        if params:
            if "query" in params:
                st.session_state.last_query = params["query"]
                params["query"] = quote(params["query"])
            payload.update(params)

        if st.secrets.get("DEBUG_API", "false").lower() == "true":
            st.sidebar.write(f"**Debug - API Request:** {payload}")

        response = requests.get(
            st.secrets["API_URL"],
            params=payload,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        if st.secrets.get("DEBUG_API", "false").lower() == "true":
            st.sidebar.write(f"**Debug - API Response:** {response.text}")

        if data.get("status") == "success":
            return data["data"]
        else:
            error_msg = data.get("error", "Unknown error")
            st.error(f"API Error: {error_msg}")
            return None
    except requests.ConnectionError:
        st.error("Network error: Unable to connect to the API.")
    except requests.Timeout:
        st.error("Request timed out. Please try again later.")
    except requests.HTTPError as e:
        st.error(f"HTTP error: {e.response.status_code} - {e.response.reason}")
    except json.JSONDecodeError:
        st.error("Invalid JSON response from API.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
    return None

# Enhanced function to define SQL chain for complex query generation
def get_sql_chain():
    """Create a chain to generate SQL queries, optimized for complex questions."""
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
    You are an expert SQL assistant retrieving data from the SCC School Store Database via an API.
    Based on the provided schema, generate a precise SQL query to fully answer the user's question, even if it requires complex operations.

    **Database Schema:**
    {schema}

    **Current date in Singapore:** {current_sg_date} (format: YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (format: YYYY-MM-DD HH:MM:SS)

    **Conversation History:** {chat_history}

    **Instructions:**
    - Use 'today' as '{current_sg_date}' (e.g., WHERE order_date = '{current_sg_date}').
    - Handle time ranges (e.g., last month, this year) with appropriate date conditions.
    - Use multiple JOINs to combine data from related tables as needed.
    - Leverage foreign key relationships (e.g., invoice_id, product_id, employee_id).
    - Apply aggregate functions (SUM, AVG, COUNT) for summarization questions.
    - Use subqueries or CTEs for complex filtering or calculations when necessary.
    - Order results logically if sorting is implied (e.g., 'top' → ORDER BY DESC).
    - Interpret ambiguous questions sensibly based on schema context.
    - Avoid referencing non-existent tables/columns.
    - Provide only the SQL query, no explanations.

    **User Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    models = [
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
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
    Synthesize the most accurate and complete SQL query from these proposals:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return ONLY the final SQL query with:
    1. SELECT statement
    2. Explicit JOIN syntax with table aliases
    3. No comments or markdown
    4. Correctness over simplicity for complex questions
    """

    aggregator_prompt = ChatPromptTemplate.from_template(aggregator_template)

    return (
        RunnablePassthrough.assign(
            schema=lambda _: schema,
            current_sg_date=lambda x: x["current_sg_date"],
            current_sg_datetime=lambda x: x["current_sg_datetime"],
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
    """Generate a natural language response and fetch data based on the user's query."""
    time_keywords = [
        "current time", "what time is it", "date and time",
        "today's date", "now", "time today", "date today"
    ]
    data_keywords = [
        "sales", "invoice", "details", "product", "category", "stock", "revenue",
        "order", "employee", "payment", "quantity", "price", "total", "subtotal",
        "discount", "due", "paid", "inventory", "log", "detail", "list", "show",
        "provide", "get", "fetch", "retrieve"
    ]

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

        if st.secrets.get("DEBUG_SQL", "false").lower() == "true":
            st.sidebar.write(f"**Debug - SQL Query:**\n```sql\n{query}\n```")

        if not query.lower().startswith("select"):
            st.error(f"Invalid query generated: {query}")
            return "Failed to generate valid database query. Please try again.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if not data:
            return "Couldn't retrieve data. Please try again or rephrase your question.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        1. If results are empty, suggest possible reasons or alternative queries.
        2. Be clear and concise.
        3. Highlight key numbers or trends.
        4. Use bullet points for lists.
        5. Mention any data limitations.
        6. Keep under 200 words.
        7. Use markdown formatting to enhance readability.
        8. Use the peso sign (₱) for monetary values.
        9. Avoid referencing non-existent data.
        10. For follow-up questions, reference the previous query and results.
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

# Enhanced function to determine chart type for data visualization
def determine_chart_type(query, df):
    """Determine the appropriate chart type based on query and data, prioritizing explicit user requests."""
    if df.empty:
        return None, None

    query_lower = query.lower()
    if 'bar chart' in query_lower:
        chart_type = 'bar'
    elif 'line chart' in query_lower:
        chart_type = 'line'
    elif 'pie chart' in query_lower:
        chart_type = 'pie'
    else:
        time_keywords = ['over time', 'trend', 'monthly', 'daily', 'weekly', 'yearly', 'history', 'progress']
        distribution_keywords = ['distribution', 'share', 'percentage', 'proportion', 'breakdown']
        ranking_keywords = ['top', 'best', 'most', 'ranking', 'leaderboard', 'highest', 'lowest']

        if any(word in query_lower for word in time_keywords):
            chart_type = 'line'
        elif any(word in query_lower for word in distribution_keywords):
            chart_type = 'pie'
        elif any(word in query_lower for word in ranking_keywords):
            chart_type = 'bar'
        else:
            chart_type = 'bar'  # Default

    # Convert columns to numeric where possible
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='ignore')

    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    date_columns = [
        col for col in df.columns
        if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])
    ]

    if chart_type in ['bar', 'pie']:
        if categorical_columns and numerical_columns:
            columns = (categorical_columns[0], numerical_columns[0])
        else:
            columns = None
    elif chart_type == 'line':
        if date_columns and numerical_columns:
            columns = (date_columns[0], numerical_columns[0])
        else:
            columns = None
    else:
        columns = None

    return chart_type, columns

# Enhanced function to display response with charts
def display_response(natural_response, data):
    """Display the AI's natural language response and associated data visualizations."""
    with st.chat_message("AI", avatar="dist/img/ai.png"):
        st.markdown(natural_response)
        if data and isinstance(data, list) and len(data) >= 1:
            df = pd.DataFrame(data)
            if st.secrets.get("DEBUG_API", "false").lower() == "true":
                st.sidebar.write(f"**Debug - DataFrame:**\n{df.head()}")

            # Rename monetary columns
            monetary_columns = [
                "subtotal", "total", "unit_price", "sale_price",
                "purchase_price", "total_price", "paid", "due"
            ]
            for col in monetary_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.rename(columns={col: f"{col} (₱)"}, inplace=True)

            chart_type, columns = determine_chart_type(st.session_state.last_query, df)
            if st.secrets.get("DEBUG_API", "false").lower() == "true":
                st.sidebar.write(f"**Debug - Chart Type:** {chart_type}, **Columns:** {columns}")

            if chart_type and columns:
                st.markdown(f"### {chart_type.capitalize()} Chart")
                try:
                    if chart_type == 'bar':
                        st.bar_chart(df.set_index(columns[0])[columns[1]].dropna())
                    elif chart_type == 'line':
                        st.line_chart(df.set_index(columns[0])[columns[1]].dropna())
                    elif chart_type == 'pie':
                        fig, ax = plt.subplots()
                        ax.pie(df[columns[1]].dropna(), labels=df[columns[0]], autopct='%1.1f%%')
                        st.pyplot(fig)
                except Exception as e:
                    st.error(f"Chart rendering failed: {str(e)}")
            else:
                st.warning("No suitable columns for chart visualization.")

            if len(df) > 100:
                st.write(f"Showing first 100 rows of {len(df)} total rows.")
                st.table(df.head(100))
            else:
                st.table(df)

# Function to handle user queries
def handle_query(query: str):
    """Process a user's query, update chat history, and display response."""
    st.session_state.chat_history.append(HumanMessage(content=query))
    with st.chat_message("Human", avatar="dist/img/Human.png"):
        st.markdown(query)

    with st.spinner("Processing your query... This may take a moment."):
        try:
            natural_response, data = get_response(query, st.session_state.chat_history)
        except Exception as e:
            natural_response = f"An error occurred: {str(e)}"
            data = None

    st.session_state.chat_history.append(AIMessage(content=natural_response))
    display_response(natural_response, data)

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

# Main application logic
def main():
    """Main function to run the AcaSquad AI application."""
    if not st.session_state.authenticated:
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

            if st.button("Clear Chat History"):
                st.session_state.chat_history = [
                    AIMessage(content="Hello! I will be your assistant. Ask me anything about your store.")
                ]
                st.rerun()

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