import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import json
import datetime
import pytz
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from langchain_community.vectorstores import FAISS
from langchain.embeddings import HuggingFaceEmbeddings
import requests
import os

# Streamlit page configuration
st.set_page_config(page_title="AcaSquad AI", page_icon="dist/img/ai.png", layout="wide")
st.markdown("""
    <style>
        .st-emotion-cache-13ln4jf { max-width: 100%; padding: 1rem; }
        .st-emotion-cache-1v0mbdj img { border-radius: 10px; }
        .stSpinner { margin: 0 auto; display: block; }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "user_role" not in st.session_state:
    st.session_state.user_role = "Cashier"  # Default role
if "vector_store" not in st.session_state:
    st.session_state.vector_store = None

# API connection
API_URL = "https://ltmptpysnd-bookstoreapi.hf.space/api/bookstoreapi.php"
API_TOKEN = st.secrets.get("API_TOKEN", "your_default_token")

@lru_cache(maxsize=100)
def fetch_data_from_api(action: str, payload: dict) -> list:
    """Fetch data from the API with caching."""
    try:
        headers = {"Authorization": f"Bearer {API_TOKEN}"}
        payload["action"] = action
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data", []) if data.get("success") else []
    except requests.RequestException as e:
        st.error(f"API error: {str(e)}")
        return []

def retrieve_metadata():
    """Retrieve current schema and recent sync_log entries."""
    schema_query = """
    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'ltmptpysnd_school_store_db';
    """
    sync_query = """
    SELECT table_name, record_id, action, timestamp
    FROM sync_log
    WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 DAY)
    ORDER BY timestamp DESC
    LIMIT 100;
    """
    schema_data = fetch_data_from_api("execute_query", {"query": schema_query})
    sync_data = fetch_data_from_api("execute_query", {"query": sync_query})
    return {
        "schema": schema_data if schema_data else [],
        "sync_log": sync_data if sync_data else []
    }

def initialize_vector_store():
    """Initialize a vector store for product names and categories."""
    products_query = "SELECT product_id, product_name FROM products;"
    categories_query = "SELECT category_id, category_name FROM categories;"
    products_data = fetch_data_from_api("execute_query", {"query": products_query})
    categories_data = fetch_data_from_api("execute_query", {"query": categories_query})
    
    if not products_data or not categories_data:
        return None
    
    texts = (
        [item["product_name"] for item in products_data] +
        [item["category_name"] for item in categories_data]
    )
    metadatas = (
        [{"type": "product", "id": item["product_id"]} for item in products_data] +
        [{"type": "category", "id": item["category_id"]} for item in categories_data]
    )
    
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    try:
        vector_store = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
        return vector_store
    except Exception as e:
        st.error(f"Vector store initialization failed: {str(e)}")
        return None

@lru_cache(maxsize=100)
def fuzzy_match_text(query: str) -> str:
    """Find closest matches for text in the vector store."""
    if not st.session_state.vector_store:
        st.session_state.vector_store = initialize_vector_store()
    if not st.session_state.vector_store:
        return json.dumps([])
    results = st.session_state.vector_store.similarity_search(query, k=3)
    return json.dumps([
        {"text": res.page_content, "type": res.metadata["type"], "id": res.metadata["id"]}
        for res in results
    ])

def validate_query(query: str) -> bool:
    """Validate SQL query for safety and correctness."""
    query_upper = query.upper().strip()
    if not query_upper.startswith("SELECT"):
        return False
    
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "EXECUTE"]
    if any(kw in query_upper for kw in forbidden_keywords):
        return False
    
    schema_query = """
    SELECT TABLE_NAME, COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'ltmptpysnd_school_store_db';
    """
    schema_data = fetch_data_from_api("execute_query", {"query": schema_query})
    valid_tables = set(item["TABLE_NAME"].lower() for item in schema_data)
    words = query_upper.replace(",", " ").replace(";", " ").split()
    used_tables = set(word.lower() for word in words if word.lower() in valid_tables)
    return len(used_tables) > 0

def restrict_query_by_role(query: str, user_role: str) -> bool:
    """Restrict queries based on user role."""
    query_upper = query.upper()
    restricted_tables = {
        "Cashier": ["employees", "user_logins"],
        "Admin": [],
        "Owner": []
    }
    for table in restricted_tables.get(user_role, []):
        if table.upper() in query_upper:
            return False
    return True

def log_query(query: str, user_id: str, success: bool):
    """Log query execution to sync_log."""
    log_query_sql = """
    INSERT INTO sync_log (table_name, record_id, action, timestamp)
    VALUES ('query_log', %s, %s, NOW());
    """
    action = "QUERY_SUCCESS" if success else "QUERY_FAILED"
    fetch_data_from_api("execute_query", {
        "query": log_query_sql,
        "params": [user_id, action]
    })

def classify_query(query: str) -> str:
    """Classify the query into a domain or list of domains."""
    classification_template = """
    Classify the query into one or more domains: sales, inventory, employee, financial, operations, misc.
    Query: {query}
    Return a single domain (e.g., 'sales') or a JSON list for multi-domain (e.g., ['sales', 'employee']).
    """
    prompt = ChatPromptTemplate.from_template(classification_template)
    chain = prompt | ChatGroq(model="llama3-8b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"]) | StrOutputParser()
    result = chain.invoke({"query": query})
    try:
        return json.loads(result) if result.startswith("[") else result
    except json.JSONDecodeError:
        return "misc"

def get_sql_chain(domain: str):
    """Create a chain to generate SQL queries with specialized agents."""
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

    domain_prompts = {
        "sales": """
        You are a Sales Agent specialized in sales data.
        Focus on invoices, invoice_details, products.
        Use SUM(id.quantity) for quantities, SUM(i.total) for revenue.
        Always include WHERE i.total > 0.
        Example: SELECT p.product_name, SUM(id.quantity) FROM invoice_details id INNER JOIN products p ON id.product_id = p.product_id INNER JOIN invoices i ON id.invoice_id = i.invoice_id WHERE i.total > 0 GROUP BY p.product_name;
        """,
        "inventory": """
        You are an Inventory Agent specialized in inventory queries.
        Focus on products, inventory_logs.
        Example: SELECT product_name, stock, reorder_level FROM products WHERE stock < reorder_level;
        """,
        "employee": """
        You are an Employee Agent specialized in employee queries.
        Focus on employees, user_logins.
        Example: SELECT CONCAT(e.first_name, ' ', e.last_name), COUNT(ul.log_id) FROM employees e INNER JOIN user_logins ul ON e.employee_id = ul.employee_id GROUP BY e.employee_id;
        """,
        "financial": """
        You are a Financial Agent specialized in financial queries.
        Focus on invoices, invoice_details.
        Example: SELECT SUM(i.total) FROM invoices i WHERE i.total > 0;
        """,
        "operations": """
        You are an Operations Agent specialized in store operations.
        Focus on invoices, user_logins.
        Example: SELECT HOUR(i.order_time), SUM(id.quantity) FROM invoices i INNER JOIN invoice_details id ON i.invoice_id = id.invoice_id WHERE i.total > 0 GROUP BY HOUR(i.order_time);
        """,
        "misc": """
        You are a Miscellaneous Agent for general queries.
        Example: SELECT product_name, (sale_price - purchase_price) / sale_price FROM products;
        """
    }

    template = """
    You are an AI assistant generating SQL queries for the SCC School Store Database.
    **Domain Role:** {domain_prompt}
    **Static Schema:** {static_schema}
    **Dynamic Metadata:** {dynamic_metadata}
    **Matched Entities:** {matched_entities}
    **Current date in Singapore:** {current_sg_date} (YYYY-MM-DD)
    **Current datetime in Singapore:** {current_sg_datetime} (YYYY-MM-DD HH:MM:SS)
    **Conversation Summary:** {chat_summary}

    **Instructions:**
    - Use dynamic metadata to verify table/column existence.
    - Incorporate matched entities (e.g., product IDs) for filtering.
    - Use explicit INNER JOINs.
    - Group by unique IDs alongside names.
    - Exclude invalid invoices with WHERE i.total > 0 for sales/financial.
    - Provide only the SQL query.

    **User Question:** {question}
    """

    prompt = ChatPromptTemplate.from_template(template)
    domain_model_map = {
        "sales": "llama3-70b-8192",
        "inventory": "gemma2-9b-it",
        "employee": "llama3-8b-8192",
        "financial": "llama3-70b-8192",
        "operations": "gemma2-9b-it",
        "misc": "llama3-70b-8192"
    }
    
    llm = ChatGroq(
        model=domain_model_map.get(domain, "llama3-70b-8192"),
        temperature=0,
        api_key=st.secrets["GROQ_API_KEY"]
    )

    def prepare_inputs(inputs):
        metadata = retrieve_metadata()
        matched_entities = json.loads(fuzzy_match_text(inputs["question"]))
        return {
            "static_schema": schema,
            "dynamic_metadata": json.dumps(metadata, indent=2),
            "matched_entities": json.dumps(matched_entities, indent=2),
            "current_sg_date": inputs["current_sg_date"],
            "current_sg_datetime": inputs["current_sg_datetime"],
            "chat_summary": " ".join([msg.content for msg in inputs["chat_history"][-3:]]),
            "question": inputs["question"],
            "domain_prompt": domain_prompts.get(domain, "General queries")
        }

    return (
        RunnablePassthrough()
        | prepare_inputs
        | prompt
        | llm
        | StrOutputParser()
    )
  	def recover_query(user_query: str, failed_query: str, chat_history: list, current_sg_date: str, current_sg_datetime: str) -> str:
      """Attempt to recover a failed query by regenerating it."""
      recovery_template = """
      The following SQL query failed: {failed_query}
      Error context: Likely invalid syntax, missing table, or incorrect join.
      Original question: {question}
      Schema: {schema}
      Current date: {current_sg_date}
      Current datetime: {current_sg_datetime}
      Regenerate a valid SQL query to answer the question.
      """
      prompt = ChatPromptTemplate.from_template(recovery_template)
      chain = (
          RunnablePassthrough.assign(
              schema=lambda _: """
              - categories: category_id, category_name, created_at
              - employees: employee_id, first_name, last_name, role, email, password_hash, created_at
              - inventory_logs: log_id, product_id, change_type, quantity, log_date, notes
              - invoices: invoice_id, employee_id, order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at
              - invoice_details: detail_id, invoice_id, product_id, quantity, unit_price, total_price
              - products: product_id, barcode, product_name, category_id, description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
              - user_logins: log_id, employee_id, login_time, logout_time, ip_address
              """
          )
          | prompt
          | ChatGroq(model="llama3-70b-8192", temperature=0.1, api_key=st.secrets["GROQ_API_KEY"])
          | StrOutputParser()
      )
      recovered_query = chain.invoke({
          "question": user_query,
          "failed_query": failed_query,
          "current_sg_date": current_sg_date,
          "current_sg_datetime": current_sg_datetime
      })
      return recovered_query.strip()
  
  def plan_multi_hop_query(query: str, schema: str) -> list:
      """Decompose a query into sequential steps."""
      planner_template = """
      You are an AI assistant decomposing a complex database query into sequential SQL steps.
      **Schema:** {schema}
      **Query:** {query}
  
      **Instructions:**
      - Break the query into logical steps, each requiring a single SQL query.
      - Ensure steps are ordered so later steps can use results from earlier ones.
      - For each step, provide:
        - A brief description (e.g., "Get top-selling products").
        - The SQL query to execute.
      - Return a JSON list of steps, e.g.:
        [
          {"description": "Get top-selling products", "sql": "SELECT ..."},
          {"description": "Get stock levels", "sql": "SELECT ..."}
        ]
      - If the query is simple, return one step.
      """
      prompt = ChatPromptTemplate.from_template(planner_template)
      chain = (
          prompt
          | ChatGroq(model="llama3-70b-8192", temperature=0, api_key=st.secrets["GROQ_API_KEY"])
          | StrOutputParser()
      )
      steps_json = chain.invoke({"query": query, "schema": schema})
      try:
          steps = json.loads(steps_json)
          return steps
      except json.JSONDecodeError:
          return [{"description": "Execute query directly", "sql": query}]
  
  def orchestrate_query(query: str, chat_history: list, current_sg_date: str, current_sg_datetime: str):
      """Orchestrate multi-domain queries by coordinating agents."""
      domains = classify_query(query)
      if isinstance(domains, str):
          domains = [domains]
      
      def run_agent(domain):
          sql_chain = get_sql_chain(domain)
          raw_query = sql_chain.invoke({
              "question": query,
              "chat_history": chat_history,
              "current_sg_date": current_sg_date,
              "current_sg_datetime": current_sg_datetime
          })
          query = raw_query.split(";")[0] + ";"
          query = query.replace("```sql", "").replace("```", "").strip()
          if validate_query(query) and restrict_query_by_role(query, st.session_state.user_role):
              data = fetch_data_from_api("execute_query", {"query": query})
              log_query(query, st.session_state.get("user_id", "unknown"), data is not None)
              return {"domain": domain, "data": data, "query": query}
          return None
      
      with ThreadPoolExecutor() as executor:
          results = list(filter(None, executor.map(run_agent, domains)))
      
      if not results:
          return "Failed to generate valid queries for any domain.", None
      
      aggregator_template = """
      Combine results from multiple agents:
      {results}
      **Original Question:** {question}
      Generate a natural language response summarizing the data.
      **Guidelines:**
      1. If results are empty, state: "No data found."
      2. For quantities, use 'units', 'items', or 'records'.
      3. For monetary values, use peso sign (₱) and format to 2 decimal places.
      4. Highlight key insights with **bold**.
      5. Use markdown: - for lists.
      6. If total_discount = 0, note: "No discounts recorded."
      7. If total_categories ≥ total_products, caution: "High category count."
      """
      prompt = ChatPromptTemplate.from_template(aggregator_template)
      chain = (
          prompt
          | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
          | StrOutputParser()
      )
      natural_response = chain.invoke({
          "question": query,
          "results": json.dumps(results, indent=2)
      })
      return natural_response, results[-1]["data"] if results else None
  
  @lru_cache(maxsize=50)
  def get_response(user_query: str, history_tuple: tuple) -> tuple:
      """Generate a natural language response and fetch data."""
      chat_history = [AIMessage(content=msg) if i % 2 else HumanMessage(content=msg) for i, msg in enumerate(history_tuple)]
      user_role = st.session_state.get("user_role", "Cashier")
      
      time_keywords = ["current time", "what time is it", "date and time", "today's date", "now", "time today", "date today"]
      data_keywords = ["sales", "invoice", "details", "product", "category", "stock", "revenue", "order", "employee", "payment", "quantity", "price", "total", "subtotal", "discount", "due", "paid", "inventory", "log", "detail", "list", "show", "provide", "get", "fetch", "retrieve", "overview"]
  
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
  
          # Check for multi-domain query
          domain = classify_query(user_query)
          if isinstance(domain, list) or " and " in user_query.lower():
              return orchestrate_query(user_query, chat_history, current_sg_date, current_sg_datetime)
          
          # Plan multi-hop query
          schema = """
          - categories: category_id, category_name, created_at
          - employees: employee_id, first_name, last_name, role, email, password_hash, created_at
          - inventory_logs: log_id, product_id, change_type, quantity, log_date, notes
          - invoices: invoice_id, employee_id, order_date, order_time, subtotal, discount, total, paid, due, payment_type, created_at
          - invoice_details: detail_id, invoice_id, product_id, quantity, unit_price, total_price
          - products: product_id, barcode, product_name, category_id, description, stock, reorder_level, purchase_price, sale_price, image, created_at, updated_at
          - user_logins: log_id, employee_id, login_time, logout_time, ip_address
          """
          steps = plan_multi_hop_query(user_query, schema)
  		        # Execute multi-hop steps
          all_data = []
          for step in steps:
              query = step["sql"].strip()
              if not validate_query(query) or not restrict_query_by_role(query, user_role):
                  recovery_query = recover_query(user_query, query, chat_history, current_sg_date, current_sg_datetime)
                  if recovery_query and validate_query(recovery_query) and restrict_query_by_role(recovery_query, user_role):
                      query = recovery_query
                  else:
                      log_query(query, st.session_state.get("user_id", "unknown"), False)
                      return f"Failed to generate a valid query for step: {step['description']}.", None
  
              if any(kw in user_query.lower() for kw in ["best-selling", "sales", "revenue", "inventory", "overview"]):
                  fetch_data_from_api.clear()
              data = fetch_data_from_api("execute_query", {"query": query})
              log_query(query, st.session_state.get("user_id", "unknown"), data is not None)
              if data is None:
                  return f"Couldn't retrieve data for step: {step['description']}.", None
              all_data.append({"step": step["description"], "data": data})
  
          # Aggregate results
          response_template = """
          Generate a natural language response based on:
          - **Question:** {question}
          - **Results:** {response}
          - **History:** {chat_history}
  
          **Guidelines:**
          1. If results are empty, state: "No data found."
          2. For quantities, use 'units', 'items', or 'records'.
          3. For monetary values, use peso sign (₱) and format to 2 decimal places.
          4. Highlight key insights with **bold**.
          5. Use markdown: - for lists.
          6. If total_discount = 0, note: "No discounts recorded."
          7. If total_categories ≥ total_products, caution: "High category count."
          8. Combine multi-step results logically.
          """
          chain = (
              RunnablePassthrough.assign(response=lambda _: json.dumps(all_data, indent=2))
              | ChatPromptTemplate.from_template(response_template)
              | ChatGroq(model="llama3-70b-8192", temperature=0.2, api_key=st.secrets["GROQ_API_KEY"])
              | StrOutputParser()
          )
  
          natural_response = chain.invoke({
              "question": user_query,
              "chat_history": chat_history,
          })
  
          combined_data = all_data[-1]["data"] if all_data else []
          return natural_response, combined_data
  
  def handle_query(query: str):
      """Process a user's query, update chat history, and display response."""
      if not query:
          return
      
      st.session_state.chat_history.append(HumanMessage(content=query))
      with st.chat_message("Human", avatar="dist/img/Human.png"):
          st.markdown(query)
  
      with st.spinner("Analyzing your query..."):
          try:
              history_tuple = tuple(msg.content for msg in st.session_state.chat_history[-6:])
              natural_response, data = get_response(query, history_tuple)
          except Exception as e:
              natural_response = f"An error occurred: {str(e)}"
              data = None
  
      st.session_state.chat_history.append(AIMessage(content=natural_response))
      with st.chat_message("AI", avatar="dist/img/ai.png"):
          st.markdown(natural_response)
          if data and isinstance(data, list) and len(data) >= 1:
              df = pd.DataFrame(data)
              for col in df.columns:
                  if "date" in col.lower():
                      df[col] = pd.to_datetime(df[col], errors='coerce')
                  if any(mon in col.lower() for mon in ["subtotal", "total", "unit_price", "sale_price", "purchase_price", "total_price", "paid", "due", "discount", "total_revenue", "avg_price", "net_total", "base_cost", "profit", "avg_sales_value", "total_inventory_value", "category_value"]):
                      df[col] = pd.to_numeric(df[col], errors='coerce')
                      df.rename(columns={col: f"{col} (₱)"}, inplace=True)
                  elif col.lower() in ["total_sold", "transaction_count", "login_count", "product_count", "total_products", "total_categories", "total_invoices"]:
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
                          ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                      elif chart_type == 'line':
                          df.plot(kind='line', x=columns[0], y=columns[1], ax=ax)
                          ax.set_title(f"{columns[1].replace(' (₱)', '')} Over Time")
                          ax.set_xlabel("Date")
                          ax.set_ylabel("Units" if columns[1].lower() in ["total_sold", "transaction_count", "login_count", "total_products", "total_categories", "total_invoices"] else columns[1].replace(' (₱)', ' (Pesos)'))
                      elif chart_type == 'pie':
                          ax.pie(df[columns[1]], labels=df[columns[0]], autopct='%1.1f%%')
                          ax.set_title(f"Distribution of {columns[1].replace(' (₱)', '')}")
                      st.pyplot(fig)
                      st.download_button("Download Data", df.to_csv(index=False), "data.csv")
              if len(df) > 0 or len(df.columns) > 1:
                  st.table(df)
  
  def determine_chart_type(query: str, df: pd.DataFrame):
      """Determine the appropriate chart type for the query and data."""
      if df.empty:
          return None, []
      
      query_lower = query.lower()
      columns = df.columns
      
      # Check for date-based columns
      date_cols = [col for col in columns if "date" in col.lower() or df[col].dtype in ["datetime64[ns]"]]
      numeric_cols = [col for col in columns if df[col].dtype in ["int64", "float64"] and "id" not in col.lower()]
      categorical_cols = [col for col in columns if df[col].dtype == "object" and "name" in col.lower() or "category" in col.lower()]
      
      # Line chart for time series
      if date_cols and numeric_cols:
          return "line", [date_cols[0], numeric_cols[0]]
      
      # Pie chart for distributions
      if "distribution" in query_lower or "share" in query_lower or "percentage" in query_lower:
          if categorical_cols and numeric_cols:
              return "pie", [categorical_cols[0], numeric_cols[0]]
      
      # Bar chart for comparisons
      if categorical_cols and numeric_cols:
          return "bar", [categorical_cols[0], numeric_cols[0]]
      
      return None, []
  
  # Streamlit UI
  st.markdown("""
      <div style='text-align: center;'>
          <img src='dist/img/AcaSquad.png' alt='AcaSquad Logo' width='150'>
          <h1>AcaSquad AI</h1>
          <p style='font-size: 18px; color: #555;'>Your intelligent assistant for the SCC School Store Database.</p>
      </div>
  """, unsafe_allow_html=True)
  
  # Sidebar for user authentication and settings
  with st.sidebar:
      st.header("User Settings")
      if "user_id" not in st.session_state:
          username = st.text_input("Username")
          password = st.text_input("Password", type="password")
          role = st.selectbox("Role", ["Cashier", "Admin", "Owner"])
          if st.button("Login"):
              # Simplified authentication (replace with API call to employees table)
              login_query = """
              SELECT employee_id, role FROM employees 
              WHERE email = %s AND password_hash = %s;
              """
              login_data = fetch_data_from_api("execute_query", {
                  "query": login_query,
                  "params": [username, password]  # In production, hash password
              })
              if login_data and login_data[0]["role"] == role:
                  st.session_state.user_id = login_data[0]["employee_id"]
                  st.session_state.user_role = role
                  st.success("Logged in successfully!")
              else:
                  st.error("Invalid credentials or role.")
      else:
          st.write(f"Logged in as {st.session_state.user_role}")
          if st.button("Logout"):
              del st.session_state.user_id
              del st.session_state.user_role
              st.session_state.chat_history = []
              st.success("Logged out.")
  
      st.markdown("---")
      if st.button("Show User Guide"):
          try:
              with open("README.md", "r") as f:
                  st.markdown(f.read())
          except FileNotFoundError:
              st.markdown("""
              # AcaSquad AI User Guide
              ## Overview
              Query sales, inventory, and more with natural language.
              ## Common Queries
              - Sales: "Best-selling products"
              - Inventory: "Low stock items"
              - Employee: "Top employees" (Admin/Owner only)
              ## Troubleshooting
              - No data? Rephrase or check date.
              - Errors? Contact admin.
              """)
  
  # Main chat interface
  st.markdown("### Ask a Question")
  query = st.text_input("Enter your query (e.g., 'Best-selling products this month')", key="query_input")
  if st.button("Submit Query") or query:
      handle_query(query)
  
  # Display chat history
  st.markdown("### Conversation History")
  for message in st.session_state.chat_history:
      avatar = "dist/img/Human.png" if isinstance(message, HumanMessage) else "dist/img/ai.png"
      with st.chat_message("Human" if isinstance(message, HumanMessage) else "AI", avatar=avatar):
          st.markdown(message.content)
