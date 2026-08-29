#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from audit.methodology_contract import validate
config = validate(ROOT / "configs/base_methodology.yaml")
required = ROOT.parent / "new_experiments/00_methodology_audit/current_publication_methodology.md"
if not required.exists(): raise SystemExit("METHODOLOGY_AUDIT_MISSING")
print("METHODOLOGY_CONTRACT_VALID", config["source_of_truth"])

