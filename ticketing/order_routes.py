import hashlib
import json
import secrets
import uuid
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import select,func
from sqlalchemy.dialects.postgresql import insert
from extensions import db
from models import Event, TicketType, Order, IdempotencyRecord, IssuedTicket
from helpers import ApiError, utc_now, require_event_owner, require_json, role_required, current_user_id, positive_int, \
    text_field, order_to_dict, require_order_access
from extensions import limiter
from rate_limit import verified_user_key
from audit import record_audit

order_bp = Blueprint('orders',__name__)

#kita kunci Event, TicketType, Order ketika sebuah order diubah.
def lock_order_resources(order_id):
    preview = db.session.execute(
        select(Order.event_id, Order.ticket_type_id).where(Order.id == order_id)
    ).first()
    if not preview:
        raise ApiError(404,'Order not found')
    event_id, ticket_type_id = preview
    event = db.session.scalar(
        select(Event).where(Event.id==event_id).with_for_update()
    )
    ticket_type = db.session.scalar(
        select(TicketType).where(TicketType.id==ticket_type_id).with_for_update()
    )
    order = db.session.scalar(
        select(Order).where(Order.id==order_id).with_for_update()
    )
    if (
        not event
        or not ticket_type
        or not order
        or ticket_type.event_id != event.id
        or order.event_id != event.id
        or order.ticket_type_id != ticket_type.id
    ):
        raise ApiError(409,"Inconsistent order relationship")
    return event, ticket_type, order

def get_idempotency_key():
    raw_key=request.headers.get("Idempotency-Key")
    if not raw_key:
        raise ApiError(400,'Idempotency key is required')

    try:
        parsed = uuid.UUID(raw_key)
    except(ValueError,TypeError,AttributeError):
        raise ApiError(400,'Idempotency key is invalid')

    if parsed.version != 4:
        raise ApiError(400,'Idempotency key dmust be UUID v4')
    return str(parsed)

#Hash payload memastikan satu key idempotency tidak bisa digunakan untuk dua isi request yang berbeda.
def payload_fingerprint(data):
    canonical = json.dumps(data,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

#Create order
#PostgreSQL (ON CONFLICT DO NOTHING dan RETURNING) dipakai untuk klaim idempotency key.
#jika ada request bersamaan dengan key sama, hanya satu yang boleh membuat order.
@order_bp.post('/orders')
@limiter.limit("10 per minute",key_func=verified_user_key)
@role_required('user')
def create_order():
    data = require_json()
    ticket_type_id = positive_int(data.get("ticket_type_id"),"ticket_type_id")
    quantity = positive_int(data.get("quantity"),"quantity")
    if quantity > 5:
        raise ApiError(400, "maximum 5 tickets per event.")
    user_id = current_user_id()
    idem_key = get_idempotency_key()
    fingerprint = payload_fingerprint({
        "ticket_type_id": ticket_type_id,
        "quantity": quantity,
    })
    response_body = None
    response_status = None
    with db.session.begin():
        statement = insert(IdempotencyRecord).values(
            user_id=user_id,
            operation="create_order",
            idem_key=idem_key,
            payload_hash=fingerprint,
            response_body={},
            response_status=0
        )
        statement = statement.on_conflict_do_nothing(
            constraint="uq_idempotency_key"
        ).returning(IdempotencyRecord.id)
        new_record_id = db.session.execute(statement).scalar_one_or_none()
        if new_record_id is None:
            #jika idem key sudah pernah digunakan, response dari request pertama dikembalikan.
            record = db.session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.operation == "create_order",
                    IdempotencyRecord.idem_key == idem_key,
                )
            )
            if not record:
                raise ApiError(409,"Idempotency request conflict")
            if record.payload_hash != fingerprint:
                raise ApiError(409,"Idempotency is reused with different payload hash")
            response_body = record.response_body
            response_status = record.response_status
        else:
            preview = db.session.get(TicketType,ticket_type_id)
            if not preview:
                raise ApiError(404,"Ticket type not found")
            event = db.session.scalar(
                select(Event).where(Event.id==preview.event_id).with_for_update()
            )
            ticket_type = db.session.scalar(
                select(TicketType).where(TicketType.id==ticket_type_id).with_for_update().execution_options(populate_existing=True)
            )
            if not event or not ticket_type:
                raise ApiError(404,"Ticket type not found")
            if event.status != "published":
                raise ApiError(409,"Event is not published")
            now = utc_now()
            if now >= event.start_at:
                raise ApiError(409,"Event has started")
            if not ticket_type.sale_start<=now<=ticket_type.sale_end:
                raise ApiError(409,"Ticket sale not active")
            available = ticket_type.total_stock-ticket_type.reserved_stock-ticket_type.sold_stock
            if quantity > available:
                raise ApiError(409,"Insufficient stock")
            #satu user hanya boleh punya satu pending order per event
            pending = db.session.scalar(
                select(Order.id).where(Order.user_id==user_id,Order.event_id==event.id,Order.status=="pending").limit(1)
            )
            if pending:
                raise ApiError(409,"You already have pending order on this event")
            #batas 5 tiket dihitung dari semua jenis tiket (baik confirmed maupun pending)
            existing_quantity = db.session.scalar(
                select(func.coalesce(func.sum(Order.quantity),0)).where(
                    Order.user_id==user_id,Order.event_id==event.id,Order.status.in_(["pending","confirmed"])
                )
            )
            if existing_quantity + quantity > 5:
                raise ApiError(409,"Maximum 5 tickets per event")
            #reservasi stok dilakukan dalam transaksi yang sama dnegan pembuatan order.
            ticket_type.reserved_stock += quantity
            order = Order(
                user_id=user_id,
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                quantity=quantity,
                total_price=ticket_type.price*quantity,
                status="pending",
            )
            db.session.add(order)
            db.session.flush()
            record_audit(action="ORDER_CREATED",target_id=order.id)
            response_body={
                "message":"Order created. Awaiting approval",
                "order": order_to_dict(order)
            }
            response_status=201
            record = db.session.get(IdempotencyRecord,new_record_id)
            record.response_body=response_body
            record.response_status=response_status
    return response_body, response_status

#Get order(User)
#user hanya dapat melihat pesanannya sendiri.
@order_bp.get("/orders/me")
@role_required("user")
def my_orders():
    orders = db.session.scalars(
        select(Order).where(Order.user_id == current_user_id()).order_by(Order.created_at.desc())
    ).all()
    return{"orders":[order_to_dict(order) for order in orders]},200

#Get specific order
@order_bp.get("/orders/<int:order_id>")
@jwt_required()
def get_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        raise ApiError(404, "Order not found")
    event = db.session.get(Event, order.event_id)
    require_order_access(order,event)
    return {"order":order_to_dict(order)}, 200

#Get list orders (organizer)
#organizer hanya bisa melihat order dari event miliknya sendiri.
@order_bp.get("/organizer/orders")
@role_required("organizer")
def organizer_orders():
    status = request.args.get("status")
    query = (
        select(Order).join(Event, Order.event_id == Event.id).where(Event.organizer_id == current_user_id())
    )
    if status:
        allowed_status={
            "pending",
            "confirmed",
            "rejected",
            "canceled"
        }
        if status not in allowed_status:
            raise ApiError(409,"Invalid order status")
        query=query.where(Order.status==status)
    orders = db.session.scalars(
        query.order_by(Order.created_at.desc())
    ).all()
    return{"orders":[order_to_dict(order) for order in orders]},200

#Cancel order
#HANYA pending order yang boleh dibatalkan. Reserved stock dikembalikan tepat satu kali.
@order_bp.patch("/orders/<int:order_id>/cancel")
@role_required("user")
def cancel_order(order_id):
    with db.session.begin():
        event, ticket_type, order = lock_order_resources(order_id)
        if order.user_id != current_user_id():
            raise ApiError(403,"Forbidden")
        if order.status != "pending":
            raise ApiError(409,"Order cant be canceled")
        ticket_type.reserved_stock -= order.quantity
        order.status = ("canceled")
        result = order_to_dict(order)
    return{"message":"Order canceled","order":result},200

#Validasi organizer
#agar seluruh pemindahan stok dan penerbitan tiket berlangsung dalam satu transaksi postgresql
@order_bp.patch("/orders/<int:order_id>/validate")
@limiter.limit("20 per minute",key_func=verified_user_key)
@role_required("organizer")
def validate_order(order_id):
    data = require_json()
    action = data.get('action')
    if action not in ("approve","reject"):
        raise ApiError(400,"You can only either approve or reject")
    reason = None
    if action =="reject":
        reason=text_field(
            data.get("rejection_reason"),"rejection_reason",1000
        )
    with db.session.begin():
        event,ticket_type,order = lock_order_resources(order_id)
        require_event_owner(event)
        if event.status != "published":
            raise ApiError(409,"Event is not published")
        if order.status != "pending":
            raise ApiError(409,"Order has already been processed")
        now = utc_now()
        if action == "approve":
            if now >= event.start_at:
                raise ApiError(409,"Event has started")
            if ticket_type.reserved_stock < order.quantity:
                raise ApiError(409,"Inconsistent reserved stock")
            ticket_type.reserved_stock -= order.quantity
            ticket_type.sold_stock += order.quantity

            order.status = "confirmed"
            order.validated_by = current_user_id()
            order.validated_at = now
            #setiap tiket individual mendapat kode unik.
            for _ in range(order.quantity):
                unique_code=("EVT-"+secrets.token_hex(12).upper())
                issued = IssuedTicket(order_id=order_id,ticket_code=unique_code,status="valid")
                db.session.add(issued)
            message = "order approved and tickets issued"
            record_audit(action="ORDER_APPROVED",target_id=order.id)
        else:
            if ticket_type.reserved_stock < order.quantity:
                raise ApiError(409,"Inconsistent reserved stock")
            ticket_type.reserved_stock -= order.quantity
            order.status = "rejected"
            order.rejection_reason = reason
            order.validated_by = current_user_id()
            order.validated_at = now
            message = "order rejected"
            record_audit(action="ORDER_REJECTED", target_id=order.id)
        result = order_to_dict(order)
    return{"message":message,"order":result},200

