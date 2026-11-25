"""Content-addressed cache, so a re-run regenerates only what changed.

Each output is named <item>__<key>.<ext>, where key is a hash of everything
that went into it: model, parameters, seed, prompt text and the hashes of any
upstream files (a shot's key includes its keyframe's hash). Change one shot's
prompt and only that shot, and whatever depends on it, gets a new key.

Old versions stay on disk so experiments can compare them; `prune` removes
files no manifest points to.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import Project
from .runlog import now_iso


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_for(spec: dict[str, Any]) -> str:
    """Short, stable hash of a spec dict (key order does not matter)."""
    return sha256_bytes(canonical_json(spec))[:16]


class StageCache:
    """outputs/<stage>/<item>__<key><ext>, indexed by outputs/<stage>/manifest.json."""

    def __init__(self, project: Project, stage: str):
        self.stage = stage
        self.dir = project.outputs / stage
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.dir / "manifest.json"
        if self.manifest_path.exists():
            self.manifest: dict[str, dict[str, Any]] = json.loads(self.manifest_path.read_text("utf-8"))
        else:
            self.manifest = {}

    def path(self, item: str, key: str, ext: str) -> Path:
        return self.dir / f"{item}__{key}{ext}"

    def hit(self, item: str, key: str, ext: str) -> Path | None:
        path = self.path(item, key, ext)
        return path if path.exists() and path.stat().st_size > 0 else None

    def record(self, item: str, key: str, path: Path, spec: dict[str, Any], **meta: Any) -> None:
        entry = {"key": key, "file": path.name, "spec": spec, "updated": now_iso()}
        entry.update(meta)
        previous = self.manifest.get(item)
        if previous and previous.get("key") == key:
            entry["updated"] = previous.get("updated", entry["updated"])  # no churn on re-runs
        self.manifest[item] = entry
        self.save()

    def current(self, item: str) -> Path | None:
        entry = self.manifest.get(item)
        if not entry:
            return None
        path = self.dir / entry["file"]
        return path if path.exists() else None

    def entry(self, item: str) -> dict[str, Any] | None:
        return self.manifest.get(item)

    def save(self) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")
        tmp.replace(self.manifest_path)

    def referenced_files(self) -> set[str]:
        files = {e["file"] for e in self.manifest.values() if "file" in e}
        for e in self.manifest.values():
            files.update(e.get("extra_files", []))
        return files


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file so an interrupted run never leaves a half file in the cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
