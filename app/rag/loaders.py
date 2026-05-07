import glob
import os
from typing import Any, Dict, List

from ..errors import AppError

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def list_corpus_files(docs_path: str) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    if not os.path.isdir(docs_path):
        return {"docs_path": docs_path, "files": files, "count": 0, "supported_extensions": sorted(SUPPORTED_EXTENSIONS)}

    for file_path in glob.glob(os.path.join(docs_path, "**/*"), recursive=True):
        if not os.path.isfile(file_path):
            continue

        extension = os.path.splitext(file_path)[1].lower()
        if extension not in SUPPORTED_EXTENSIONS:
            continue

        stat = os.stat(file_path)
        files.append(
            {
                "source": relative_source_path(file_path, docs_path),
                "extension": extension.lstrip("."),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )

    files.sort(key=lambda item: item["source"].lower())
    return {"docs_path": docs_path, "files": files, "count": len(files), "supported_extensions": sorted(SUPPORTED_EXTENSIONS)}


def read_docs(docs_path: str, pdf_mode: str = "page") -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []

    for ext in ("txt", "md"):
        for file_path in glob.glob(os.path.join(docs_path, f"**/*.{ext}"), recursive=True):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                    files.append({"path": file_path, "text": handle.read(), "kind": "text", "page": None})
            except OSError:
                continue

    for file_path in glob.glob(os.path.join(docs_path, "**/*.pdf"), recursive=True):
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                if pdf_mode == "document":
                    page_texts: List[str] = []
                    for page in pdf.pages:
                        text = (page.extract_text() or "").strip()
                        if text:
                            page_texts.append(text)
                    if page_texts:
                        files.append(
                            {
                                "path": file_path,
                                "text": "\n\n".join(page_texts),
                                "kind": "pdf",
                                "page": None,
                            }
                        )
                else:
                    for page_num, page in enumerate(pdf.pages, start=1):
                        text = (page.extract_text() or "").strip()
                        if text:
                            files.append({"path": file_path, "text": text, "kind": "pdf", "page": page_num})
        except ImportError as exc:
            raise AppError("PDF ingestion requires pdfplumber. Install project requirements before ingesting PDFs.", 500) from exc
        except Exception:
            continue

    return files


def relative_source_path(file_path: str, docs_path: str) -> str:
    return file_path.replace(docs_path, "").lstrip("/\\")
