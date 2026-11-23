import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

def get_pem(name):
    value = os.getenv(name,"").replace("\\n","\n")
    if value.strip():
        return value

    path = os.getenv(f"{name}_PATH")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return ""

def normalize_database_url(url):
    if url.startswith("postgres://"):
        return url.replace("postgres://","postgresql+psycopg://",1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

def get_config():
    load_dotenv()
    return{
        "SQLALCHEMY_DATABASE_URI": normalize_database_url(os.getenv("DATABASE_URL","")),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "pool_recycle": 240,
            "pool_size": 2,
            "max_overflow": 1,
        },
        "JWT_ALGORITHM": "RS256",
        "JWT_DECODE_ALGORITHMS": ["RS256"],
        "JWT_PRIVATE_KEY": get_pem("JWT_PRIVATE_KEY"),
        "JWT_PUBLIC_KEY": get_pem("JWT_PUBLIC_KEY"),
        #issuer => penerbit token
        #audience => service tujuan token
        "JWT_ENCODE_ISSUER": "auth-service",
        "JWT_DECODE_ISSUER": "auth-service",
        "JWT_ENCODE_AUDIENCE": "ticketing-service",
        "JWT_DECODE_AUDIENCE": "ticketing-service",

        "JWT_TOKEN_LOCATION": ["headers"],
        "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=15),

        "APP_ENV": os.getenv("APP_ENV", "development"),

        "SMTP_HOST": os.getenv("SMTP_HOST", ""),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "587")),
        "SMTP_USERNAME": os.getenv("SMTP_USERNAME", ""),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
        "SMTP_USE_SSL": os.getenv("SMTP_USE_SSL","false").lower() == "true",
        "MAIL_FROM": os.getenv("MAIL_FROM", ""),
        "RESET_PAGE_URL": os.getenv(
            "RESET_PAGE_URL",
            "http://localhost:8001/auth/reset-password"
        ),
        "MAX_CONTENT_LENGTH": 16 * 1024
    }
