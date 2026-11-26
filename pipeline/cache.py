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


def _without(spec: dict[str, Any], paths: tuple[str, ...]) -> Any:
    out = json.loads(canonical_json(spec))  # tuples and lists compare alike, as in the key
    for path in paths:
        *parents, last = path.split(".")
        node = out
        for part in parents:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(last, None)
    return out


def same_except(made: dict[str, Any], now: dict[str, Any], ignore: tuple[str, ...]) -> bool:
    """`made` and `now` are the same spec once the `ignore` fields are left out of both."""
    return _without(made, ignore) == _without(now, ignore)


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

    def usable(self, item: str, key: str, exts: tuple[str, ...], now: dict[str, Any] | None = None,
               ignore: tuple[str, ...] = ()) -> Path | None:
        """The file made for exactly `key`, or else the current file when what it was made from
        differs from `now` only in the `ignore` fields (dotted paths: "tts.model"). Those are
        settings around an item, like which model drew it, not the item itself: changing them
        alone is no reason to make it again, so nothing should call it out of date. The current
        file wins over an older file made for exactly `key`, so switching back to a model used
        before never swaps in that model's old take for the one the person chose."""
        made = (self.entry(item) or {}).get("spec")
        if now is not None and ignore and made is not None and same_except(made, now, ignore):
            if current := self.current(item):
                return current
        for ext in exts:
            if hit := self.hit(item, key, ext):
                return hit
        return None

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
