#!/usr/bin/env python3
"""Run non-executing acceptance checks and issue the final readiness verdict."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
EXP = WORKSPACE / "report/publication/new_experiments"
OUT = EXP / "16_scientific_execution_readiness/05_final_gate"
PYTHON = WORKSPACE / "model/.venv/bin/python"
sys.path.insert(0, str(ROOT / "src"))

from execution.contract import assert_readiness_contract, load_contract  # noqa: E402
from execution.gate import run_pre_execution_gate  # noqa: E402
from execution.preparation_guard import running_forbidden_processes, sha256_file  # noqa: E402


def _run(arguments: list[str]) -> dict:
    completed = subprocess.run(arguments, cwd=WORKSPACE, capture_output=True, text=True)
    return {"command": arguments, "returncode": completed.returncode,
            "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}


def _protected_evidence() -> tuple[bool, int, list[str]]:
    path = EXP / "15_three_sensor_parity/00_PHASE0_PROTECTION/PROTECTED_EVIDENCE.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    failures = []
    for row in rows:
        target = WORKSPACE / row["path"]
        if not target.is_file() or target.stat().st_size != int(row["size_bytes"]) or sha256_file(target) != row["sha256"]:
            failures.append(row["path"])
    return not failures, len(rows), failures


def main() -> int:
    contract = load_contract(ROOT / "configs/scientific_execution.yaml")
    design_hash = assert_readiness_contract(contract)
    gate = run_pre_execution_gate(contract, write=True)
    tests = _run([str(PYTHON), "-m", "pytest", "report/publication/code/tests", "-q"])
    runners = {}
    for script in ("20_run_multi_aoi_experiment.py", "21_run_rolling_origin_experiment.py"):
        for mode in ("--validate", "--dry-run"):
            runners[f"{script}:{mode}"] = _run([str(PYTHON), f"report/publication/code/scripts/{script}", mode])
    multi = json.loads((EXP / "08_scientific_execution/00_execution_manifest/MULTI_AOI_DRY_RUN.json").read_text(encoding="utf-8"))
    rolling = json.loads((EXP / "08_scientific_execution/00_execution_manifest/ROLLING_ORIGIN_DRY_RUN.json").read_text(encoding="utf-8"))
    protected_ok, protected_count, protected_failures = _protected_evidence()
    forbidden = running_forbidden_processes()
    checks = {
        "pre_execution_gate": gate["status"] == "PASS",
        "publication_tests": tests["returncode"] == 0,
        "runner_validate_and_dry_run": all(item["returncode"] == 0 for item in runners.values()),
        "multi_aoi_plan_exact": multi.get("gate_status") == "PASS" and len(multi.get("expected_runs", [])) == 72
                                and multi.get("scientific_results_executed") is False,
        "rolling_origin_plan_exact": rolling.get("gate_status") == "PASS" and len(rolling.get("expected_runs", [])) == 72
                                     and rolling.get("scientific_results_executed") is False,
        "protected_evidence_unchanged": protected_ok and protected_count == 84,
        "no_forbidden_processes": not forbidden,
        "scientific_execution_disabled": contract.get("scientific_execution_enabled") is False,
        "execution_unacknowledged": contract.get("execution_acknowledged") is False,
    }
    ready = all(checks.values())
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "status": "SCIENTIFIC_EXECUTION_READY" if ready else "NOT_READY_FOR_SCIENTIFIC_EXECUTION",
              "ready_for_execution": ready, "design_hash": design_hash, "checks": checks,
              "pre_execution_gate": gate, "tests": tests, "runners": runners,
              "protected_evidence_count": protected_count, "protected_evidence_failures": protected_failures,
              "forbidden_processes": forbidden, "scientific_models_run": False,
              "scientific_execution_enabled": False, "execution_acknowledged": False}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "SCIENTIFIC_EXECUTION_READY_GATE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# Scientific Execution Ready gate", "", f"**Verdict: {result['status']}**", "",
             f"Design hash: `{design_hash}`.", "", "| Acceptance control | Status |", "|---|---|"]
    lines += [f"| {name} | {'PASS' if value else 'FAIL'} |" for name, value in checks.items()]
    lines += ["", f"Publication tests: `{tests['stdout']}`.",
              f"Protected evidence verified: {protected_count}; failures: {len(protected_failures)}.",
              "", "Extraction-only paired rows were validated; no scientific model, prediction, metric, inference, or manuscript update was run.",
              "Formal execution remains disabled and requires a separate explicit authorization transition."]
    (OUT / "SCIENTIFIC_EXECUTION_READY_GATE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": checks, "tests": tests["stdout"]}, indent=2))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
