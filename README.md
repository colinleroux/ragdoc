# RagDoc

RagDoc is a document-focused RAG pipeline and playground for exploring reusable AI pipeline code.

- App factory + blueprints (`main` and `api`)
- RAG topic pages for data loading, data chunking, embedding, and storing
- Prompt experiment storage for prompts, model runs, artifacts, and evaluations
- Phase-1 RAG service layer for Ollama embeddings/generation and Qdrant retrieval
- SQLite by default, created from migrations at startup (`instance/app.db`)
- Docker Compose support (`ollama` + `qdrant` + `web` + `nginx`)
- Tailwind + Vite + Alpine frontend pipeline

## Quick start (Docker)

```bash
docker compose build
docker compose up
```

Then open: `http://localhost:8050`

Note: `compose.yaml` currently maps Nginx as `8050:80` so it doesn't clash with existing port 80 usage.
Change that line to `80:80` when you want standard HTTP on host port 80.

The RAG API ingests documents from `./docs` by default. In Docker this is mounted read-only at `/app/docs`, so you can add `.txt`, `.md`, or `.pdf` files without rebuilding the image.

## GPU support

RagDoc itself does not have an app-level "use GPU" switch. GPU use is determined by whether the `ollama` container can see a supported GPU.

- The Flask app does not need a checkbox or special runtime flag for GPU inference.
- Ollama will generally use a GPU automatically if GPU access is available inside the container.
- The important configuration lives at the Docker and host level, not in the Ask UI.

For NVIDIA on Linux, make sure the server has:

- a supported NVIDIA GPU
- current NVIDIA drivers
- the NVIDIA Container Toolkit installed

Official references:

- [Ollama Docker GPU docs](https://docs.ollama.com/docker)
- [Ollama hardware support](https://docs.ollama.com/gpu)
- [Docker Compose GPU support](https://docs.docker.com/compose/gpu-support/)

The base `compose.yaml` is intentionally CPU-safe and portable. For a GPU-enabled server, use a Compose override such as:

```yaml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Then start the stack with:

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up -d
```

This keeps local development simple on machines without a GPU while allowing the server to use GPU acceleration automatically.

Note: Ollama models are not baked into the rebuilt `web` image. They persist in the Docker volume mounted at `/root/.ollama`, so normal rebuilds and container recreation do not force large model re-downloads unless you remove the Docker volume.

## Quick start (local)

```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install
npm run build
flask --app wsgi_app.py db upgrade
python run.py
```

## Migrations

The database is intentionally not committed. A fresh `instance/app.db` is created by running:

```bash
flask --app wsgi_app.py db upgrade
```

## Phase-1 RAG API

The first refactor pass follows the service/API shape in `reference_apps/docker_ai_rag`, with RagDoc's own SQLite models acting as the ingestion ledger:

- `GET /api/health`
- `GET /api/stats`
- `POST /api/setup-models`
- `GET /api/setup-models/stream`
- `GET /api/ingested-docs`
- `POST /api/ingest`
- `POST /api/ask`
- `POST /api/chat`
- `GET /api/find`

Core environment variables:

- `OLLAMA_BASE_URL` (default `http://ollama:11434`)
- `QDRANT_URL` (default `http://qdrant:6333`)
- `MODEL_NAME` (default `dolphin3:latest`)
- `EMBED_MODEL` (default `nomic-embed-text`)
- `COLLECTION_NAME` (default `ragdoc_docs_v1`)
- `DOCS_PATH` (defaults locally to `./docs`; Docker uses `/app/docs`)

Ingestion now writes:

- `DataSource` records for each source file
- `DocumentChunk` records for each chunk
- `EmbeddingRecord` records with Qdrant vector references
- Qdrant payload metadata that links hits back to SQLite source/chunk IDs

When models change, create a migration with:

```bash
flask --app wsgi_app.py db migrate -m "Describe the schema change"
flask --app wsgi_app.py db upgrade
```

## Structure

```text
app/
  api/
  main/
  prompts/
  rag/
    chunking.py
    embeddings.py
    loaders.py
    options.py
    pipeline.py
    retrieval.py
    service.py
    vector_store.py
  templates/
  static/
  __init__.py
  assets.py
  config.py
  errors.py
  extensions.py
  models.py
instance/
migrations/
reference_apps/
  docker_ai_rag/
src/
compose.yaml
Dockerfile
```

## Reference App

`reference_apps/docker_ai_rag/` is a clean snapshot of the earlier working Ollama/Qdrant RAG app. It is kept as reference material only while this project is rebuilt with clearer pipeline boundaries and a removable playground.
