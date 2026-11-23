from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, UniqueConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from extensions import db

def utc_now():
    return datetime.now(timezone.utc)

#Buat tabel user
class User(db.Model):
    __tablename__ = 'users'
    id:Mapped[int]=mapped_column(primary_key=True)
    username:Mapped[str]=mapped_column(db.String(32),unique=True, nullable=False)
    email:Mapped[str]=mapped_column(db.String(300),unique=True, nullable=False)
    password_hash:Mapped[str]=mapped_column(db.String(300), nullable=False)
    role:Mapped[str]=mapped_column(db.String(20),nullable=False)
    created_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)

    __table_args__ = (
        CheckConstraint("role IN('user','organizer')", name="ck_user_role"),
    )

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'
    id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),index=True,nullable=False)
    token_hash: Mapped[str]=mapped_column(db.String(64),unique=True,nullable=False)
    expires_at: Mapped[datetime]= mapped_column(db.DateTime(timezone=True),nullable=False)
    used_at: Mapped[datetime|None]= mapped_column(db.DateTime(timezone=True),nullable=True)

#mencegah bruteforce login dan menyimpan jumlah request dalam suatu periode.
class RateBucket(db.Model):
    __tablename__ = 'rate_bucket'
    id:Mapped[int]=mapped_column(primary_key=True)
    scope:Mapped[str]=mapped_column(db.String(40),nullable=False)
    key_hash: Mapped[str]=mapped_column(db.String(64),nullable=False)
    hits:Mapped[int]=mapped_column(default=0,nullable=False)
    started_at:Mapped[datetime]=mapped_column(db.DateTime(timezone=True),default=utc_now,nullable=False)

    __table_args__ =(
        UniqueConstraint("scope","key_hash",name="uq_rate_bucket_scope_key"),
    )