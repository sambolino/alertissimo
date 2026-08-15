#!/usr/bin/env python3
"""List compact statistics for generated Portfolio UI fixtures."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / ".ui-fixtures" / "portfolios"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=DEFAULT)
    directory = parser.parse_args().directory
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = Counter(r["semantic_type"].split("@", 1)[0] for r in data["records"])
        families = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(f"{path.name}\n  id={data['internal_portfolio_id']}")
        print(f"  records={len(data['records'])} {families}".rstrip())
        print(f"  executions={len(data['executions'])} edges={len(data['edges'])}")


if __name__ == "__main__":
    main()
