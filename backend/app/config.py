import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"
DATA_DIR = BACKEND_DIR / "data"

load_dotenv(BACKEND_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    MAX_PAGES = int(os.environ.get("WEB_MAX_PAGES", "6"))
    SKIP_TESTS = os.environ.get("WEB_SKIP_TESTS", "false").lower() == "true"

    # ------------------------------------------------------------------
    # MySQL (users table) -- used by app/utils/db.py + app/models/user.py
    # ------------------------------------------------------------------
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "websense_ai")

    # Full connection string can be overridden directly with DATABASE_URL
    # if you'd rather not set the individual DB_* vars above.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"mysql+mysqlconnector://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    )

    # Connection pooling
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "1800"))  # seconds
