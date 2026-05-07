"""Add ingestion presets and ingestion runs.

Revision ID: 0004_ingestion_presets
Revises: 0003_model_catalog
Create Date: 2026-05-07 00:00:00.000000
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0004_ingestion_presets"
down_revision = "0003_model_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_preset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_preset_name"), "ingestion_preset", ["name"], unique=True)

    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ingestion_preset_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("docs_path", sa.String(length=500), nullable=False),
        sa.Column("collection", sa.String(length=255), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("files_count", sa.Integer(), nullable=False),
        sa.Column("doc_units_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("embedding_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_preset_id"], ["ingestion_preset.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_run_collection"), "ingestion_run", ["collection"], unique=False)
    op.create_index(op.f("ix_ingestion_run_ingestion_preset_id"), "ingestion_run", ["ingestion_preset_id"], unique=False)

    preset_table = sa.table(
        "ingestion_preset",
        sa.column("name", sa.String),
        sa.column("purpose", sa.String),
        sa.column("config_json", sa.JSON),
        sa.column("version", sa.Integer),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        preset_table,
        [
            {
                "name": "Balanced Default",
                "purpose": "General-purpose chunking with fixed windows and moderate overlap.",
                "config_json": {
                    "split_strategy": "fixed",
                    "chunk_chars": 1200,
                    "overlap_chars": 200,
                    "min_chunk_chars": 200,
                    "pdf_mode": "page",
                },
                "version": 1,
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Smaller Retrieval Units",
                "purpose": "Use sentence-aware chunking for tighter retrieval matches and faster scanning.",
                "config_json": {
                    "split_strategy": "sentence",
                    "chunk_chars": 800,
                    "overlap_chars": 120,
                    "min_chunk_chars": 120,
                    "pdf_mode": "page",
                },
                "version": 1,
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "Broader Context",
                "purpose": "Use paragraph-aware chunking and document-level PDF flow for richer surrounding context.",
                "config_json": {
                    "split_strategy": "paragraph",
                    "chunk_chars": 1600,
                    "overlap_chars": 240,
                    "min_chunk_chars": 240,
                    "pdf_mode": "document",
                },
                "version": 1,
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade():
    op.drop_index(op.f("ix_ingestion_run_ingestion_preset_id"), table_name="ingestion_run")
    op.drop_index(op.f("ix_ingestion_run_collection"), table_name="ingestion_run")
    op.drop_table("ingestion_run")
    op.drop_index(op.f("ix_ingestion_preset_name"), table_name="ingestion_preset")
    op.drop_table("ingestion_preset")
