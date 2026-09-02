"""Measure Agent routing and context metrics without changing learning state.

The script deliberately reports null when a metric lacks a comparable baseline or
provider usage field. It uses a documented UTF-8 byte estimate (four bytes/token)
for context comparisons; this is not a substitute for a provider tokenizer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from learningloop.config import Settings
from learningloop.db import Database
from learningloop.metrics import context_metrics, usage_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--session-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    settings = Settings(_env_file=None, data_dir=args.data_dir, enable_real_models=False)
    db = Database(settings.database_path)
    rows = db.model_calls(session_id=args.session_id, limit=100_000)
    report = {
        "method": {
            "context_token_estimator": "utf8_bytes_div_4",
            "cost_baseline": "requires a separately recorded Pro-only run",
            "null_policy": "missing usage, price, or baseline remains null",
        },
        **context_metrics(settings, db, args.session_id),
        **usage_metrics(rows),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
