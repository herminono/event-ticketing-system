from datetime import date, datetime, time, timedelta, timezone
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from sqlalchemy import select,func
from extensions import db
from models import Event, TicketType, Order, IssuedTicket
from helpers import ApiError, utc_now, require_json, role_required, require_event_owner, current_user_id, text_field, parse_datetime,validate_event_type,event_to_dict
from extensions import limiter
from rate_limit import verified_user_key
from audit import record_audit

event_bp = Blueprint('events', __name__)

#buat event, status event awal selalu sebagai draft
#dengan demikian organizer dapat menambahkan tiket sebelum event dipublikasikan.
@event_bp.post("/events")
@limiter.limit("10 per hour",key_func=verified_user_key)
@role_required("organizer")
def create_event():
    data = require_json()
    title = text_field(data.get("title"),"title",150)
    description = text_field(data.get("description"),"description",5000)
    category = text_field(data.get("category"),"category",50)
    event_type = data.get("event_type")
    location, meeting_url = validate_event_type(event_type, data.get("location"), data.get("meeting_url"))
    start_at = parse_datetime(data.get("start_at"))
    end_at = parse_datetime(data.get("end_at"))
    if start_at <= utc_now() or end_at <= start_at:
        raise ApiError(400,"Invalid event schedule")
    with db.session.begin():
        event = Event(
            organizer_id=current_user_id(),
            title=title,
            description=description,
            category=category,
            event_type=event_type,
            location=location,
            meeting_url=meeting_url,
            start_at=start_at,
            end_at=end_at,
            status="draft"
        )
        db.session.add(event)
        db.session.flush()
        record_audit(action="EVENT_MADE",target_id=event.id)
        result = event_to_dict(event,include_private=True)
    return {"event":result},201

#public event list, pagination membatasi jumlah record per request
#Query SQLAlchemy menggunakan parameter binding, sehingga input pencarian aman dari SQL injection
@event_bp.get("/events")
def list_events():
    try:
        page = int(request.args.get("page",1))
        limit = int(request.args.get("limit",10))
    except ValueError:
        raise ApiError(400,"Invalid pagination")
    if page < 1 or not 1 <= limit<= 50:
        raise ApiError(400,"Invalid pagination")
    filters = [Event.status.in_(["published","canceled"])]
    search = request.args.get("search", "").strip()
    if len(search) > 100:
        raise ApiError(400,"Search too long")
    if search:
        escaped=(
            search.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        )
        filters.append(Event.title.ilike(f"%{escaped}%", escape="\\"))
    category = request.args.get("category")
    if category:
        if len(category) > 50:
            raise ApiError(400,"Invalid category")
        filters.append(Event.category == category)
    location = request.args.get("location")
    if location:
        if len(location) > 100:
            raise ApiError(400,"Invalid location")
        escaped_location=(
            location.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        )
        filters.append(Event.location.ilike(f"%{escaped_location}%", escape="\\"))
    event_date = request.args.get("date")
    if event_date:
        try:
            selected = date.fromisoformat(event_date)
        except ValueError:
            raise ApiError(400,"Invalid date")
        day_start = datetime.combine(selected,time.min,tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        #event yang berlangsung beberapa hari akan tetap muncul selama tanggal
        #pencarian berada dalam periode event
        filters.extend([Event.start_at < day_end,Event.end_at >= day_start])
    total = db.session.scalar(select(func.count(Event.id)).where(*filters))
    events = db.session.scalars(
        select(Event).where(*filters).order_by(Event.start_at,Event.id).offset((page-1)*limit).limit(limit)
    ).all()
    return{
        "page":page,
        "limit":limit,
        "total":total,
        "events":[event_to_dict(event) for event in events],
    }, 200

#detail event
#JWT opsional memungkinkan akses publik, tetapi draft hanya bisa dilihat pemiliki event (organizer).
@event_bp.get("/events/<int:event_id>")
@jwt_required(optional=True)
def get_event(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        raise ApiError(404, "Event not found")
    owner = (
        get_jwt().get("role") == "organizer" and get_jwt_identity() is not None and str(event.organizer_id) == get_jwt_identity()
    )
    if event.status == "draft" and not owner:
        raise ApiError(404, "Event not found")
    return {"event":event_to_dict(event,include_private=owner)},200

#list of events owned by organizer
@event_bp.get("/organizer/events")
@role_required("organizer")
def organizer_events():
    events = db.session.scalars(select(Event).where(Event.organizer_id==current_user_id()).order_by(Event.created_at.desc())).all()
    return{
        "events":[event_to_dict(event, include_private=True) for event in events]
    }, 200

#update event
#informasi penting tidak boleh diubah setelah event menerima minimal satu pesanan.
@event_bp.patch("/events/<int:event_id>")
@role_required("organizer")
def update_event(event_id):
    data = require_json()
    allowed = {
        "title", "description", "category",
        "event_type", "location", "meeting_url",
        "start_at", "end_at"
    }
    if not data or not set(data).issubset(allowed):
        raise ApiError(400, "Invalid event update")
    with db.session.begin():
        event = db.session.scalar(
            select(Event).where(Event.id==event_id).with_for_update()
        )
        if not event:
            raise ApiError(404, "Event not found")
        require_event_owner(event)
        if event.status == "canceled":
            raise ApiError(409,"Canceled event cant be updated")
        has_orders = db.session.scalar(
            select(Order.id).where(Order.event_id==event_id).limit(1)
        ) is not None
        if has_orders and not set(data).issubset({"description"}):
            raise ApiError(409,"Only description can be changed after order exist.")

        title = event.title
        description = event.description
        category = event.category
        event_type = event.event_type
        location = event.location
        meeting_url = event.meeting_url
        start_at = event.start_at
        end_at = event.end_at

        if "title" in data:
            title = text_field(data["title"],"title",150)
        if "description" in data:
            description = text_field(data["description"],"description",5000)
        if "category" in data:
            category = text_field(data["category"],"category",50)
        if "event_type" in data:
            event_type = data["event_type"]
        if "location" in data:
            location = data["location"]
        if "meeting_url" in data:
            meeting_url = data["meeting_url"]
        if "start_at" in data:
            start_at = parse_datetime(data["start_at"])
        if "end_at" in data:
            end_at = parse_datetime(data["end_at"])

        location,meeting_url=validate_event_type(event_type,location,meeting_url)
        if end_at <= start_at:
            raise ApiError(400, "Invalid event schedule")

        if not has_orders and start_at <= utc_now():
            raise ApiError(409, "Event has already started")

        ticket_types = db.session.scalars(select(TicketType).where(TicketType.event_id==event_id)).all()
        if any(ticket.sale_end>start_at for ticket in ticket_types):
            raise ApiError(400, "Event starts before ticket sales end")

        event.title = title
        event.description = description
        event.category = category
        event.event_type = event_type
        event.location = location
        event.meeting_url = meeting_url
        event.start_at = start_at
        event.end_at = end_at
        result = event_to_dict(event,include_private=True)

        return {"event":result}, 200

#publish event
#event hanya bisa dipublish jika sudah punya at least satu jenis tiket.
@event_bp.patch("/events/<int:event_id>/publish")
@role_required("organizer")
def publish_event(event_id):
    with db.session.begin():
        event=db.session.scalar(
            select(Event).where(Event.id==event_id).with_for_update()
        )
        if not event:
            raise ApiError(404, "Event not found")
        require_event_owner(event)
        if event.status != "draft":
            raise ApiError(409, "Event is not draft")
        if event.start_at <= utc_now():
            raise ApiError(409, "Event has already started")
        ticket_count = db.session.scalar(
            select(func.count(TicketType.id)).where(TicketType.event_id==event_id)
        )
        if ticket_count == 0:
            raise ApiError(409, "Event needs a ticket type")
        event.status = "published"
        result = event_to_dict(event,include_private=True)
    return {"event":result}, 200

#cancel event
#pembatalan dilakukan dalam satu database transaction. Semua pending order dilepaskan, dan semua issued
#tickets dinyatakan invalid.
@event_bp.patch("/events/<int:event_id>/cancel")
@role_required("organizer")
def cancel_event(event_id):
    with db.session.begin():
        event=db.session.scalar(
            select(Event).where(Event.id==event_id).with_for_update()
        )
        if not event:
            raise ApiError(404, "Event not found")
        require_event_owner(event)
        if event.status == "canceled":
            raise ApiError(409, "Event already canceled")
        ticket_types = db.session.scalars(
            select(TicketType).where(TicketType.event_id==event_id).order_by(TicketType.id).with_for_update()
        ).all()
        orders=db.session.scalars(
            select(Order).where(Order.event_id==event_id).order_by(Order.id).with_for_update()
        ).all()
        for order in orders:
            if order.status=="pending":
                order.status = "canceled"
        for ticket_type in ticket_types:
            ticket_type.reserved_stock = 0

        issued_tickets=db.session.scalars(
            select(IssuedTicket).join(Order,IssuedTicket.order_id==Order.id)
            .where(Order.event_id==event_id).order_by(IssuedTicket.id).with_for_update(of=IssuedTicket)
        ).all()
        for ticket in issued_tickets:
            ticket.status = "invalid"

        event.status = "canceled"
    return{"message":"Event canceled, issued tickets invalidated"},200

#Delete event
#untuk menjaga riwayat transaksi, hard delete hanya dibolehin bagi draft tanpa tiket/order.
@event_bp.delete("/events/<int:event_id>")
@role_required("organizer")
def delete_event(event_id):
    with db.session.begin():
        event=db.session.scalar(
            select(Event).where(Event.id==event_id).with_for_update()
        )
        if not event:
            raise ApiError(404, "Event not found")
        require_event_owner(event)
        if event.status != "draft":
            raise ApiError(409,"Only draft events can be deleted")
        has_ticket = db.session.scalar(
            select(TicketType.id).where(TicketType.event_id==event_id).limit(1)
        )
        has_order= db.session.scalar(
            select(Order.id).where(Order.event_id==event_id).limit(1)
        )
        if has_ticket or has_order:
            raise ApiError(409,"Event with ticket data cannot be deleted")
        db.session.delete(event)
    return{"message":"Event deleted"},200 