"""Add model catalog and seed suggested models.

Revision ID: 0003_model_catalog
Revises: 0002_pipeline_settings
Create Date: 2026-05-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "0003_model_catalog"
down_revision = "0002_pipeline_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("family", sa.String(length=120), nullable=True),
        sa.Column("size_label", sa.String(length=40), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("recommended", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_model_catalog_kind"), "model_catalog", ["kind"], unique=False)
    op.create_index(op.f("ix_model_catalog_name"), "model_catalog", ["name"], unique=True)

    model_catalog = sa.table(
        "model_catalog",
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
        sa.column("family", sa.String),
        sa.column("size_label", sa.String),
        sa.column("size_bytes", sa.BigInteger),
        sa.column("notes", sa.Text),
        sa.column("source_url", sa.String),
        sa.column("recommended", sa.Boolean),
        sa.column("active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        model_catalog,
        [
            {
                "name": "llama3.2:3b",
                "kind": "generation",
                "family": "Llama 3.2",
                "size_label": "2.0GB",
                "size_bytes": 2_000_000_000,
                "notes": "Good all-round small chat model for RAG and summarization.",
                "source_url": "https://ollama.com/library/llama3.2",
                "recommended": True,
                "active": True,
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "llama3.2:1b",
                "kind": "generation",
                "family": "Llama 3.2",
                "size_label": "1.3GB",
                "size_bytes": 1_300_000_000,
                "notes": "Very light option when you want fast local iteration.",
                "source_url": "https://ollama.com/library/llama3.2",
                "recommended": False,
                "active": True,
                "sort_order": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "gemma3:1b",
                "kind": "generation",
                "family": "Gemma 3",
                "size_label": "815MB",
                "size_bytes": 815_000_000,
                "notes": "Tiny and handy for quick answer-style comparisons.",
                "source_url": "https://ollama.com/library/gemma3",
                "recommended": False,
                "active": True,
                "sort_order": 2,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "gemma3:4b",
                "kind": "generation",
                "family": "Gemma 3",
                "size_label": "3.3GB",
                "size_bytes": 3_300_000_000,
                "notes": "Strong small model if your machine can comfortably hold it.",
                "source_url": "https://ollama.com/library/gemma3",
                "recommended": True,
                "active": True,
                "sort_order": 3,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "qwen2.5:3b",
                "kind": "generation",
                "family": "Qwen 2.5",
                "size_label": "1.9GB",
                "size_bytes": 1_900_000_000,
                "notes": "Worth trying when you want stronger structured output behavior.",
                "source_url": "https://ollama.com/library/qwen2.5",
                "recommended": True,
                "active": True,
                "sort_order": 4,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "qwen2.5:1.5b",
                "kind": "generation",
                "family": "Qwen 2.5",
                "size_label": "986MB",
                "size_bytes": 986_000_000,
                "notes": "Small multilingual option with low download cost.",
                "source_url": "https://ollama.com/library/qwen2.5",
                "recommended": False,
                "active": True,
                "sort_order": 5,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "nomic-embed-text",
                "kind": "embedding",
                "family": "Nomic",
                "size_label": "274MB",
                "size_bytes": 274_000_000,
                "notes": "Good default embedding model and already a strong fit for this app.",
                "source_url": "https://ollama.com/library/nomic-embed-text",
                "recommended": True,
                "active": True,
                "sort_order": 0,
                "created_at": now,
                "updated_at": now,
            },
            {
                "name": "mxbai-embed-large",
                "kind": "embedding",
                "family": "Mixedbread",
                "size_label": "670MB",
                "size_bytes": 670_000_000,
                "notes": "A heavier but stronger embedding option for retrieval experiments.",
                "source_url": "https://ollama.com/library/mxbai-embed-large",
                "recommended": True,
                "active": True,
                "sort_order": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade():
    op.drop_index(op.f("ix_model_catalog_name"), table_name="model_catalog")
    op.drop_index(op.f("ix_model_catalog_kind"), table_name="model_catalog")
    op.drop_table("model_catalog")
