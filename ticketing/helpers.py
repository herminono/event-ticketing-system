import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlsplit
from flask import request
from flask_jwt_extended import jwt_required,get_jwt,get_jwt_identity
from zoneinfo import ZoneInfo

class ApiError(Exception):
    def __init__(self,status,message):
        self.status = status
        self.message = message

def utc_now():
    return datetime.now(timezone.utc)

WIB = ZoneInfo("Asia/Jakarta")

def wib_iso(dt):
    if dt is None:
        return None
    return dt.astimezone(WIB).isoformat()

def require_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400,"JSON OBject missing")
    return data

#custom decorator untuk mastiin JWT valid dan role sesuai.
def role_required(role):
    def decorator(function):
        @wraps(function)
        @jwt_required()
        def wrapper(*args, **kwargs):
            if get_jwt().get("role") != role:
                raise ApiError(403, "Role not allowed")
            return function(*args, **kwargs)
        return wrapper
    return decorator

def current_user_id():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        raise ApiError(401,"Invalid identity")

    if user_id <= 0:
        raise ApiError(401, "Invalid identity")
    return user_id

#cek kepemilikan objek
def require_event_owner(event):
    if event is None:
        raise ApiError(404, "Event not found")
    if event.organizer_id != current_user_id():
        raise ApiError(403, "Not your event")
def require_order_access(order,event):
    if order is None or event is None:
        raise ApiError(404,"Event not found")
    user_id = current_user_id()
    role = get_jwt().get("role")
    is_buyer= role == "user" and order.user_id == user_id
    is_organizer = role == "organizer" and event.organizer_id == user_id
    if not (is_buyer or is_organizer):
        raise ApiError(404,"Order not found")
def require_ticket_access(order,event):
    if order is None or event is None:
        raise ApiError(404, "Ticket not found")
    user_id = current_user_id()
    role = get_jwt().get("role")
    is_buyer = role == "user" and order.user_id == user_id
    is_organizer = role == "organizer"and event.organizer_id == user_id
    if not (is_buyer or is_organizer):
        raise ApiError(404, "Ticket not found")

#validasi input
def positive_int(value,field):
    if type(value)is not int or value <= 0:
        raise ApiError(400, f"{field} must be in positive integer")
    return value

def nonnegative_int(value,field):
    if type(value)is not int or value < 0:
        raise ApiError(400, f"{field} must be in nonnegative integer")
    return value

def text_field(value,field,maximum,minimum=1):
    if not isinstance(value,str):
        raise ApiError(400,f"Invalid {field} value")
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise ApiError(400,f"Invalid {field} value")
    return value
#Tanggal harus mengandung timezone, semua datetime dinormalisasi ke utc
def parse_datetime(value):
    if not isinstance(value,str):
        raise ApiError(400,"Datetime must be ISO 8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        raise ApiError(400,"Invalid datetime")

    if dt.tzinfo is None:
        raise ApiError(400,"Datetime must include timezone")
    return dt.astimezone(timezone.utc)

def parse_price(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float)):
        raise ApiError(400,"Invalid price")
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        raise ApiError(400,"Invalid price")
    if not price.is_finite():
        raise ApiError(400,"Invalid price")
    if price < 0 or price>Decimal("9999999999.99"):
        raise ApiError(400,"Price out of range")
    if price != price.quantize(Decimal("0.01")):
        raise ApiError(400,"Price has too many decimal places")
    return price

def validate_event_type(event_type,location,meeting_url):
    if event_type not in ("online","offline"):
        raise ApiError(400,"Invalid event type")
    if event_type == "offline":
        location = text_field(location,"location",255)
        meeting_url = None
    else:
        location = None
        meeting_url = text_field(meeting_url,"meeting_url",500)
        parsed = urlsplit(meeting_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ApiError(400,"Meeting URL must be HTTPS")
    return location,meeting_url

def event_to_dict(event,include_private=False):
    now = utc_now()
    status = event.status
    if status == "published" and event.end_at < now:
        display_status = "completed"
    else:
        display_status = status
    result = {
        "id": event.id,
        "organizer_id": event.organizer_id,
        "title": event.title,
        "description": event.description,
        "category": event.category,
        "event_type": event.event_type,
        "location": event.location,
        "start_at": wib_iso(event.start_at),
        "end_at": wib_iso(event.end_at),
        "status": status,
        "display_status": display_status,
    }
    if include_private:
        result["meeting_url"] = event.meeting_url
    return result

def ticket_type_to_dict(ticket):
    available = (ticket.total_stock-ticket.reserved_stock-ticket.sold_stock)
    return {
        "id": ticket.id,
        "event_id": ticket.event_id,
        "name": ticket.name,
        "price": str(ticket.price),
        "total_stock": ticket.total_stock,
        "reserved_stock": ticket.reserved_stock,
        "sold_stock": ticket.sold_stock,
        "available_stock": available,
        "sale_start": wib_iso(ticket.sale_start),
        "sale_end": wib_iso(ticket.sale_end)
    }

def order_to_dict(order):
    return{
        "id": order.id,
        "user_id": order.user_id,
        "event_id": order.event_id,
        "ticket_type_id": order.ticket_type_id,
        "quantity": order.quantity,
        "total_price": str(order.total_price),
        "status": order.status,
        "rejection_reason": order.rejection_reason,
        "validated_by": order.validated_by,
        "validated_at": wib_iso(order.validated_at),
        "created_at": wib_iso(order.created_at)
    }

def issued_ticket_to_dict(ticket,order,event,ticket_type):
    result = {
        "id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status,
        "order_id": order.id,
        "event_id": event.id,
        "event_title": event.title,
        "ticket_type": ticket_type.name,
        "start_at": wib_iso(event.start_at),
        "end_at": wib_iso(event.end_at),
        "issued_at": wib_iso(ticket.issued_at),
        "checked_in_at": wib_iso(ticket.checked_in_at)
    }
    #informasi event online dibagikan hanya ke pemilik tiket,bukan publik.
    if event.event_type == "online" and event.status != "canceled":
        result["meeting_url"] = event.meeting_url

    return result