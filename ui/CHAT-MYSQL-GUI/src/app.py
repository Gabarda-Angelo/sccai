import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import logging
from datetime import datetime
from langchain_groq import ChatGroq
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from sentence_transformers import SentenceTransformer
from faiss import IndexFlatL2
import numpy as np
from functools import lru_cache
import asyncio
import json
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
import re
from retry import retry

# Initialize logging
logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize vector store for RAG
@lru_cache(maxsize=1)
def initialize_vector_store():
    try:
        # Fetch product and category names via API
        response = fetch_data_from_api(
            {"query": "SELECT product_name FROM products UNION SELECT category_name FROM categories"}
        )
        if not response or 'data' not in response:
            logger.error("Failed to fetch items for vector store")
            return None
        items = [row['product_name'] for row in response['data']]

        model = SentenceTransformer('all-MiniLM-L6-v2')
        embeddings = model.encode(items)
        dimension = embeddings.shape[1]
        index = IndexFlatL2(dimension)
        index.add(embeddings)
        logger.info("Vector store initialized")
        return model, index, items
    except Exception as e:
        logger.error(f"Vector store initialization failed: {e}")
        return None

# Query classifier
@st.cache_resource
def init_query_classifier():
    try:
        queries = [
            ("What are the top selling products?", "sales"),
            ("Show inventory levels", "inventory"),
            ("Who are the best employees?", "employee"),
            ("What is the profit margin?", "financial"),
            ("How many transactions today?", "operations"),
            ("What time is it?", "conversational")
        ]
        X, y = zip(*queries)
        vectorizer = TfidfVectorizer()
        X_vectorized = vectorizer.fit_transform(X)
        classifier = MultinomialNB()
        classifier.fit(X_vectorized, y)
        logger.info("Query classifier initialized")
        return vectorizer, classifier
    except Exception as e:
        logger.error(f"Query classifier initialization failed: {e}")
        return None, None

# SQL query validation
def validate_sql_query(query):
    query = query.lower().strip()
    if not query.startswith("select"):
        logger.warning(f"Invalid SQL query: {query}")
        return False
    forbidden_keywords = ["insert", "update", "delete", "drop", "alter", "truncate"]
    if any(keyword in query for keyword in forbidden_keywords):
        logger.warning(f"SQL query contains forbidden keywords: {query}")
        return False
    valid_tables = [
        "categories", "employees", "inventory_logs", "invoices", "invoice_details",
        "products", "user_logins", "discount_logs", "void_logs", "admin_logs",
        "sync_log", "action_requests", "admin_action_logs"
    ]
    tables_in_query = re.findall(r'\bfrom\s+([a-z_]+)\b', query)
    for table in tables_in_query:
        if table not in valid_tables:
            logger.warning(f"Query references invalid table: {table}")
            return False
    return True

# Initialize LLMs
@st.cache_resource
def init_llms():
    try:
        llm1 = ChatGroq(model_name="llama3-70b-8192", api_key=st.secrets["GROQ_API_KEY"])
        llm2 = ChatGroq(model_name="gemma2-9b-it", api_key=st.secrets["GROQ_API_KEY"])
        llm3 = ChatGroq(model_name="mixtral-8x7b-32768", api_key=st.secrets["GROQ_API_KEY"])
        logger.info("LLMs initialized")
        return llm1, llm2, llm3
    except Exception as e:
        logger.error(f"LLM initialization failed: {e}")
        return None, None, None

# SQL chain for domain-specific queries
def get_sql_chain(llm, domain):
    schema = """
    Tables:
    - categories (category_id, category_name, created_at)
    - employees (employee_id, employee_name, role, hire_date, email, created_at)
    - inventory_logs (log_id, product_id, quantity_change, log_date, reason)
    - invoices (invoice_id, employee_id, invoice_date, total_amount)
    - invoice_details (invoice_id, product_id, quantity, unit_price)
    - products (product_id, product_name, category_id, unit_price, stock_quantity, created_at)
    - user_logins (login_id, employee_id, login_time, logout_time)
    - discount_logs (discount_id, invoice_id, discount_amount, discount_date)
    - void_logs (void_id, invoice_id, void_date, reason)
    - admin_logs (log_id, employee_id, action, action_date)
    - action_requests (request_id, employee_id, request_type, request_details, status, request_date)
    - admin_action_logs (action_id, employee_id, request_id, action_type, action_details, action_date)
    - sync_log (sync_id, sync_date, status, details)
    """
    prompt_template = PromptTemplate(
        input_variables=["query", "schema"],
        template=f"""
        You are a SQL expert for a school store database. Given a user query and the database schema, generate a valid SELECT SQL query for the {domain} domain. Ensure the query is safe, accurate, and uses proper joins. Return only the SQL query, no explanations.

        Schema:
        {{schema}}

        Query:
        {{query}}
        """
    )
    return LLMChain(llm=llm, prompt=prompt_template)

# Aggregate SQL queries from multiple LLMs
def aggregate_sql_queries(queries):
    valid_queries = [q for q in queries if validate_sql_query(q)]
    if not valid_queries:
        logger.warning("No valid SQL queries generated")
        return None
    return max(valid_queries, key=lambda q: len(re.findall(r'\bjoin\b', q.lower())))

# Multi-hop query planning
async def plan_multi_hop_query(query, domain, llms):
    try:
        steps = []
        current_query = query
        for i in range(3):  # Max 3 hops
            sql_chains = [get_sql_chain(llm, domain) for llm in llms]
            query_tasks = [chain.run({"query": current_query, "schema": "...schema..."}) for chain in sql_chains]
            queries = await asyncio.gather(*query_tasks)
            sql_query = aggregate_sql_queries(queries)
            if not sql_query:
                break
            steps.append(sql_query)
            if "group by" in sql_query.lower() or "order by" in sql_query.lower():
                break
            current_query = f"Summarize the results of: {sql_query}"
        return steps
    except Exception as e:
        logger.error(f"Multi-hop query planning failed: {e}")
        return []

# Execute SQL query via API
@st.cache_data(ttl=300)
def execute_sql_query(_query):
    try:
        if st.secrets["DEBUG_SQL"] == "true":
            logger.info(f"Executing SQL query: {_query}")
        response = fetch_data_from_api({"query": _query})
        if not response or 'data' not in response:
            logger.error(f"API query failed: {response}")
            return None
        data = response['data']
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        logger.info(f"SQL query executed successfully: {_query}")
        return df
    except Exception as e:
        logger.error(f"SQL execution failed: {e}")
        return None

# Generate visualization
def generate_visualization(df, query):
    try:
        if df.empty:
            return None
        chart_type = "table"
        if len(df.columns) >= 2:
            cat_cols = df.select_dtypes(include=['object', 'category']).columns
            num_cols = df.select_dtypes(include=['int64', 'float64']).columns
            if len(cat_cols) >= 1 and len(num_cols) >= 1:
                chart_type = "bar"
            elif len(num_cols) >= 2:
                chart_type = "scatter"
            elif len(cat_cols) >= 2:
                chart_type = "heatmap"
        plt.figure(figsize=(10, 6))
        if chart_type == "bar":
            sns.barplot(x=df[num_cols[0]], y=df[cat_cols[0]], palette="viridis")
            plt.title(f"Bar Chart for {query}")
        elif chart_type == "scatter":
            sns.scatterplot(x=df[num_cols[0]], y=df[num_cols[1]], palette="viridis")
            plt.title(f"Scatter Plot for {query}")
        elif chart_type == "heatmap":
            pivot = df.pivot_table(index=cat_cols[0], columns=cat_cols[1], aggfunc='size', fill_value=0)
            sns.heatmap(pivot, cmap="viridis", annot=True)
            plt.title(f"Heatmap for {query}")
        plt.tight_layout()
        st.pyplot(plt)
        logger.info(f"Visualization generated: {chart_type}")
    except Exception as e:
        logger.error(f"Visualization failed: {e}")
        return None

# Fetch data from API with retry
@retry(tries=3, delay=1, backoff=2)
def fetch_data_from_api(params):
    try:
        headers = {"Authorization": f"Bearer {st.secrets['API_KEY']}"}
        response = requests.post(st.secrets["API_URL"], json=params, headers=headers, timeout=15)
        response.raise_for_status()
        if st.secrets["DEBUG_API"] == "true":
            logger.info(f"API response: {response.text}")
        return response.json()
    except requests.RequestException as e:
        logger.error(f"API call failed: {e}")
        return None

# Main Streamlit app
def main():
    st.set_page_config(page_title="AcaSquad AI", layout="wide")
    st.title("AcaSquad AI - School Store Insights")

    if st.secrets["DEBUG_MODE"] == "true":
        st.sidebar.write("Debug Mode: Enabled")

    # Authentication
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.role = None
    if not st.session_state.authenticated:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            auth_data = fetch_data_from_api({"action": "auth", "username": username, "password": password})
            if auth_data and auth_data.get("status") == "success":
                st.session_state.authenticated = True
                st.session_state.role = auth_data.get("role")
                st.success("Logged in successfully!")
            else:
                st.error("Invalid credentials")
        return

    # Only Owners and Admins can access
    if st.session_state.role not in ["Owner", "Admin"]:
        st.error("Access denied. Please log in as Owner or Admin.")
        return

    # Sidebar with predefined queries
    st.sidebar.header("Quick Insights")
    predefined_queries = {
        "Top 5 Products by Sales": "SELECT p.product_name, SUM(id.quantity) as total_sold FROM products p JOIN invoice_details id ON p.product_id = id.product_id GROUP BY p.product_id ORDER BY total_sold DESC LIMIT 5",
        "Revenue This Month": "SELECT SUM(total_amount) as revenue FROM invoices WHERE MONTH(invoice_date) = MONTH(CURRENT_DATE()) AND YEAR(invoice_date) = YEAR(CURRENT_DATE())",
        "Low Stock Products": "SELECT product_name, stock_quantity FROM products WHERE stock_quantity < 10"
    }
    selected_query = st.sidebar.selectbox("Select a predefined query", list(predefined_queries.keys()))
    if st.sidebar.button("Run Predefined Query"):
        st.session_state.user_query = selected_query

    # Main query input
    user_query = st.text_input("Ask a question about the store:", value=st.session_state.get("user_query", ""))
    if st.button("Submit Query") or user_query != st.session_state.get("user_query", ""):
        st.session_state.user_query = user_query
        if not user_query:
            st.warning("Please enter a query.")
            return

        # Initialize components
        vectorizer, classifier = init_query_classifier()
        model, index, items = initialize_vector_store()
        llms = init_llms()

        # Classify query
        if vectorizer and classifier:
            query_vector = vectorizer.transform([user_query])
            domain = classifier.predict(query_vector)[0]
        else:
            domain = "misc"

        # Handle conversational queries
        if domain == "conversational":
            if "time" in user_query.lower():
                st.write(f"Current time (SGT): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                st.write("This is a conversational query. Please ask a data-related question.")
            return

        # Fuzzy matching for products/categories
        if model and index:
            query_embedding = model.encode([user_query])[0]
            _, indices = index.search(np.array([query_embedding]), k=1)
            matched_item = items[indices[0][0]]
            user_query = user_query.replace(matched_item, f"'{matched_item}'")

        # Handle predefined query
        if user_query in predefined_queries:
            sql_query = predefined_queries[user_query]
        else:
            # Generate SQL query
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            sql_queries = loop.run_until_complete(plan_multi_hop_query(user_query, domain, llms))
            sql_query = sql_queries[-1] if sql_queries else None

        if not sql_query or not validate_sql_query(sql_query):
            st.error("Could not generate a valid SQL query. Please try rephrasing your question.")
            return

        # Execute query
        df = execute_sql_query(sql_query)
        if df is None or df.empty:
            st.warning("No data found for your query.")
            return

        # Generate response
        response_prompt = PromptTemplate(
            input_variables=["query", "data"],
            template="""
            Summarize the results for the query: {query}
            Data: {data}
            Keep the response concise (<200 words), use markdown, and include units (₱ for money, % for percentages).
            """
        )
        response_chain = LLMChain(llm=llms[0], prompt=response_prompt)
        response = response_chain.run({"query": user_query, "data": df.to_string()})
        st.markdown(response)

        # Display results
        st.subheader("Results")
        st.dataframe(df)

        # Generate visualization
        generate_visualization(df, user_query)

        # Download option
        csv = df.to_csv(index=False)
        st.download_button("Download Results as CSV", csv, "results.csv", "text/csv")

if __name__ == "__main__":
    main()
