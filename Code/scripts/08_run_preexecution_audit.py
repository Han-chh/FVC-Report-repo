#!/usr/bin/env python3
from pathlib import Path
import csv, hashlib, json, re, shutil, subprocess, sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]; EXP = ROOT.parent / "new_experiments"; sys.path.insert(0, str(ROOT / "src"))
from audit.methodology_contract import validate
from rolling_origin.windows import primary_windows

checks = {}
validate(ROOT / "configs/base_methodology.yaml"); checks["methodology_contract"] = True
final = json.loads((EXP / "01_multi_aoi/final_four_aoi_registry.geojson").read_text()); checks["four_final_aois"] = len(final["features"]) == 4
selected_sources = {f["properties"].get("source_candidate_id") for f in final["features"]}; checks["expected_selected_candidates"] = selected_sources == {"AOI-00", "AOI-C10", "AOI-C07", "AOI-C09"}
rows = primary_windows(); checks["rolling_matrix_exact"] = [(r["target_year"], tuple(r["history_years"])) for r in rows] == [(2024,(2023,)),(2024,(2022,2023)),(2024,(2021,2022,2023)),(2025,(2024,)),(2025,(2023,2024)),(2025,(2022,2023,2024))]
status = pd.read_csv(EXP / "data/data_preparation_status.csv"); checks["all_required_data_ready"] = bool((status.status == "READY").all())
checks["candidate_data_not_ready"] = bool(((status.aoi_id != "AOI-00") & (status.status != "READY")).any())
checks["2021_not_ready"] = bool(((status.year == 2021) & (status.status != "READY")).any())
cloud_audit = json.loads((EXP / "04_preexecution_audit/gee_cloud_asset_audit.json").read_text())
cloud_checks = cloud_audit["checks"]
checks["gee_cloud_asset_audit_ready"] = cloud_checks.get("ready") is True
checks["gee_cloud_counts_exact"] = (
    cloud_checks.get("actual_fcover_assets") == 165
    and cloud_checks.get("actual_pair_assets") == 55
    and not cloud_checks.get("missing_fcover_assets")
    and not cloud_checks.get("missing_pair_assets")
    and not cloud_checks.get("fcover_contract_errors")
    and not cloud_checks.get("pair_contract_errors")
)
checks["gee_scientific_results_not_executed"] = cloud_checks.get("scientific_results_executed") is False
source_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (ROOT / "src").rglob("*.py"))
checks["no_legacy_runtime_imports"] = not re.search(r"(?:from|import)\s+(?:model|report\.code|backend)", source_text)
checks["scientific_phase_disabled"] = "scientific_execution_enabled: false" in (ROOT / "configs/base_methodology.yaml").read_text()
tests = subprocess.run([str(ROOT.parents[2] / "model/.venv/bin/python"), "-m", "pytest", "-q", str(ROOT / "tests")], capture_output=True, text=True)
checks["unit_tests_pass"] = tests.returncode == 0

manifest_dir = EXP / "data/manifests"; manifest_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(EXP / "data/data_preparation_status.csv", manifest_dir / "source_availability_manifest.csv")
audit = {"checks": checks, "tests_stdout": tests.stdout.strip(), "scientific_results_executed": False,
         "ready": all(value for key, value in checks.items() if key not in {"candidate_data_not_ready", "2021_not_ready"}) and checks["all_required_data_ready"]}
out = EXP / "04_preexecution_audit/preexecution_checks.json"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(audit, indent=2), encoding="utf-8")

# Hash only after every other audit artifact has reached its final state so the
# manifest describes this exact run rather than the previous audit report.
manifest = []
for path in sorted(EXP.rglob("*")):
    if path.is_file() and path.name != "preparation_artifact_manifest.json":
        digest = hashlib.sha256(path.read_bytes()).hexdigest(); manifest.append({"path": str(path.relative_to(EXP)), "size_bytes": path.stat().st_size, "sha256": digest})
(manifest_dir / "preparation_artifact_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(audit, indent=2))
