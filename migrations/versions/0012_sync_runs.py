"""sync_runs: журнал синхронизаций остатков с CarSale

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="carsale"),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="schedule"),  # schedule | manual
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),  # running | ok | failed
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dealers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pieces", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("sync_runs")
