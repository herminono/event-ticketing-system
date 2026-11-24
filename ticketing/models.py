from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import ForeignKey, UniqueConstraint, CheckConstraint,Index,text
from sqlalchemy.orm import Mapped, mapped_column
from extensions import db

def utc_now():
    return datetime.now(timezone.utc)

#tabel events
class Event(db.Model):
    __tablename__ = 'events'
    id:Mapped[int] = mapped_column(primary_key=True)
    organizer_id:Mapped[int] = mapped_column(index=True,nullable=False)
    title:Mapped[str] = mapped_column(db.String(150),nullable=False)
    description:Mapped[str] = mapped_column(db.Text, nullable=False)
    category: Mapped[str]=mapped_column(db.String(50), nullable=False)
    event_type:Mapped[str] = mapped_column(db.String(20),nullable=False)
    location: Mapped[str|None] = mapped_column(db.String(225),nullable=True)
    meeting_url: Mapped[str|None] = mapped_column(db.String(500), nullable=True)
    start_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),nullable=False)
    end_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),nullable=False)
    status:Mapped[str]=mapped_column(db.String(20),default="draft",nullable=False)
    created_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)

    __table_args__ =(
        CheckConstraint(
            "event_type IN ('online','offline')",
            name="ck_event_type"
        ),
        CheckConstraint(
            "status IN ('draft','published', 'canceled')",
            name="ck_event_status"
        ),
        CheckConstraint(
            "end_at>start_at",
            name="ck_event_dates"
        ),
    )

#jenis jenis tiket
class TicketType(db.Model):
    __tablename__ = 'ticket_types'
    id:Mapped[int]=mapped_column(primary_key=True)
    event_id:Mapped[int]=mapped_column(ForeignKey("events.id"),index=True,nullable=False)
    name:Mapped[str]=mapped_column(db.String(50),nullable=False)
    price:Mapped[Decimal] = mapped_column(db.Numeric(12,2),nullable=False)
    total_stock: Mapped[int]=mapped_column(nullable=False)
    reserved_stock:Mapped[int]=mapped_column(default=0,nullable=False)
    sold_stock:Mapped[int] = mapped_column(default=0,nullable=False)
    sale_start:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),nullable=False)
    sale_end:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),nullable=False)

    __table_args__=(
        UniqueConstraint(
            "event_id","name",name="uq_event_ticket_name"
        ),
        CheckConstraint(
            "price >=0", name="ck_ticket_price"
        ),
        CheckConstraint(
            "total_stock>=0",
            name="ck_total_stock"
        ),
        CheckConstraint(
            "reserved_stock>=0",
            name="ck_reserved_stock"
        ),
        CheckConstraint(
            "sold_stock>=0",
            name="ck_sold_stock"
        ),
        CheckConstraint(
            "reserved_stock+sold_stock <= total_stock",
            name="ck_stock_capacity"
        ),
        CheckConstraint(
            "sale_end >= sale_start",
            name="ck_ticket_sale_dates"
        ),
    )
#tabel orders
class Order(db.Model):
    __tablename__ = 'orders'
    id:Mapped[int]=mapped_column(primary_key=True)
    #id dari auth
    user_id: Mapped[int]=mapped_column(index=True,nullable=False)
    event_id:Mapped[int]=mapped_column(ForeignKey("events.id"),nullable=False,index=True)
    ticket_type_id:Mapped[int]=mapped_column(ForeignKey("ticket_types.id"),nullable=False)
    quantity:Mapped[int]=mapped_column(nullable=False)
    total_price:Mapped[Decimal]=mapped_column(db.Numeric(13,2),nullable=False)
    status:Mapped[str]=mapped_column(db.String(20),default="pending",nullable=False)
    rejection_reason:Mapped[str|None]=mapped_column(db.Text,nullable=True)
    validated_at:Mapped[datetime|None]=mapped_column(db.DateTime(timezone=True),nullable=True)
    validated_by: Mapped[int|None]= mapped_column(nullable=True)
    created_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)
    expires_at:Mapped[datetime] = mapped_column(db.DateTime(timezone=True),nullable=False)
    __table_args__ =(
        CheckConstraint(
            "quantity>0",
            name="ck_order_quantity"
        ),
        CheckConstraint(
            "total_price>=0",
            name="ck_order_total"
        ),
        CheckConstraint(
            "status IN ('pending','confirmed','rejected','canceled','expired')",
            name="ck_order_status"
        ),
        #satu user hanya boleh punya satu pending order dalam satu event.
        Index(
            "uq_pending_order_per_user_event",
            "user_id","event_id",
            unique=True,
            postgresql_where=text("status ='pending'")
        ),
        Index(
            "ix_pending_order_expiration",
            "expires_at",
            "event_id",
            postgresql_where=text("status='pending'")
        )
    )

#Issued tickets, row baru ditambahkan ketika organizer sudah approve order.
class IssuedTicket(db.Model):
    __tablename__ = 'issued_tickets'
    id:Mapped[int]=mapped_column(primary_key=True)
    order_id:Mapped[int]=mapped_column(ForeignKey("orders.id"),nullable=False,index=True)
    ticket_code: Mapped[str]=mapped_column(db.String(40),unique=True,nullable=False)
    status: Mapped[str]=mapped_column(db.String(20),default="valid",nullable=False)
    issued_at: Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)
    checked_in_at: Mapped[datetime|None]=mapped_column(db.DateTime(timezone=True))

    __table_args__ =(
        CheckConstraint(
            "status IN ('valid','used','invalid')",
            name="ck_issued_ticket_status"
        ),
    )

#Idempotency, agar kombinasi user, opration, dan key menjadi wajib unik.
class IdempotencyRecord(db.Model):
    __tablename__ = 'idempotency_records'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(nullable=False)
    operation: Mapped[str]=mapped_column(db.String(50),nullable=False)
    idem_key:Mapped[str]=mapped_column(db.String(80),nullable=False)
    payload_hash:Mapped[str]=mapped_column(db.String(64),nullable=False)
    response_body:Mapped[dict]=mapped_column(db.JSON,nullable=False)
    response_status:Mapped[int]=mapped_column(nullable=False)
    created_at: Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)
    __table_args__ =(
        UniqueConstraint(
            "user_id", "operation","idem_key",
            name="uq_idempotency_key"
        ),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False,index=True)
    action: Mapped[str] = mapped_column(db.String(50),nullable=False)
    target_id: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)

