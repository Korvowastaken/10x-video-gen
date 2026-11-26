"""Consent for real people, confirmed in the studio and kept with each story.

A character that portrays or voices a real person carries `"real_person": true`
and `"consent": "C<n>"`, and nothing of them is generated until that id has a
record (storyboard.rule_errors). Records live in the story's consent.json; the
consent table in ETHICS.md still counts too, for records written there by hand.

A record keeps what the person agreed to: how they are shown, the voice that
speaks for them and the very lines they heard, the confirmations, how the answer
was recorded (the recording itself stays private, never in the repository) and
the date. Withdrawing keeps the record but blocks the person again; marking a
character "not a real person after all" keeps it for history and lets the
character be drawn as a fictional composite.

Real people with a record (agreed or withdrawn) also carry into every new draft
of the script, so a redraft keeps their ids and their real-person mark.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import ROOT, Project

FILE = "consent.json"
AGREED, WITHDRAWN, FICTIONAL = "agreed", "withdrawn", "fictional"


def load(project: Project) -> list[dict[str, Any]]:
    path = project.root / FILE
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8")).get("records", [])


def _save(project: Project, records: list[dict[str, Any]]) -> None:
    path = project.root / FILE
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps({"records": records}, indent=2, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(path)


def _ethics_ids(project: Project) -> set[str]:
    if not project.ethics.exists():
        return set()
    return set(re.findall(r"^\|\s*(C\d+)\s*\|", project.ethics.read_text("utf-8"), re.MULTILINE))


def ids(project: Project) -> set[str]:
    """Consent ids that let a real person be generated: the ETHICS.md table and this story's agreed records."""
    return _ethics_ids(project) | {r["id"] for r in load(project) if r["status"] == AGREED}


def people(project: Project) -> list[dict[str, str]]:
    """Real people for a new draft, as story.md's `people` setting lists them."""
    return [{"id": r["character"], "name": r["person"], "consent": r["id"]}
            for r in load(project) if r["status"] in (AGREED, WITHDRAWN)]


def _next_id(project: Project, sb: dict[str, Any] | None = None) -> str:
    """The next free C<n>: past the ETHICS.md table, this story's records and ids characters already hold."""
    held = {c["consent"] for c in (sb or {}).get("characters", []) if re.fullmatch(r"C\d+", c.get("consent") or "")}
    taken = {int(i[1:]) for i in _ethics_ids(project) | {r["id"] for r in load(project)} | held}
    return f"C{max(taken, default=0) + 1}"


def lines_of(sb: dict[str, Any], cid: str) -> list[dict[str, str]]:
    return [{"shot": s["id"], "text": line["text"], "en": line["en"]}
            for s in sb["shots"] for line in s["lines"] if line["speaker"] == cid]


def wording() -> list[dict[str, str]]:
    """The consent request to read out, from ETHICS.md "How consent is asked": one block per language."""
    path = ROOT / "ETHICS.md"
    if not path.exists():
        return []
    text = path.read_text("utf-8")
    start = text.find("### How consent is asked")
    if start < 0:
        return []
    end = text.find("\n## ", start)
    section = text[start:end if end > 0 else None]
    out = []
    for block in re.split(r"\n\s*\n", section):
        quoted = [ln[1:].strip() for ln in block.strip().splitlines() if ln.startswith(">")]
        if not quoted:
            continue
        body = " ".join(quoted)
        m = re.match(r"\*\*(.+?)\.?\*\*\s*(\([^)]*\))?\s*(.*)", body, re.S)
        if m:
            out.append({"label": m.group(1).rstrip("."), "note": (m.group(2) or "").strip("() "), "text": m.group(3).strip()})
        else:
            out.append({"label": "", "note": "", "text": body})
    return out


def overview(project: Project) -> dict[str, Any]:
    """Every character with where it stands, the records, and the words to read out."""
    records = load(project)
    by_id = {r["id"]: r for r in records}
    sb = json.loads(project.storyboard.read_text("utf-8")) if project.storyboard.exists() else None
    agreed = ids(project)
    characters = []
    for c in (sb or {}).get("characters", []):
        rec = by_id.get(c.get("consent", ""))
        lines = lines_of(sb, c["id"])
        if not c.get("real_person"):
            status = "fictional"
        elif c.get("consent") in agreed:
            status = "agreed"
        elif rec and rec["status"] == WITHDRAWN:
            status = "withdrawn"
        else:
            status = "needs consent"
        heard = [(x["text"], x["en"]) for x in rec["lines"]] if rec else None
        characters.append({
            "id": c["id"], "name": c["name"], "role": c["role"], "visible": c["visible"],
            "voice": (c.get("voice") or {}).get("name"), "real_person": bool(c.get("real_person")),
            "consent": c.get("consent"), "status": status, "lines": lines,
            # the person agreed to other words than these: they hear the new lines before they are used
            "lines_changed": heard is not None and status == "agreed" and heard != [(x["text"], x["en"]) for x in lines],
        })
    return {"characters": characters, "records": records, "wording": wording()}


def record(project: Project, sb: dict[str, Any], cid: str, *, self: bool, read_out: bool, agreed: bool,
           recording_kept: bool, how: str, evidence: str, today: str | None = None) -> dict[str, Any]:
    """Confirm consent for character `cid`, mark it a real person in the storyboard (the caller saves it)."""
    character = next((c for c in sb["characters"] if c["id"] == cid), None)
    if character is None:
        raise KeyError(cid)
    if not self and not (read_out and agreed and recording_kept and how.strip()):
        raise ValueError("Confirm all three, and say how the answer was recorded")
    lines = lines_of(sb, cid)
    voice = (character.get("voice") or {}).get("name")
    photo = bool((character.get("reference") or {}).get("photo"))
    # a character marked real before confirming keeps the id it holds, unless a record already took it
    held = character.get("consent")
    fresh = held if held and character.get("real_person") and held not in {r["id"] for r in load(project)}         and held not in _ethics_ids(project) else _next_id(project, sb)
    rec = {
        "id": fresh, "character": cid, "person": character["name"], "status": AGREED, "self": self,
        "shown_as": ("an AI-made animated character" + (", drawn from their photo" if photo else ""))
                    if character["visible"] else "not shown (voice only)",
        "voiced_as": f"a computer voice ({voice}), not their own" if lines else "no spoken lines",
        "lines": lines,
        "agreed_to": "appear and be voiced as above, "
                     + ("with their photo given to the image model only as a reference for their character, " if photo else "")
                     + "saying these lines, in a short film posted publicly on TikTok and YouTube with a label "
                       "saying it was made with AI; may ask for it to be taken down",
        "read_out": True if self else read_out, "agreed": True if self else agreed,
        "recording_kept": recording_kept, "how": how.strip() or ("It is me" if self else ""),
        "evidence": evidence.strip(), "date": today or dt.date.today().isoformat(),
    }
    records = load(project)
    records.append(rec)
    _save(project, records)
    character["real_person"] = True
    character["consent"] = rec["id"]
    return rec


def mark_real(project: Project, sb: dict[str, Any], cid: str) -> None:
    """Mark a character as a real person before consent is confirmed: from now on nothing of them is
    generated until it is (the caller saves the storyboard)."""
    character = next((c for c in sb["characters"] if c["id"] == cid), None)
    if character is None:
        raise KeyError(cid)
    if not character.get("real_person"):
        character["real_person"] = True
        character["consent"] = _next_id(project, sb)


def set_status(project: Project, sb: dict[str, Any], cid: str, status: str, today: str | None = None) -> None:
    """Withdraw a consent (the person stays blocked) or mark its character fictional after all."""
    records = load(project)
    rec = next((r for r in records if r["id"] == cid), None)
    linked = [c for c in sb["characters"] if c.get("consent") == cid]
    if rec is None and not (status == FICTIONAL and linked):  # a mark from story.md has no record yet
        raise KeyError(cid)
    if rec is not None:
        rec["status"] = status
        rec[status] = today or dt.date.today().isoformat()
        _save(project, records)
    if status == FICTIONAL:
        for c in sb["characters"]:
            if c.get("consent") == cid:
                c["real_person"] = False
                c.pop("consent", None)


# ---------------------------------------------------------------- API

router = APIRouter(prefix="/api/consent")


def _project() -> Project:
    from . import studio
    return studio.PROJECT


def _storyboard(project: Project) -> dict[str, Any]:
    if not project.storyboard.exists():
        raise HTTPException(409, "draft the script first: consent is asked for the characters it names")
    return json.loads(project.storyboard.read_text("utf-8"))


def _save_storyboard(project: Project, sb: dict[str, Any]) -> None:
    from . import storyboard as sbmod
    errors = sbmod.schema_errors(sb)
    if errors:
        raise HTTPException(422, {"errors": errors})
    sbmod.save(project, sb)


@router.get("")
def get_consent() -> dict[str, Any]:
    return overview(_project())


class Confirm(BaseModel):
    character: str
    self: bool = False
    read_out: bool = False
    agreed: bool = False
    recording_kept: bool = False
    how: str = ""
    evidence: str = ""


@router.post("")
def post_consent(body: Confirm) -> dict[str, Any]:
    project = _project()
    sb = _storyboard(project)
    try:
        record(project, sb, body.character, self=body.self, read_out=body.read_out, agreed=body.agreed,
               recording_kept=body.recording_kept, how=body.how, evidence=body.evidence)
    except KeyError:
        raise HTTPException(404, "no such character")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    _save_storyboard(project, sb)
    return overview(project)


@router.post("/{cid}/withdraw")
def post_withdraw(cid: str) -> dict[str, Any]:
    return _status(cid, WITHDRAWN)


@router.post("/{cid}/fictional")
def post_fictional(cid: str) -> dict[str, Any]:
    return _status(cid, FICTIONAL)


def _status(cid: str, status: str) -> dict[str, Any]:
    project = _project()
    sb = _storyboard(project)
    try:
        set_status(project, sb, cid, status)
    except KeyError:
        raise HTTPException(404, "no such consent record")
    _save_storyboard(project, sb)
    return overview(project)


class Character(BaseModel):
    character: str


@router.post("/real")
def post_real(body: Character) -> dict[str, Any]:
    """The Real person switch, turned on: protected at once, consent asked next."""
    project = _project()
    sb = _storyboard(project)
    try:
        mark_real(project, sb, body.character)
    except KeyError:
        raise HTTPException(404, "no such character")
    _save_storyboard(project, sb)
    return overview(project)
