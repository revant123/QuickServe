"""add rider role

Revision ID: a1b795687269
Revises: 1a9f95710308
Create Date: 2026-11-17 09:22:11

Written by hand: Alembic's autogenerate does NOT notice a new value added to a
Python Enum, so `alembic revision --autogenerate` would have produced an empty
migration and production would crash the first time someone signed up as a rider.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b795687269"
down_revision: str | Sequence[str] | None = "1a9f95710308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adding a value to a PostgreSQL ENUM is quick and safe on a live table.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'RIDER' BEFORE 'ADMIN'")


def downgrade() -> None:
    # PostgreSQL can't remove a value from an ENUM, so we rebuild the type.
    # We refuse to run if riders exist: silently turning them into customers
    # (or deleting them) during a rollback would be data loss nobody asked for.
    bind = op.get_bind()
    riders = bind.execute(sa.text("SELECT count(*) FROM users WHERE role = 'RIDER'")).scalar_one()
    if riders:
        raise RuntimeError(f"{riders} rider account(s) exist; reassign or remove them before downgrading")
    op.execute("ALTER TYPE user_role RENAME TO user_role_old")
    op.execute("CREATE TYPE user_role AS ENUM ('CUSTOMER', 'RESTAURANT_OWNER', 'ADMIN')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role")
    op.execute("DROP TYPE user_role_old")
