import secrets
from flask import Blueprint, request, current_app
from sqlalchemy import select
from extensions import db
from models import Order
from helpers import utc_now, ApiError
from expiration import expire_event_orders

cron_bp = Blueprint("cron", __name__)
@cron_bp.get("/internal/expire-orders")
def expire_orders():
    secret = current_app.config["CRON_SECRET"]
    authorization = request.headers.get("Authorization","")
    expected = f"Bearer {secret}"
    if not secret or not secrets.compare_digest(
        authorization.encode("utf-8"),
        expected.encode("utf-8")
    ):
        raise ApiError(401, "Unauthorized")
    with db.session.begin():
        event_ids = db.session.scalars(
            select(Order.event_id)
            .where(
                Order.status == "pending",
                Order.expires_at <= utc_now()
            ).distinct().order_by(Order.event_id).limit(50)
        ).all()
    expired_count = 0
    for event_id in event_ids:
        with db.session.begin():
            expired_count += expire_event_orders(event_id)
    return {
        "message": "Expiration completed",
        "expired_orders": expired_count
    }, 200