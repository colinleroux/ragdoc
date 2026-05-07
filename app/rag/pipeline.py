from typing import Any, Dict, List

from ..errors import AppError
from ..extensions import db
from ..ingestion_presets import get_active_ingestion_preset, ingestion_run_payload, latest_ingestion_run, preset_defaults
from ..models import DataSource, DocumentChunk, EmbeddingRecord, IngestionRun
from .chunking import chunk_text, content_hash, estimate_token_count, stable_id
from .embeddings import ollama_embed
from .loaders import read_docs, relative_source_path
from .vector_store import ensure_collection_ready, qdrant_delete_collection, qdrant_delete_sources, qdrant_upsert


def _source_doc_type(docs: List[Dict[str, Any]], source: str, docs_path: str) -> str:
    for doc in docs:
        if relative_source_path(doc["path"], docs_path) == source:
            return doc.get("kind", "text")
    return "text"


def _replace_data_sources(sources: List[str], docs: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, DataSource]:
    if sources:
        for existing in DataSource.query.filter(DataSource.location.in_(sources)).all():
            db.session.delete(existing)
        db.session.flush()

    source_records: Dict[str, DataSource] = {}
    for source in sorted(sources, key=str.lower):
        record = DataSource(
            name=source,
            source_type=_source_doc_type(docs, source, cfg["DOCS_PATH"]),
            location=source,
            description=f"Ingested from {cfg['DOCS_PATH']}",
        )
        db.session.add(record)
        source_records[source] = record

    db.session.flush()
    return source_records


def ingest_docs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    ensure_collection_ready(cfg)
    preset = get_active_ingestion_preset()
    preset_cfg = preset_defaults(preset)
    docs = read_docs(cfg["DOCS_PATH"], pdf_mode=preset_cfg["pdf_mode"])
    if not docs:
        raise AppError(f"No .txt or .md or .pdf files found under {cfg['DOCS_PATH']}.", 400)

    sources = sorted({relative_source_path(doc["path"], cfg["DOCS_PATH"]) for doc in docs})
    points: List[Dict[str, Any]] = []
    chunk_count = 0

    try:
        qdrant_delete_sources(sources, cfg)
        source_records = _replace_data_sources(sources, docs, cfg)

        for doc in docs:
            source = relative_source_path(doc["path"], cfg["DOCS_PATH"])
            page_num = doc.get("page")
            doc_type = doc.get("kind", "text")
            source_record = source_records[source]

            for index, chunk in enumerate(
                chunk_text(
                    doc["text"],
                    chunk_chars=preset_cfg["chunk_chars"],
                    overlap=preset_cfg["overlap_chars"],
                    split_strategy=preset_cfg["split_strategy"],
                    min_chunk_chars=preset_cfg["min_chunk_chars"],
                )
            ):
                chunk_count += 1
                chunk_hash = content_hash(chunk)
                vector = ollama_embed(chunk, cfg)
                point_id = stable_id(f"{source}:{doc_type}:{page_num}:{index}:{chunk_hash}")

                chunk_record = DocumentChunk(
                    data_source=source_record,
                    chunk_index=index,
                    content=chunk,
                    token_count=estimate_token_count(chunk),
                    metadata_json={
                        "source": source,
                        "page": page_num,
                        "doc_type": doc_type,
                        "content_hash": chunk_hash,
                        "ingestion_preset_id": preset.id,
                        "ingestion_preset_name": preset.name,
                        "split_strategy": preset_cfg["split_strategy"],
                    },
                )
                db.session.add(chunk_record)
                db.session.flush()

                vector_ref = f"qdrant:{cfg['COLLECTION_NAME']}:{point_id}"
                db.session.add(
                    EmbeddingRecord(
                        chunk=chunk_record,
                        provider="ollama",
                        model=cfg["EMBED_MODEL"],
                        dimensions=len(vector),
                        vector_ref=vector_ref,
                        metadata_json={"point_id": point_id, "collection": cfg["COLLECTION_NAME"]},
                    )
                )

                points.append(
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            "source": source,
                            "page": page_num,
                            "doc_type": doc_type,
                            "chunk_index": index,
                            "text": chunk,
                            "data_source_id": source_record.id,
                            "document_chunk_id": chunk_record.id,
                            "content_hash": chunk_hash,
                        },
                    }
                )

        for index in range(0, len(points), 64):
            qdrant_upsert(points[index : index + 64], cfg)

        run = IngestionRun(
            preset=preset,
            name=f"{preset.name} ingest",
            docs_path=cfg["DOCS_PATH"],
            collection=cfg["COLLECTION_NAME"],
            config_json=preset_cfg,
            files_count=len(sources),
            doc_units_count=len(docs),
            chunk_count=chunk_count,
            embedding_count=len(points),
        )
        db.session.add(run)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "files": len(sources),
        "doc_units": len(docs),
        "chunks": chunk_count,
        "embeddings": len(points),
        "collection": cfg["COLLECTION_NAME"],
        "ledger": "sqlite",
        "ingestion_preset": {
            "id": preset.id,
            "name": preset.name,
            "config": preset_cfg,
        },
        "ingestion_run": ingestion_run_payload(run),
    }


def list_ingested_docs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    docs: List[Dict[str, Any]] = []
    for source in DataSource.query.order_by(DataSource.name.asc()).all():
        pages = set()
        for chunk in source.chunks:
            metadata = chunk.metadata_json or {}
            page = metadata.get("page")
            if isinstance(page, int):
                pages.add(page)

        docs.append(
            {
                "source": source.location or source.name,
                "name": source.name,
                "source_type": source.source_type,
                "chunks": len(source.chunks),
                "embeddings": sum(len(chunk.embeddings) for chunk in source.chunks),
                "pages": sorted(pages),
                "page_count": len(pages),
            }
        )

    latest_run = latest_ingestion_run(cfg["COLLECTION_NAME"])
    return {
        "collection": cfg["COLLECTION_NAME"],
        "docs": docs,
        "count": len(docs),
        "ledger": "sqlite",
        "latest_ingestion_run": ingestion_run_payload(latest_run),
    }


def reset_ingestion(cfg: Dict[str, Any]) -> Dict[str, Any]:
    source_count = DataSource.query.count()
    chunk_count = DocumentChunk.query.count()
    embedding_count = EmbeddingRecord.query.count()

    try:
        for source in DataSource.query.all():
            db.session.delete(source)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    collection_deleted = qdrant_delete_collection(cfg)
    return {
        "ok": True,
        "sources_deleted": source_count,
        "chunks_deleted": chunk_count,
        "embeddings_deleted": embedding_count,
        "collection": cfg["COLLECTION_NAME"],
        "collection_deleted": collection_deleted,
        "ledger": "sqlite",
    }


def delete_ingested_source(source_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    source_name = (source_name or "").strip()
    if not source_name:
        raise AppError("source is required.", 400)

    source = DataSource.query.filter(
        (DataSource.location == source_name) | (DataSource.name == source_name)
    ).first()
    if source is None:
        raise AppError(f"Ingested source not found: {source_name}", 404)

    chunk_count = len(source.chunks)
    embedding_count = sum(len(chunk.embeddings) for chunk in source.chunks)

    try:
        qdrant_delete_sources([source.location or source.name], cfg)
        db.session.delete(source)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "ok": True,
        "source": source.location or source.name,
        "chunks_deleted": chunk_count,
        "embeddings_deleted": embedding_count,
        "ledger": "sqlite",
        "collection": cfg["COLLECTION_NAME"],
    }
