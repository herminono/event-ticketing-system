import hashlib
import re
from datetime import datetime, timedelta, timezone
from email_validator import validate_email, EmailNotValidError
from flask import request
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from extensions import db
from models import RateBucket

class ApiError(Exception):
    def __init__(self,status, message):
        self.status = status
        self.message = message

#validasi input untuk memastikan data sesuai aturan
def require_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "JSON object missing.")
    return data

def normalize_email(value):
    if not isinstance(value,str) or len(value) > 255:
        raise ApiError(400, "Invalid email address")

    try:
        return validate_email(value,check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ApiError(400, "Invalid email address")

def validate_username(value):
    if not isinstance(value,str):
        raise ApiError(400,"Invalid username")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}",value):
        raise ApiError(400,"Username must contain 3-32 letters, numbers, or underscores.")
    return value.lower()

def validate_password(value):
    if not isinstance(value,str):
        raise ApiError(400,"Invalid password")

    if not 8<=len(value)<=128:
        raise ApiError(400,"Password must be between 10 and 128 characters")
    if not any(char.isalpha()for char in value):
        raise ApiError(400,"Password must contain at least one letter")
    if not any(char.isdigit()for char in value):
        raise ApiError(400,"Password must contain at least one number")
    return value

def client_ip():
    return request.remote_addr or "unknown"

#Rate limiting dengan atomic postgresql upsert
def check_rate(scope, identifier, limit, window_seconds):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)
    digest = hashlib.sha256(f"{scope}:{identifier}".encode("utf-8")).hexdigest()
    expired=RateBucket.started_at<cutoff
    statement = insert(RateBucket).values(
        scope = scope,
        key_hash = digest,
        hits =1,
        started_at = now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["scope", "key_hash"],
        set_={
            "hits":case(
                (expired,1),
                else_=RateBucket.hits + 1
            ),
            "started_at":case(
                (expired,now),
                else_=RateBucket.started_at
            )
        }
    ).returning(RateBucket.hits)

    hits = db.session.execute(statement).scalar_one()
    db.session.commit()
    if hits>limit:
        raise ApiError(429,"Too many requests. Try again later")

