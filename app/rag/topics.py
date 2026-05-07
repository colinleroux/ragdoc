RAG_TOPICS = [
    {
        "slug": "data-loading",
        "title": "Data Loading",
        "summary": "Bring documents, text, URLs, and generated files into a traceable ingestion flow.",
        "focus": [
            "Source registration",
            "File and text ingestion",
            "Metadata capture",
            "Repeatable fixtures",
        ],
        "questions": [
            "Where did this content come from?",
            "Can the same source be loaded again consistently?",
            "What metadata should survive every downstream step?",
        ],
        "tradeoffs": [
            "Page-based PDF ingestion keeps citations clearer, but document mode can preserve broader context.",
            "Metadata that survives ingestion makes later evaluation and troubleshooting far easier.",
        ],
        "cta_label": "Open ingestion settings",
        "cta_href": "/ingestion-settings/",
    },
    {
        "slug": "data-chunking",
        "title": "Data Chunking",
        "summary": "Split source material into retrieval-sized units while preserving useful context.",
        "focus": [
            "Chunk size experiments",
            "Overlap strategy",
            "Structure-aware splitting",
            "Token counting",
        ],
        "questions": [
            "Does each chunk answer one coherent question?",
            "How much overlap improves retrieval before it adds noise?",
            "Which document boundaries should never be split?",
        ],
        "tradeoffs": [
            "Smaller chunks often improve precision, but can starve the model of context.",
            "Larger chunks can help answer synthesis, but may reduce retrieval sharpness and increase noise.",
            "Paragraph and sentence-aware strategies preserve structure better than fixed windows when the corpus is well formatted.",
        ],
        "cta_label": "Experiment with chunking presets",
        "cta_href": "/ingestion-settings/",
    },
    {
        "slug": "embedding",
        "title": "Embedding",
        "summary": "Convert chunks and queries into vectors that can support semantic retrieval.",
        "focus": [
            "Provider/model tracking",
            "Dimension checks",
            "Batching",
            "Embedding refreshes",
        ],
        "questions": [
            "Which model created this vector?",
            "Can embeddings be regenerated after a model change?",
            "How will failed batches be retried safely?",
        ],
        "tradeoffs": [
            "Embedding changes usually require a full re-ingest if you want fair retrieval comparisons.",
        ],
        "cta_label": "Open pipeline setup",
        "cta_href": "/rag/pipeline",
    },
    {
        "slug": "storing",
        "title": "Storing",
        "summary": "Persist sources, chunks, vectors, prompts, responses, and evaluation notes cleanly.",
        "focus": [
            "SQLite records",
            "Vector-store references",
            "Artifact paths",
            "Evaluation history",
        ],
        "questions": [
            "What belongs in SQLite versus a vector store or file store?",
            "How are prompt runs compared later?",
            "Which records must be immutable once evaluated?",
        ],
        "tradeoffs": [
            "Separate stores make each layer clearer, but only if the references between them are easy to inspect.",
        ],
        "cta_label": "Review captured answers",
        "cta_href": "/rag/pipeline",
    },
]


def get_topic(slug):
    return next((topic for topic in RAG_TOPICS if topic["slug"] == slug), None)
