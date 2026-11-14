"""Safe, readable names for run folders and browser downloads."""

from datetime import timezone
import re
from pathlib import Path


def source_stem(filename: str) -> str:
    # Never use an uploaded name as a path. Bound the stem by UTF-8 bytes.
    stem = Path(filename.replace("\\", "/").rsplit("/", 1)[-1]).stem
    stem = re.sub(r"[^\w .-]+", "_", stem).strip(" ._")
    return stem.encode("utf-8")[:96].decode("utf-8", errors="ignore").rstrip(" .")


def run_label(run, directory: Path) -> str:
    source = run.config.preprocessing.get("source", {})
    name = source.get("original_name")
    if name:
        return name
    # Older sample runs have a recovered stem in the folder name only.
    prefix = f"{run.started_at.astimezone(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S.%fZ')}_{run.run_id}_"
    if directory.name.startswith(prefix):
        return directory.name[len(prefix):]
    return f"Sheet {run.document_id[:12]}"


def run_stem(run, directory: Path) -> str:
    name = run.config.preprocessing.get("source", {}).get("original_name")
    label = source_stem(name) if name else run_label(run, directory)
    # Recovered labels are already stems, which can contain dots.
    return source_stem(f"{label}.ext") or "Inventory"
