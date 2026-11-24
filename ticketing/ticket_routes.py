import secrets
from datetime import datetime,timezone
from flask import Blueprint
from flask_jwt_extended import jwt_required,get_jwt
from sqlalchemy import select
from extensions import db
from models import Event, TicketType, Order, IssuedTicket
from helpers import (
    ApiError,
    utc_now,
    require_json,
    role_required,
    current_user_id,
    require_event_owner,
    positive_int,
    nonnegative_int,
    text_field,
    parse_datetime,
    parse_price,
    ticket_type_to_dict,
    issued_ticket_to_dict, require_ticket_access
)
from extensions import limiter
from rate_limit import verified_user_key
from audit import record_audit
from expiration import expire_event_orders

ticket_bp = Blueprint("tickets",__name__)

#List ticket tyoes
#jenis tiket untuk draft hanya terlihat oleh organizer yang mengelola event tersebut.
@ticket_bp.get("/events/<int:event_id>/tickets")
@jwt_required(optional=True)
def list_ticket_types(event_id):
    with db.session.begin():
        event = db.session.scalar(
            select(Event).where(Event.id == event_id).with_for_update()
        )
        if not event:
            raise ApiError(404, "Event not found")
        is_owner = False
        if get_jwt().get("role") == "organizer":
            is_owner = event.organizer_id == current_user_id()
        if event.status == "draft" and not is_owner:
            raise ApiError(404, "Event not found")
        expire_event_orders(event_id)
        tickets = db.session.scalars(
            select(TicketType).where(TicketType.event_id == event_id).order_by(TicketType.id)
        ).all()
        result = [ticket_type_to_dict(ticket) for ticket in tickets]
    return {"tickets": result}, 200

#Create ticket types
#harga akan tetap setelah tiket dibuat. Nmama dinormalisasi ke uppercase agar "Regular" dan "regular" tidak menjadi dua kategori berbeda.
@ticket_bp.post("/events/<int:event_id>/tickets")
@limiter.limit("20 per hour",key_func=verified_user_key)
@role_required("organizer")
def create_ticket_type(event_id):
    data = require_json()
    name = text_field(data.get("name"), "name", 50)
    name = text_field(name.upper(), "name", 50)
    price=parse_price(data.get("price"))
    total_stock=nonnegative_int(data.get("total_stock"),"total_stock")
    sale_start=parse_datetime(data.get("sale_start"))
    sale_end=parse_datetime(data.get("sale_end"))
    if sale_end <sale_start:
        raise ApiError(400,"Invalid ticket sale schedule")
    with db.session.begin():
        event=db.session.scalar(
            select(Event).where(Event.id == event_id).order_by(Event.id).with_for_update()
        )
        if not event:
            raise ApiError(404,"Event not found")
        require_event_owner(event)
        if event.status == "canceled":
            raise ApiError(409,"Event already canceled")
        if event.start_at <= utc_now():
            raise ApiError(409,"Event already started")
        if sale_end > event.start_at:
            raise ApiError(400,"Ticket sales must end before event starts")

        ticket = TicketType(
            event_id=event.id,
            name=name,
            price=price,
            total_stock=total_stock,
            reserved_stock=0,
            sold_stock=0,
            sale_start=sale_start,
            sale_end=sale_end
        )
        db.session.add(ticket)
        db.session.flush()
        result = ticket_type_to_dict(ticket)
    return {"ticket":result},201

#update stok
#total stok adalah kapasitas keseluruhan, nilainya tidak boleh < daripada tiket yang terlah direservasi atau dijual.
@ticket_bp.patch("/tickets/<int:ticket_id>/stock")
@role_required("organizer")
def update_ticket_stock(ticket_id):
    data = require_json()
    total_stock=nonnegative_int(data.get("total_stock"),"total_stock")
    with db.session.begin():
        event_id = db.session.scalar(
            select(TicketType.event_id).where(TicketType.id == ticket_id)
        )
        if event_id is None:
            raise ApiError(404, "Ticket not found")
        event = db.session.scalar(
            select(Event).where(Event.id == event_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if not event:
            raise ApiError(404, "Event not found")
        require_event_owner(event)
        expire_event_orders(event.id)
        ticket = db.session.scalar(
            select(TicketType).where(TicketType.id == ticket_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if not ticket:
            raise ApiError(404, "Ticket not found")
        if event.status=="canceled":
            raise ApiError(409,"Event already canceled")
        if event.start_at <= utc_now():
            raise ApiError(400,"Event already started")
        minimum = ticket.reserved_stock + ticket.sold_stock
        if total_stock < minimum:
            raise ApiError(409,"Stock cant be below reserved + sold stock")

        ticket.total_stock = total_stock
        result = ticket_type_to_dict(ticket)
    return {"ticket":result},200

#Issued ticket (milik User)
#Hanya tiket yang telah diterbitkan setelah approval, muncul dalam daftar kepeimilikan.
@ticket_bp.get("/tickets/me")
@role_required("user")
def my_tickets():
    user_id = current_user_id()
    rows = db.session.execute(
        select(IssuedTicket, Order, Event, TicketType)
        .join(Order, IssuedTicket.order_id == Order.id)
        .join(Event, Order.event_id == Event.id)
        .join(TicketType,Order.ticket_type_id == TicketType.id)
        .where(Order.user_id == user_id)
        .order_by(IssuedTicket.issued_at.desc())
    ).all()
    return{
        "tickets":[issued_ticket_to_dict(issued,order,event,ticket_type) for issued,order,event,ticket_type in rows]
    },200

#individual tiket
#yang boleh akses hanya pemilik tiket atau pemilik event
@ticket_bp.get("/issued-tickets/<int:ticket_id>")
@jwt_required()
def get_issued_ticket(ticket_id):
    row = db.session.execute(
        select(IssuedTicket, Order, Event, TicketType)
        .join(Order, IssuedTicket.order_id == Order.id)
        .join(Event, Order.event_id == Event.id)
        .join(TicketType,Order.ticket_type_id == TicketType.id)
        .where(IssuedTicket.id == ticket_id)
    ).first()
    if not row:
        raise ApiError(404,"ticket not found")
    issued,order,event,ticket_type = row
    require_ticket_access(order,event)
    return{"ticket":issued_ticket_to_dict(issued,order,event,ticket_type)},200

#Check-in
#organizer memverifikasi kode unik tiket. Tiket used tidaj bisa digunakan lagi,
@ticket_bp.post("/tickets/check-in")
@limiter.limit("30 per minute",key_func=verified_user_key)
@role_required("organizer")
def check_in_ticket():
    data = require_json()
    ticket_code=text_field(data.get("ticket_code"),"ticket_code",40)
    with db.session.begin():
        preview= db.session.execute(
            select(IssuedTicket,Order).join(Order,IssuedTicket.order_id==Order.id)
            .where(IssuedTicket.ticket_code == ticket_code)
        ).first()
        if not preview:
            raise ApiError(404,"Ticket not found")
        issued_preview,order = preview
        event = db.session.scalar(
            select(Event).where(Event.id==order.event_id).with_for_update()
        )
        require_event_owner(event)
        issued=db.session.scalar(
            select(IssuedTicket).where(IssuedTicket.id==issued_preview.id).with_for_update().execution_options(populate_existing=True)
        )
        if event.status != "published":
            raise ApiError(409,"Event is not active")
        now = utc_now()
        if not event.start_at <= now <= event.end_at:
            raise ApiError(409,"Check-in is outside event schedule")
        if issued.status != "valid":
            raise ApiError(409,"Ticket is not valid")
        issued.status = "used"
        issued.checked_in_at = now
        record_audit(action="TICKET_CHECKED_IN", target_id=issued.id)
        result={
            "ticket_code": issued.ticket_code,
            "status": issued.status,
            "checked_in_at": wib_iso(now)
        }
    return {
        "message":"Check-in successful",
        "ticket":result
    },200