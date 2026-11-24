from sqlalchemy import select
from extensions import db
from models import Event, Order, TicketType
from helpers import ApiError, utc_now

def expire_locked_order(order,ticket_type,now):
    if order.status != "pending":
         return False
    if order.expires_at > now:
        return False
    if ticket_type.reserved_stock < order.quantity:
        raise ApiError(409,"Inconsistent reserved stock")
    ticket_type.reserved_stock -= order.quantity
    order.status = "expired"
    return True

def expire_event_orders(event_id):
    event = db.session.scalar(
        select(Event).where(Event.id==event_id).with_for_update().execution_options(populate_existing=True)
    )
    if not event:
        return 0
    now = utc_now()
    due_filter=(
        Order.event_id==event_id,
        Order.status=="pending",
        Order.expires_at<=now
    )
    ticket_ids=db.session.scalars(
        select(Order.ticket_type_id).where(*due_filter).distinct()
    ).all()
    if not ticket_ids:
        return 0
    ticket_types = db.session.scalars(
        select(TicketType).where(TicketType.id.in_(ticket_ids))
        .order_by(TicketType.id)
        .with_for_update().execution_options(populate_existing=True)
    ).all()
    tickets = {ticket.id: ticket for ticket in ticket_types}
    orders = db.session.scalars(
        select(Order).where(*due_filter)
        .order_by(Order.id).with_for_update().execution_options(populate_existing=True)
    ).all()
    expired_count = 0

    for order in orders:
        ticket=tickets.get(order.ticket_type_id)
        if not ticket:
            raise ApiError(409,"Inconsistent order relationship")
        if expire_locked_order(order,ticket,now):
            expired_count += 1
    db.session.flush()
    return expired_count

def expire_matching_orders(*conditions):
    event_ids = db.session.scalars(
        select(Order.event_id).where(
            Order.status=="pending",
            Order.expires_at<=utc_now(),
            *conditions
        ).distinct().order_by(Order.event_id)
    ).all()
    expired_count = 0
    for event_id in event_ids:
        expired_count += expire_event_orders(event_id)
    return expired_count