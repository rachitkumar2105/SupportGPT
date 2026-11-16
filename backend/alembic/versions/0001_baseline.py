"""Baseline schema for SupportGPT v4.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-16

The baseline is created from the ORM metadata (checkfirst, so it is safe on a
database that already has some tables). Every later schema change gets its own
explicit migration file.
"""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app import models  # noqa: F401  (registers tables)
    from app.db import Base

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
