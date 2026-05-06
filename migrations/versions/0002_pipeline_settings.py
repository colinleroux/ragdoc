"""Add pipeline settings table.

Revision ID: 0002_pipeline_settings
Revises: 0001_initial
Create Date: 2026-05-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_pipeline_settings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pipeline_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_setting_key"), "pipeline_setting", ["key"], unique=True
    )


def downgrade():
    op.drop_index(op.f("ix_pipeline_setting_key"), table_name="pipeline_setting")
    op.drop_table("pipeline_setting")
