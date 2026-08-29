from pathlib import Path

from execution.contract import load_contract
from execution.gate import run_pre_execution_gate


ROOT = Path(__file__).resolve().parents[1]


def test_current_scientific_execution_readiness_gate_passes_all_hard_controls():
    report = run_pre_execution_gate(load_contract(ROOT / "configs/scientific_execution.yaml"), write=False)
    outcomes = {row["gate"]: row["status"] for row in report["checks"]}
    assert report["status"] == "PASS"
    assert outcomes["Sentinel source manifests"] == "PASS"
    assert outcomes["GEE/local Sentinel parity"] == "PASS"
    assert outcomes["GEE/local Landsat parity"] == "PASS"
    assert outcomes["GEE/local MODIS parity"] == "PASS"
    assert outcomes["FCOVER active asset provenance"] == "PASS"
    assert outcomes["Paired-cube provenance"] == "PASS"
    assert outcomes["processing hashes"] == "PASS"
    assert outcomes["5 km block stability"] == "PASS"
    assert outcomes["scientific execution interlock"] == "PASS"
    assert outcomes["no premature scientific results"] == "PASS"


def test_runners_use_the_runtime_contract_not_a_hardcoded_phase_guard():
    for name in ("20_run_multi_aoi_experiment.py", "21_run_rolling_origin_experiment.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "require_scientific_acknowledgement(contract)" in source
        assert "acknowledge-scientific-execution" not in source
