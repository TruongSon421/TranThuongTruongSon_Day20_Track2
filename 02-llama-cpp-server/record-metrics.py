#!/usr/bin/env python3
"""Poll llama-server's /metrics every N seconds during a load run, write CSV.

Usage:
    # In one terminal: start llama-server.
    # In another:      start locust.
    # In a third:      python 02-llama-cpp-server/record-metrics.py --duration 60
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import httpx

INTERESTING = {
    "llamacpp:n_decode_total",
    "llamacpp:n_busy_slots_per_decode",
    "llamacpp:tokens_predicted_total",
    "llamacpp:prompt_tokens_total",
    "llamacpp:kv_cache_usage_ratio",
    "llamacpp:kv_cache_tokens",
    "llamacpp:requests_processing",
    "llamacpp:requests_deferred",
}

LINE = re.compile(r"^([a-z_:]+)(?:\{[^}]*\})?\s+([0-9eE.+-]+)$")


def scrape_kv_ratio_from_slots(base_url: str) -> float:
    """Compute kv_cache_usage_ratio from /slots when /metrics doesn't expose it.

    llama.cpp >=b9000 removed kv_cache_usage_ratio from /metrics for ISWA models.
    We derive it: for each active slot, tokens in KV = n_decoded (generated so far).
    Ratio = sum(n_decoded across processing slots) / sum(n_ctx across all slots).
    """
    import json as _json
    import re as _re
    try:
        resp = httpx.get(base_url.replace("/metrics", "/slots"), timeout=3.0)
        raw = _re.sub(r'[\x00-\x1f\x7f]', ' ', resp.text)
        slots = _json.loads(raw)
        total_ctx = sum(s.get("n_ctx", 0) for s in slots)
        if total_ctx == 0:
            return 0.0
        used = 0
        for s in slots:
            if s.get("is_processing"):
                nt = s.get("next_token")
                if isinstance(nt, list) and nt:
                    used += nt[0].get("n_decoded", 0)
                elif isinstance(nt, dict):
                    used += nt.get("n_decoded", 0)
        return used / total_ctx
    except Exception:
        return 0.0


def scrape(url: str) -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        text = httpx.get(url, timeout=3.0).text
    except httpx.HTTPError:
        return out
    for raw in text.splitlines():
        if raw.startswith("#"):
            continue
        m = LINE.match(raw.strip())
        if not m:
            continue
        name, val = m.group(1), m.group(2)
        if name in INTERESTING:
            try:
                out[name] = float(val)
            except ValueError:
                pass
    # Backfill kv_cache_usage_ratio from /slots if not in /metrics (llama.cpp >=b9000)
    if "llamacpp:kv_cache_usage_ratio" not in out:
        out["llamacpp:kv_cache_usage_ratio"] = scrape_kv_ratio_from_slots(url)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080/metrics")
    parser.add_argument("--duration", type=int, default=60, help="seconds to record")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between scrapes")
    parser.add_argument("--out", default="benchmarks/02-server-metrics.csv")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + args.duration
    rows: list[dict] = []
    print(f"==> Recording {args.url} for {args.duration}s, every {args.interval}s")
    while time.time() < deadline:
        sample = scrape(args.url)
        if sample:
            sample["t"] = round(time.time(), 1)
            rows.append(sample)
            print(
                f"   t={sample['t']:.0f}  "
                f"reqs_proc={sample.get('llamacpp:requests_processing', 0):.0f}  "
                f"deferred={sample.get('llamacpp:requests_deferred', 0):.0f}  "
                f"kv_ratio={sample.get('llamacpp:kv_cache_usage_ratio', 0):.2f}  "
                f"tok_pred={sample.get('llamacpp:tokens_predicted_total', 0):.0f}"
            )
        else:
            print("   (scrape failed — is llama-server running with --metrics?)")
        time.sleep(args.interval)

    if not rows:
        print("ERROR: no samples collected.", file=sys.stderr)
        return 1

    fieldnames = sorted({k for r in rows for k in r.keys()})
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n==> Wrote {out_path} ({len(rows)} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
