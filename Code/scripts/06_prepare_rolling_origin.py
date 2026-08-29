#!/usr/bin/env python3
from pathlib import Path
import csv, sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from rolling_origin.windows import primary_windows

out = ROOT.parent / "new_experiments/02_rolling_origin/rolling_origin_matrix.csv"; out.parent.mkdir(parents=True, exist_ok=True)
rows = primary_windows()
with out.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=["target_year", "history_years", "history_length", "target_role", "loyo"]); writer.writeheader()
    for row in rows: writer.writerow({**row, "history_years": ";".join(map(str, row["history_years"]))})
print(out)

