import json
from pathlib import Path

from flask import current_app

_manifest_cache = None
_manifest_mtime = None
_manifest_warned_missing = False


def _manifest_path() -> Path:
    static_root = Path(current_app.static_folder) / "vite"
    preferred = static_root / "manifest.json"
    if preferred.exists():
        return preferred
    return static_root / ".vite" / "manifest.json"


def _load_manifest() -> dict:
    global _manifest_cache, _manifest_mtime, _manifest_warned_missing
    path = _manifest_path()
    if not path.exists():
        if not _manifest_warned_missing:
            current_app.logger.warning(
                "Vite manifest not found at %s. Run `npm run build` (or rebuild Docker image) to generate assets.",
                path,
            )
            _manifest_warned_missing = True
        return {}

    mtime = path.stat().st_mtime
    if _manifest_cache is None or _manifest_mtime != mtime:
        with path.open("r", encoding="utf-8") as f:
            _manifest_cache = json.load(f)
        _manifest_mtime = mtime

    return _manifest_cache


def _lookup_entry(manifest: dict, entry: str) -> dict:
    if entry in manifest:
        return manifest[entry]
    if entry.startswith("src/") and entry[4:] in manifest:
        return manifest[entry[4:]]
    if not entry.startswith("src/") and f"src/{entry}" in manifest:
        return manifest[f"src/{entry}"]
    return {}


def asset_url(entry: str) -> str:
    manifest = _load_manifest()
    info = _lookup_entry(manifest, entry)
    if "file" in info:
        return f"/static/vite/{info['file']}"
    return f"/static/vite/{entry}"


def asset_css_urls(entry: str) -> list[str]:
    manifest = _load_manifest()
    info = _lookup_entry(manifest, entry)
    return [f"/static/vite/{css_file}" for css_file in info.get("css", [])]
