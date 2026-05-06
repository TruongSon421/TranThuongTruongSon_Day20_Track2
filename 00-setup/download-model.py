#!/usr/bin/env python3
"""Download the recommended GGUF model for the laptop's RAM tier.

Reads `hardware.json` (produced by detect-hardware.py) and pulls a single
GGUF file via huggingface_hub. Two quantizations downloaded so 02 and bonus
tracks have something to compare.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("ERROR: huggingface_hub not installed. Did you run setup script?", file=sys.stderr)
    sys.exit(1)


# repo_id, file_q4 (primary), file_compare (smaller for the comparison frame)
TIERS: dict[str, tuple[str, str, str]] = {
    "TinyLlama-1.1B": (
        "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
        "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "tinyllama-1.1b-chat-v1.0.Q2_K.gguf",
    ),
    "Qwen2.5-1.5B-Instruct": (
        "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "qwen2.5-1.5b-instruct-q2_k.gguf",
    ),
    "Llama-3.2-3B-Instruct": (
        "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "Llama-3.2-3B-Instruct-Q2_K.gguf",
    ),
    "Qwen2.5-7B-Instruct": (
        "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "qwen2.5-7b-instruct-q4_k_m.gguf",
        "qwen2.5-7b-instruct-q2_k.gguf",
    ),
}


def pick_tier(rec_model: str) -> str:
    for key in TIERS:
        if rec_model.startswith(key):
            return key
    return "TinyLlama-1.1B"


def find_existing(out_dir: Path, filename: str) -> Path | None:
    for p in out_dir.rglob(filename):
        if p.is_file():
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Download GGUF model for the lab.")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Don't fetch — only locate already-downloaded files and write models/active.json",
    )
    parser.add_argument(
        "--repo-id",
        default=None,
        help="Override Hugging Face repo id (e.g. user/repo).",
    )
    parser.add_argument(
        "--primary-file",
        default=None,
        help="Override primary GGUF filename (Q4-ish).",
    )
    parser.add_argument(
        "--compare-file",
        default=None,
        help="Override comparison GGUF filename (Q2-ish).",
    )
    args = parser.parse_args()

    hw_path = Path("hardware.json")
    if not hw_path.exists():
        print("ERROR: hardware.json not found. Run detect-hardware.py first.", file=sys.stderr)
        return 1

    hw = json.loads(hw_path.read_text())
    tier_key = pick_tier(hw["recommendation"]["recommended_model"])
    tier_repo_id, tier_q4_file, tier_q2_file = TIERS[tier_key]
    repo_id = args.repo_id or tier_repo_id
    q4_file = args.primary_file or tier_q4_file
    q2_file = args.compare_file or tier_q2_file

    out_dir = Path("models")
    out_dir.mkdir(exist_ok=True)

    if args.skip_download:
        primary = find_existing(out_dir, q4_file)
        compare = find_existing(out_dir, q2_file)
        if not primary or not compare:
            print(
                f"ERROR: --skip-download but couldn't find {q4_file} or {q2_file} under {out_dir}/."
                f"\nDrop them in manually first; see 00-setup/MANUAL-DOWNLOAD.md.",
                file=sys.stderr,
            )
            return 1
        print(f"==> Found {primary}")
        print(f"==> Found {compare}")
    else:
        print(f"==> Downloading {tier_key} ({q4_file}) — primary model")
        primary = Path(hf_hub_download(repo_id=repo_id, filename=q4_file, local_dir=str(out_dir)))
        print(f"    -> {primary}")

        print(f"==> Downloading {tier_key} ({q2_file}) — for quantization comparison")
        compare = Path(hf_hub_download(repo_id=repo_id, filename=q2_file, local_dir=str(out_dir)))
        print(f"    -> {compare}")

    config = {
        "tier": tier_key,
        "repo_id": repo_id,
        "primary_model": str(primary),
        "compare_model": str(compare),
    }
    Path("models/active.json").write_text(json.dumps(config, indent=2))
    print("\nWrote models/active.json — quickstart and bonus scripts read this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
