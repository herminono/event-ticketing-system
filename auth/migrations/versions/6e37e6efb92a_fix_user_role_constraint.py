"""Fix user role constraint

Revision ID: 6e37e6efb92a
Revises: cc0cf18e61d2
Create Date: 2026-11-22 21:43:44.743785

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e37e6efb92a'
down_revision = 'cc0cf18e61d2'
branch_labels = None
depends_on = None



def upgrade():
    # Menghapus constraint role yang salah.
    op.drop_constraint(
        "ck_user_role",
        "users",
        type_="check"
    )

    # Membuat constraint role yang benar.
    op.create_check_constraint(
        "ck_user_role",
        "users",
        "role IN ('user', 'organizer')"
    )


def downgrade():
    # Mengembalikan constraint ke versi sebelumnya.
    op.drop_constraint(
        "ck_user_role",
        "users",
        type_="check"
    )

    op.create_check_constraint(
        "ck_user_role",
        "users",
        "role IN ('users', 'organizer')"
    )
