from datetime import datetime, timezone

from .extensions import db


def utc_now():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PipelineSetting(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    value = db.Column(db.String(500), nullable=False)


class ModelCatalog(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True, index=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    family = db.Column(db.String(120), nullable=True)
    size_label = db.Column(db.String(40), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    source_url = db.Column(db.String(500), nullable=True)
    recommended = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=100)


class DataSource(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    source_type = db.Column(db.String(80), nullable=False, default="manual")
    location = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    chunks = db.relationship(
        "DocumentChunk", back_populates="data_source", cascade="all, delete-orphan"
    )


class DocumentChunk(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_source_id = db.Column(
        db.Integer, db.ForeignKey("data_source.id"), nullable=False, index=True
    )
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    token_count = db.Column(db.Integer, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

    data_source = db.relationship("DataSource", back_populates="chunks")
    embeddings = db.relationship(
        "EmbeddingRecord", back_populates="chunk", cascade="all, delete-orphan"
    )


class EmbeddingRecord(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chunk_id = db.Column(
        db.Integer, db.ForeignKey("document_chunk.id"), nullable=False, index=True
    )
    provider = db.Column(db.String(80), nullable=False)
    model = db.Column(db.String(160), nullable=False)
    dimensions = db.Column(db.Integer, nullable=True)
    vector_ref = db.Column(db.String(500), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

    chunk = db.relationship("DocumentChunk", back_populates="embeddings")


class Prompt(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    purpose = db.Column(db.String(255), nullable=True)
    template = db.Column(db.Text, nullable=False)
    input_schema_json = db.Column(db.JSON, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)

    runs = db.relationship(
        "PromptRun", back_populates="prompt", cascade="all, delete-orphan"
    )


class PromptRun(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prompt_id = db.Column(db.Integer, db.ForeignKey("prompt.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=True)
    provider = db.Column(db.String(80), nullable=True)
    model = db.Column(db.String(160), nullable=True)
    input_json = db.Column(db.JSON, nullable=True)
    response_text = db.Column(db.Text, nullable=True)
    response_json = db.Column(db.JSON, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    token_count = db.Column(db.Integer, nullable=True)

    prompt = db.relationship("Prompt", back_populates="runs")
    artifacts = db.relationship(
        "RunArtifact", back_populates="run", cascade="all, delete-orphan"
    )
    evaluations = db.relationship(
        "RunEvaluation", back_populates="run", cascade="all, delete-orphan"
    )


class RunArtifact(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prompt_run_id = db.Column(
        db.Integer, db.ForeignKey("prompt_run.id"), nullable=False, index=True
    )
    label = db.Column(db.String(160), nullable=False)
    artifact_type = db.Column(db.String(80), nullable=False)
    path = db.Column(db.String(500), nullable=True)
    content_text = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

    run = db.relationship("PromptRun", back_populates="artifacts")


class RunEvaluation(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prompt_run_id = db.Column(
        db.Integer, db.ForeignKey("prompt_run.id"), nullable=False, index=True
    )
    evaluator = db.Column(db.String(160), nullable=False)
    metric = db.Column(db.String(120), nullable=False)
    score = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    rubric_json = db.Column(db.JSON, nullable=True)

    run = db.relationship("PromptRun", back_populates="evaluations")
