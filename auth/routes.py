import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from flask import Blueprint, current_app, request
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from models import User, PasswordResetToken
from security import ApiError, require_json, normalize_email, validate_password,validate_username,check_rate,client_ip
from mailer import send_reset_email

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

def utc_now():
    return datetime.now(timezone.utc)
#ubah obj database menjadi dict (json)
def user_to_dict(user):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
    }

#register
@auth_bp.post("/register")
def register():
    data = require_json()
    check_rate("register_ip",client_ip(), 15,3600)
    username = validate_username(data.get("username"))
    email = normalize_email(data.get("email"))
    password = validate_password(data.get("password"))
    role = data.get("role", "user")

    if role not in ("user", "organizer"):
        raise ApiError(400,"Invalid role.")
    existing = db.session.scalar(
        select(User).where((User.email == email)|(User.username == username))
    )
    if existing:
        raise ApiError(409,"Username or email already registered.")
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        role = role
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        if getattr(error.orig,"sqlstate",None)=="23505":
            raise ApiError(409,"Username or email already registered.")
        current_app.logger.exception("Registration failed due to a database constraint.")
        raise ApiError(500,"Registration failed due to a database error.")
    return{
        "message": "Account created successfully.",
        "user": user_to_dict(user)
    }, 201

#login
@auth_bp.post("/login")
def login():
    data = require_json()
    email = normalize_email(data.get("email"))
    password = data.get("password")
    if not isinstance(password,str) or len(password) > 128:
        raise ApiError(400,"Invalid password.")

    #batasi per IP dan email untuk mengurangi resiko bruteforce
    check_rate("login_ip", client_ip(),20,900)
    check_rate("login_email",email,8,900)
    user = db.session.scalar(select(User).where(User.email==email))
    if not user or not check_password_hash(user.password_hash,password):
        raise ApiError(401,"Invalid credentials.")
    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role":user.role}
    )
    return{
        "access_token": token,
        "token_type": "Bearer",
        "user": user_to_dict(user)
    }, 200
#GET profile, perlu jwt
@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        raise ApiError(404, "User not found.")
    return {"user": user_to_dict(user)}, 200

#Logout
@auth_bp.post("/logout")
@jwt_required()
def logout():
    return{
        "message": "Discard the access token on the client.",
        "note": "The existing token remains valid until expiration"
    }, 200

#lupa password
@auth_bp.post("/forgot-password")
def forgot_password():
    data = require_json()
    email = normalize_email(data.get("email"))
    check_rate("reset_ip",client_ip(),10,1800)
    check_rate("reset_email",email,3,1800)
    user = db.session.scalar(select(User).where(User.email==email))
    response={"message":"If the account exists, password reset. Instructions will be sent"}

    if not user:
        return response, 200
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=utc_now()+timedelta(minutes=30)
    )
    db.session.add(reset_token)
    db.session.commit()
    query = urlencode({"token":raw_token})
    base_url = current_app.config["RESET_PAGE_URL"].rstrip("?")
    separator = "&" if "?" in base_url else "?"
    reset_link = base_url + separator + query
    try:
        send_reset_email(user.email,reset_link)
    except Exception:
        current_app.logger.exception("Failed to send password reset email")
    return response, 200

#Cek  reset token
@auth_bp.get("/reset-password")
def check_reset_token():
    raw_token = request.args.get("token","")
    if not raw_token or len(raw_token) > 256:
        raise ApiError(400,"Invalid reset token.")

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if not record or record.used_at is not None or record.expires_at <= utc_now():
        raise ApiError(400,"Invalid or expired reset token.")
    return {
        "valid": True,
        "message":(
            "Submit  the token and new password to POST /auth/reset-password"
        )
    }, 200

#reset password
@auth_bp.post("/reset-password")
def reset_password():
    data = require_json()
    raw_token = data.get("token")
    new_password = validate_password(data.get("new_password"))
    if not isinstance(raw_token,str) or not 10<=len(raw_token)<=256:
        raise ApiError(400,"Invalid reset token.")
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with db.session.begin():
        preview = db.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        if not preview:
            raise ApiError(400,"Invalid or expired reset token.")
        #lock user dulu biar dua reset bersamaan tidak saling collide saat memperbarui pw.
        user = db.session.scalar(
            select(User).where(User.id == preview.user_id). with_for_update()
        )
        record = db.session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.id == preview.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not user or not record or record.used_at is not None or record.expires_at <= utc_now():
            raise ApiError(400,"Invalid or expired reset token.")
        user.password_hash = generate_password_hash(new_password)
        db.session.execute(
            update(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None)
            ).values(used_at=utc_now())
        )
        return{
            "message": "Successfully reset your password.",
        }, 200