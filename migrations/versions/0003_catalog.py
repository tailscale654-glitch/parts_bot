"""catalog: models, nodes, parts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _names(length: int) -> list[sa.Column]:
    return [
        sa.Column("name_ru", sa.String(length), nullable=False),
        sa.Column("name_en", sa.String(length)),
        sa.Column("name_uz", sa.String(length)),
    ]


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_names(128),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("name_ru", name="uq_models_name_ru"),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_names(128),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("name_ru", name="uq_nodes_name_ru"),
    )
    op.create_table(
        "parts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        *_names(255),
        sa.Column("part_number", sa.String(64), nullable=False),
        sa.Column("description_ru", sa.Text()),
        sa.Column("description_en", sa.Text()),
        sa.Column("description_uz", sa.Text()),
        sa.Column("photo", sa.String(512)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("model_id", "part_number", name="uq_parts_model_part_number"),
    )
    op.create_index("ix_parts_model_id", "parts", ["model_id"])
    op.create_index("ix_parts_node_id", "parts", ["node_id"])
    op.create_index("ix_parts_part_number", "parts", ["part_number"])


def downgrade() -> None:
    op.drop_table("parts")
    op.drop_table("nodes")
    op.drop_table("models")
