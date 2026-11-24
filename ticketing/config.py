import os
from pathlib import Path
from dotenv import load_dotenv

def get_public_key():
    value = os.getenv("JWT_PUBLIC_KEY","").replace("\\n", "\n")
    if value.strip():
        return value
    path = os.getenv("JWT_PUBLIC_KEY_PATH")
    if path:
        return Path(path).read_text(encoding="utf-8")

    return ""

def normalize_database_url(url):
    if url.startswith("postgres://"):
        return url.replace("postgres://","postgresql+psycopg://",1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://","postgresql+psycopg://",1)
    return url

def get_config():
    load_dotenv()
    return{
        "SQLALCHEMY_DATABASE_URI": normalize_database_url(os.environ["DATABASE_URL"]),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS":{
            "pool_pre_ping": True,
            "pool_size": 2,
            "pool_recycle": 240,
            "max_overflow": 1,
        },
        "JWT_ALGORITHM": "RS256",
        "JWT_DECODE_ALGORITHMS": ["RS256"],
        "JWT_PUBLIC_KEY": get_public_key(),
        "JWT_DECODE_ISSUER": "auth-service",
        "JWT_DECODE_AUDIENCE": "ticketing-service",
        "JWT_TOKEN_LOCATION": ["headers"],
        "MAX_CONTENT_LENGTH": 16 * 1024,
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        "RATELIMIT_HEADERS_ENABLED": True,
        "ORDER_EXPIRATION_MINUTES": int(os.getenv("ORDER_EXPIRATION_MINUTES", "30")),
        "CRON_SECRET": os.getenv("CRON_SECRET", ""),
    }