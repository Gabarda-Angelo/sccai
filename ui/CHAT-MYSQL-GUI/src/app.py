import streamlit as st
import pandas as pd
import json
import datetime
import pytz
import requests
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
import plotly.express as px

# Initialize session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Streamlit app layout
st.title("SCC School Store Analytics")
st.write("Ask about sales, inventory, or other store metrics, and I'll provide insights with charts where relevant.")

# Sidebar for settings
with st.sidebar:
    st.header("Settings")
    st.write("Adjust the API key or clear chat history.")
    groq_api_key = st.text_input("GROQ API Key", type="password", value=st.secrets.get("GROQ_API_KEY", ""))
    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

# Function to validate SQL query
def validate_query(query: str) -> bool:
    """Validate if the query is a SELECT statement and safe to execute."""
    query = query.strip().upper()
    return query.startswith("SELECT") and not any(keyword in query for keyword in ["DELETE", "UPDATE", "INSERT", "DROP"])

# Function to fetch data from API
def fetch_data_from_api(endpoint: str, payload: dict):
    """Fetch data from the API endpoint."""
    try:
        response = requests.post(f"https://your-api-endpoint/{endpoint}", json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        st.error(f"API error: {str(e)}")
        return None

# Function to generate SQL chain
def get_sql_chain():
    """Create a chain to generate SQL queries based on user input."""
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

    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - When the user mentions "today," use the current date in Singapore, e.g., WHERE order_date = '{current_sg_date}'.
    - Use explicit JOIN syntax with table aliases for clarity (e.g., invoices i JOIN invoice_details id ON i.invoice_id = id.invoice_id).
    - For quantities, use invoice_details.quantity; for prices, use invoice_details.unit_price or products.sale_price.
    - For totals, calculate as invoice_details.total_price (quantity * unit_price) or invoices.total.
    - Use aggregate functions (SUM, COUNT) for summarizations, ensuring no double-counting across joins.
    - Filter data based on conditions mentioned, validating for NULL or negative values.
    - Order results if the question suggests a specific order (e.g., ORDER BY total_price DESC).
    - If the question involves revenue or sales, prioritize invoice_details.total_price for accuracy.
    - For overview statistics (e.g., total invoices, revenue, profit, top product), align with:
      - Total invoices: COUNT(i.invoice_id)
      - Average sales: ROUND(AVG(i.total), 2)
      - Total revenue: SUM(i.total)
      - Base cost: SUM(id.quantity * p.purchase_price)
      - Profit: SUM(i.total) - SUM(id.quantity * p.purchase_price)
      - Profit margin: ((SUM(i.total) - SUM(id.quantity * p.purchase_price)) / SUM(i.total)) * 100
      - Top product: Product with highest SUM(id.quantity)
      - Low stock: COUNT products where stock <= reorder_level
    - Avoid referencing non-existent tables or columns.
    - Provide only the SQL query as output, without explanations.
    - When no date period is mentioned, include all records from the earliest date.
    - Ensure calculations are correct:
      - Total revenue: SUM(invoice_details.total_price)
      - Units sold: SUM(invoice_details.quantity)
      - Profit: SUM(invoice_details.total_price - (invoice_details.quantity * products.purchase_price))
    - Handle edge cases (e.g., no sales, zero stock) by returning meaningful results.

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
        **{
            f"proposal_{i}": prompt | llm | StrOutputParser()
            for i, llm in enumerate(proposal_llms)
        }
    )

    aggregator_template = """
    Synthesize the best SQL query from these proposals:
    {proposals}

    **Original Question:** {question}
    **Schema:** {schema}

    Return ONLY the final SQL query without any explanations or formatting.
    The query must:
    1. Start with SELECT
    2. Use explicit JOIN syntax with table aliases
    3. Correctly calculate quantities (invoice_details.quantity) and totals (invoice_details.total_price)
    4. Validate prices using invoice_details.unit_price or products.sale_price
    5. Contain no comments or markdown
    6. Avoid double-counting in aggregations
    7. Align with overview stats logic for invoices, revenue, cost, profit, and top product
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

# Function to generate natural language response
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
        "provide", "get", "fetch", "retrieve", "overview", "profit", "cost", "margin"
    ]

    if any(keyword in user_query.lower() for keyword in time_keywords) and not any(keyword in user_query.lower() for keyword in data_keywords):
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.datetime.now(singapore_tz)
        natural_response = f"The current date and time in Singapore is {current_time.strftime('%Y-%m-%d %H:%M:%S')}."
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
            return "Failed to generate a valid database query. Please try again.", None

        data = fetch_data_from_api("execute_query", {"query": query})
        if data is None:
            return "Couldn't retrieve data. Please try again or rephrase your question.", None

        response_template = """
        Generate a natural language response based on:
        - **Question:** {question}
        - **Results:** {response}
        - **History:** {chat_history}

        **Guidelines:**
        1. If results are empty, state: "No data found. This could be due to no records for the specified period or item. Try a broader time frame or different product."
        2. Clearly distinguish quantities (e.g., "X units sold") from monetary values (e.g., "total revenue of ₱Y pesos").
        3. Highlight key insights (e.g., highest/lowest quantities, largest revenue contributors).
        4. Use markdown: **bold** for emphasis, - for lists.
        5. Include the peso sign (₱) and the word "pesos" only for monetary values (e.g., ₱100 pesos).
        6. For quantities, specify "units" explicitly (e.g., "100 units").
        7. For overview queries, include metrics like:
           - Total invoices: Number of transactions
           - Average sales value: ₱X pesos per invoice
           - Total revenue: ₱Y pesos
           - Profit: ₱Z pesos (revenue - base cost)
           - Profit margin: X%
           - Top product: Product name with highest units sold
           - Low stock: Number of products needing restock
        8. Ensure calculations are accurate (e.g., total revenue = sum of total_price, units sold = sum of quantity).
        9. Keep concise, under 200 words.
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

# Function to determine chart type
def determine_chart_type(query, df):
    """Determine the appropriate chart type based on query and data."""
    if df.empty or len(df.columns) < 2:
        return None, None

    columns = df.columns.tolist()
    query_lower = query.lower()

    date_columns = [col for col in columns if "date" in col.lower() or pd.api.types.is_datetime64_any_dtype(df[col])]
    numerical_columns = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_columns = df.select_dtypes(include=["object"]).columns.tolist()

    # Prioritize quantity or total_price for sales-related queries
    if "quantity" in query_lower or "sold" in query_lower:
        numerical_cols = [col for col in numerical_columns if "quantity" in col.lower()]
    elif any(kw in query_lower for kw in ["revenue", "total", "price", "profit", "cost", "margin"]):
        numerical_cols = [col for col in numerical_columns if any(kw in col.lower() for kw in ["total", "price", "revenue", "profit", "cost", "margin"])]
    else:
        numerical_cols = numerical_columns

    if date_columns and numerical_cols:
        return "line", (date_columns[0], numerical_cols[0])
    elif categorical_columns and numerical_cols:
        unique_categories = len(df[categorical_columns[0]].unique())
        if unique_categories <= 6 and "percentage" in query_lower:
            return "pie", (categorical_columns[0], numerical_cols[0])
        else:
            return "bar", (categorical_columns[0], numerical_cols[0])
    return None, None

# Main app logic
def main():
    """Main function to handle user queries and display results."""
    user_query = st.text_input("Enter your question:", placeholder="E.g., How many units of SCC Shirt were sold today?")
    
    if user_query:
        with st.spinner("Processing your query..."):
            natural_response, data = get_response(user_query, st.session_state.messages)
            
            # Display natural language response
            st.markdown("### Response")
            st.markdown(natural_response)
            
            # Display data table if available
            if data:
                df = pd.DataFrame(data)
                st.markdown("### Data")
                st.dataframe(df)
                
                # Generate and display chart
                chart_type, axes = determine_chart_type(user_query, df)
                if chart_type:
                    st.markdown("### Visualization")
                    if chart_type == "bar":
                        st.bar_chart(df.set_index(axes[0])[axes[1]])
                    elif chart_type == "line":
                        st.line_chart(df.set_index(axes[0])[axes[1]])
                    elif chart_type == "pie":
                        st.plotly_chart(px.pie(df, names=axes[0], values=axes[1]))
            
            # Update chat history
            st.session_state.messages.append({"role": "user", "content": user_query})
            st.session_state.messages.append({"role": "assistant", "content": natural_response})

    # Display chat history
    st.markdown("### Chat History")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

if __name__ == "__main__":
    main()
