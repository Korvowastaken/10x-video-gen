"""Asking before a chain moves on to another service.

The stages name a chain of models (Cloudflare, then Kaggle, then Gemini for
pictures; Claude, then Gemini for writing). When a model's service has used up
its free limit, or keeps failing, the next model in line belongs to another
service with limits and money of its own. Nothing is sent there until the
person says so:

  - in a studio job, the job waits with a question on the page ("Use Kaggle" or
    "Stop"); Stop ends the job like the Stop button, and what was made is kept;
  - on the command line at a terminal, it asks y/n;
  - anywhere else (a script, a request outside a job) it refuses.

A yes holds for the rest of the run (a studio job, or one command), so a stage
that speaks forty lines asks once. Moving between models of the same service,
or between saved keys of one service, does not ask: that is the same account.
A model skipped without a call (no key saved, paused) is not a switch either.
"""
from __future__ import annotations

from . import jobs, keys
from .config import ConfigError
from .retry import QuotaExhausted

AUTO = False         # tests: switch without asking
INTERACTIVE = False  # set by the command line when it runs at a terminal

# What using each service costs, in a line for the question.
NOTE = {
    "kaggle": "It runs as one GPU job, can wait a long time in Kaggle's queue, and uses your weekly GPU hours.",
    "wavespeed": "It is paid from your WaveSpeed credit.",
    "anthropic": "It is paid from your Claude credit.",
}
_RUN: dict[str, bool] = {}  # outside a studio job: answers given in this command


class Declined(ConfigError):
    """The next service was not allowed (answered no, or nobody could be asked)."""


def label(service: str) -> str:
    return keys.SERVICES.get(service, {}).get("label", service)


def reason(exc: BaseException | None) -> str:
    if isinstance(exc, QuotaExhausted):
        return "has used up its free limit"
    text = " ".join(str(exc).split())[:160] if exc else ""
    return f"failed ({text})" if text else "failed"


def new_run() -> None:
    _RUN.clear()


def allow(failed: str, failed_exc: BaseException | None, service: str, *, what: str) -> None:
    """Return when `service` may take over from `failed`; raise if not.

    In a studio job a Stop answer raises jobs.Cancelled, so the job ends the way Stop ends it."""
    if service == failed or AUTO:
        return
    ctx = jobs.current()
    answers = ctx.switches if ctx else _RUN
    if answers.get(service):
        return
    question = {"from": label(failed), "to": label(service), "reason": reason(failed_exc), "what": what,
                "note": NOTE.get(service, f"It uses {label(service)}'s own free limit.")}
    text = f"{question['from']} {question['reason']} for {what}. Use {question['to']} instead? {question['note']}"
    if service in answers:  # said no before in this run
        raise Declined(f"{question['from']} {question['reason']}; {question['to']} was not allowed")
    if ctx:
        answers[service] = ctx.ask(question, text)  # waits; Stop raises jobs.Cancelled
    elif INTERACTIVE:
        answers[service] = input(f"\n  {text} [y/N] ").strip().lower() in ("y", "yes")
    else:
        raise Declined(f"{text} Run it from the studio or a terminal to choose.")
    if not answers[service]:
        if ctx:
            raise jobs.Cancelled(f"{question['to']} was not used")
        raise Declined(f"{question['from']} {question['reason']}; {question['to']} was not used")
