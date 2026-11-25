"""Several stories side by side, each its own film.

The home project (the repo root, or STUDIO_PROJECT) is the first story. Every
other story is a folder under <home>/stories/, a full project of its own: its
story.md, storyboard.json, approvals.json, runs.jsonl and outputs/. Switching
points the studio at another folder; nothing is copied or overwritten.

A story's name lives in its folder's story.json. The story the studio opened
last is remembered in <home>/stories/current.txt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import Project

HOME_ID = "home"
NAME_FILE = "story.json"


def folder(home: Path) -> Path:
    return home / "stories"


def _path(home: Path, sid: str) -> Path:
    if sid == HOME_ID:
        return home
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", sid):
        raise KeyError(sid)
    path = folder(home) / sid
    if not path.is_dir():
        raise KeyError(sid)
    return path


def name_of(path: Path, home: Path) -> str:
    """The name given to the story, else its storyboard's title, else a plain default."""
    try:
        name = json.loads((path / NAME_FILE).read_text("utf-8")).get("name")
        if name:
            return str(name)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        title = json.loads((path / "storyboard.json").read_text("utf-8")).get("title")
        if title:
            return str(title)
    except (OSError, ValueError, AttributeError):
        pass
    return "First story" if path == home else "Untitled story"


def _summary(sid: str, path: Path, home: Path, current: Path) -> dict[str, Any]:
    story = path / "story.md"
    text = story.read_text("utf-8") if story.exists() else ""
    return {"id": sid, "name": name_of(path, home), "current": path.resolve() == current.resolve(),
            "written": bool(text.strip()), "drafted": (path / "storyboard.json").exists()}


def listing(home: Path, current: Path) -> list[dict[str, Any]]:
    """Every story, the first one at the top, the others in the order they were made."""
    out = [_summary(HOME_ID, home, home, current)]
    if folder(home).is_dir():
        others = sorted((p for p in folder(home).iterdir() if p.is_dir() and not p.name.startswith(".")),
                        key=lambda p: p.stat().st_ctime)
        out += [_summary(p.name, p, home, current) for p in others]
    return out


def _slug(name: str, home: Path) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "story"
    slug, n = base, 2
    while (folder(home) / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create(home: Path, name: str) -> str:
    name = name.strip() or "Untitled story"
    sid = _slug(name, home)
    path = folder(home) / sid
    path.mkdir(parents=True)
    rename(home, sid, name)
    return sid


def rename(home: Path, sid: str, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("a story needs a name")
    (_path(home, sid) / NAME_FILE).write_text(json.dumps({"name": name}, ensure_ascii=False) + "\n", "utf-8")


def remembered(home: Path) -> Path:
    """The story opened last, or the first story."""
    try:
        return _path(home, (folder(home) / "current.txt").read_text("utf-8").strip())
    except (OSError, KeyError):
        return home


def remember(home: Path, sid: str) -> None:
    folder(home).mkdir(exist_ok=True)
    (folder(home) / "current.txt").write_text(sid + "\n", "utf-8")


# ---------------------------------------------------------------- API

router = APIRouter(prefix="/api/stories")


def _studio():
    from . import studio
    return studio


def _refuse_if_busy() -> None:
    """A running job writes into the open story, so the story stays put until it ends."""
    job = _studio().busy_job()
    if job:
        raise HTTPException(409, f"'{job['kind']}' is still running. Switch stories when it is done.")


def _open(sid: str) -> None:
    studio = _studio()
    _refuse_if_busy()
    try:
        studio.PROJECT = Project(_path(studio.HOME, sid).resolve())
    except KeyError:
        raise HTTPException(404, "no such story")
    remember(studio.HOME, sid)


@router.get("")
def get_stories() -> list[dict[str, Any]]:
    studio = _studio()
    return listing(studio.HOME, studio.PROJECT.root)


class Name(BaseModel):
    name: str = ""


class Open(BaseModel):
    id: str


@router.post("")
def post_story(body: Name) -> list[dict[str, Any]]:
    """Start a new, empty story and open it."""
    _refuse_if_busy()
    sid = create(_studio().HOME, body.name)
    _open(sid)
    return get_stories()


@router.put("/current")
def put_current(body: Open) -> list[dict[str, Any]]:
    _open(body.id)
    return get_stories()


@router.put("/{sid}")
def put_name(sid: str, body: Name) -> list[dict[str, Any]]:
    try:
        rename(_studio().HOME, sid, body.name)
    except KeyError:
        raise HTTPException(404, "no such story")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return get_stories()
