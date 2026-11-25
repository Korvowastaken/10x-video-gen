"""`make costs`: per-stage calls, latency, GPU time and list-price cost from runs.jsonl.

Free tiers cost nothing here; the "list price" column says what the same calls
would cost at each provider's published paid rate, so the numbers transfer to a
paid setup. Rates and their sources are in COSTS.md.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .config import Project
from .runlog import read

# USD list prices, read 2026-11-25 (sources in COSTS.md).
T4_SESSION_USD_PER_HOUR = 0.70  # estimate: 2x T4 on demand, about $0.35 each, like Kaggle's "GPU T4 x2"
GEMINI_USD_PER_M = {  # (input, output) per million tokens, standard tier, prices "through December 31, 2026"
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-transcribe": (2.00, 12.00),
    "gemini-3.8-flash-tts": (0.50, 9.00),       # audio output at 25 tokens a second
    "gemini-3.8-flash-lite-tts": (0.50, 6.00),
}
UNLISTED_GEMINI = (0.75, 3.75)  # 3.7 and 3.5 Flash have no row on the pricing page: priced like 3.8 Flash


def _usd(row: dict[str, Any]) -> float:
    cost = row.get("cost") or {}
    if "usd_list" in cost:
        return float(cost["usd_list"])
    if cost.get("unit") == "tokens":
        rates = GEMINI_USD_PER_M.get(row.get("model", ""), UNLISTED_GEMINI)
        tokens_in = cost.get("input") or 0
        tokens_out = (cost.get("output") or 0) + (cost.get("thinking") or 0)
        return tokens_in * rates[0] / 1e6 + tokens_out * rates[1] / 1e6
    if row.get("provider") == "kaggle" and row.get("latency_s"):
        return row["latency_s"] / 3600 * T4_SESSION_USD_PER_HOUR
    return 0.0


def summarise(project: Project) -> dict[str, dict[str, Any]]:
    stages: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    for row in read(project):
        s = stages[row["stage"]]
        s["calls"] += 1
        s["ok"] += row.get("status") == "ok"
        s["errors"] += row.get("status") == "error"
        s["latency_s"] += row.get("latency_s") or 0
        s["gpu_s"] += row.get("gpu_s") or 0
        s["neurons"] += (row.get("cost") or {}).get("neurons") or 0
        s["usd_list"] += _usd(row)
    return {k: dict(v) for k, v in stages.items()}


def run(project: Project) -> None:
    table = summarise(project)
    rows = ["| stage | calls | ok | errors | total latency (s) | mean latency (s) | GPU (min) | neurons | list price (USD) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for stage, s in sorted(table.items()):
        mean = s["latency_s"] / s["calls"] if s["calls"] else 0
        rows.append(f"| {stage} | {int(s['calls'])} | {int(s['ok'])} | {int(s['errors'])} | {s['latency_s']:.1f} | "
                    f"{mean:.1f} | {s['gpu_s'] / 60:.1f} | {s['neurons']:.0f} | {s['usd_list']:.4f} |")
    print("\n".join(rows))
    project.out("costs.json").write_text(json.dumps(table, indent=2) + "\n", "utf-8")
