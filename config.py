import os
from dotenv import load_dotenv

load_dotenv()

# --- OpenAI ---
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# --- MSSQL ---
DB_SERVER: str = os.getenv("DB_SERVER", "localhost,1433")
DB_NAME: str = os.getenv("DB_NAME", "ocr_db")
DB_USER: str = os.getenv("DB_USER", "sa")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
DB_DRIVER: str = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")

# --- External API ---
API_KEY: str = os.getenv("API_KEY", "")

DB_CONNECTION_STRING: str = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    "TrustServerCertificate=yes;"
)
