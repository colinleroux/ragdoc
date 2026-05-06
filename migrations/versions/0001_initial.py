"""Create initial RAG playground tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "data_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "document_chunk",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_source_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_source.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_chunk_data_source_id"),
        "document_chunk",
        ["data_source_id"],
        unique=False,
    )
    op.create_table(
        "prompt_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompt.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prompt_run_prompt_id"), "prompt_run", ["prompt_id"], unique=False
    )
    op.create_table(
        "embedding_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("vector_ref", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunk.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_embedding_record_chunk_id"),
        "embedding_record",
        ["chunk_id"],
        unique=False,
    )
    op.create_table(
        "run_artifact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_run_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_run_id"], ["prompt_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_run_artifact_prompt_run_id"),
        "run_artifact",
        ["prompt_run_id"],
        unique=False,
    )
    op.create_table(
        "run_evaluation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_run_id", sa.Integer(), nullable=False),
        sa.Column("evaluator", sa.String(length=160), nullable=False),
        sa.Column("metric", sa.String(length=120), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("rubric_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["prompt_run_id"], ["prompt_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_run_evaluation_prompt_run_id"),
        "run_evaluation",
        ["prompt_run_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_run_evaluation_prompt_run_id"), table_name="run_evaluation")
    op.drop_table("run_evaluation")
    op.drop_index(op.f("ix_run_artifact_prompt_run_id"), table_name="run_artifact")
    op.drop_table("run_artifact")
    op.drop_index(op.f("ix_embedding_record_chunk_id"), table_name="embedding_record")
    op.drop_table("embedding_record")
    op.drop_index(op.f("ix_prompt_run_prompt_id"), table_name="prompt_run")
    op.drop_table("prompt_run")
    op.drop_index(op.f("ix_document_chunk_data_source_id"), table_name="document_chunk")
    op.drop_table("document_chunk")
    op.drop_table("prompt")
    op.drop_table("data_source")
