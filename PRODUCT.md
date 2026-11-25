# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A grandchild who heard a family story and wants to turn it into a short film for their family and for people their age. They are not technical: they don't know what a seed, a motion mode or a LoRA is, and they shouldn't need to. They work on a laptop, at a desk, over a few evenings, and come back to the project between sessions.

## Product Purpose

The studio turns a family story into a 60 to 90 second Amharic film with English captions, in 9:16 for phone feeds and 16:9 for sharing. It walks the maker through six steps (Story, Script, Sketch, References, Scenes, Final cut), each approved before the next opens. Success is a finished film the family recognises as their story, made without surprise costs and without redoing work.

## Positioning

Approval-gated and cost-aware: every decision is made once, in order (words, then composition, then faces, then motion). Upstream changes mark later work stale instead of deleting it. Most of the work is free, and the few paid actions (clips, score) are priced and confirmed before they run.

## Operating Context

- Runs locally (`uv run python -m pipeline studio`, http://127.0.0.1:8765), desktop only, on Windows.
- The same steps run from the CLI (`python -m pipeline flow`, `approve`, `sketch`, `scene`, `cut`).
- Free tiers (Gemini, Cloudflare Workers AI) run out daily; the maker sees when each comes back and can add keys from another account.
- Outputs land in `outputs/`; approvals live in `approvals.json`.

## Capabilities and Constraints

- Six steps, each with an Approve, and staleness reasons ("changed: the script").
- Sketch and animatic are drawn locally for free. Reference sheets, stills and voices use free tiers. Clips (WaveSpeed) and the score are paid.
- Allowed motion modes and a whole-film budget, set once.
- Earlier approved versions of a scene can be put back from the cache at no cost.
- Desktop only; phone and tablet layouts are out of scope.

## Brand Commitments

- Plain, user-facing words everywhere: no pipeline jargon in the UI.
- Every action shows its price or "Free"; paid actions always ask first.

## Evidence on Hand

- A placeholder story: `story.md` ("An Egg Walks on Its Own Legs", a grandmother's walk to the Dessie market).
- Its storyboard, reference sheets, stills and voices under `outputs/`.
- No real audience feedback yet (DESIGN.md test tables are empty); do not invent any.

## Product Principles

1. Always show where the maker is, what is next, what is stale, and what it costs.
2. One decision at a time; later steps wait for earlier approvals.
3. Nothing is lost: edits mark later work stale, old versions come back for free.
4. Money is never spent by surprise.

## Accessibility & Inclusion

Amharic (Ge'ez script) text appears beside English throughout; fonts must render it well.
