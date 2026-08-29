import csv
from pathlib import Path

from data_prep.gee_cloud import FCOVER_SOURCE_BANDS


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
ACTIVE = (WORKSPACE / "report/publication/new_experiments/08_scientific_execution/"
          "00_execution_manifest/source_scenes/active_r2")


def _rows(name: str):
    with (ACTIVE / name).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_active_full_source_contract_has_complete_exact_identities():
    names = ("ACTIVE_SENTINEL_SCENE_MANIFEST.csv", "ACTIVE_LANDSAT_SCENE_MANIFEST.csv",
             "ACTIVE_MODIS_SCENE_MANIFEST.csv")
    rows = [row for name in names for row in _rows(name)]
    assert len(rows) == 1992
    assert all(row["system:id"] and row["system:index"] and row["processing_version"] for row in rows)
    assert all(not row["system:index"].startswith(("1_", "2_")) for row in rows)
    assert all(row["source_manifest_hash"] for row in rows)


def test_missing_sentinel_cloud_partner_is_fail_observation_not_manifest_failure():
    rows = _rows("ACTIVE_SENTINEL_CLOUD_JOIN_MANIFEST.csv")
    missing = [row for row in rows if row["join_status"] == "MISSING"]
    assert len(missing) == 2
    assert all(row["included"].lower() == "false" for row in missing)


def test_active_pair_schema_is_36_bands_without_removed_sensitivity_fields():
    source = (ROOT / "src/data_prep/gee_cloud.py").read_text(encoding="utf-8")
    assert 'raw.select("RMSE").rename(f"rmse_{suffix}")' in source
    assert "normal_" not in source and "strict_" not in source and "datamask_" not in source
    assert FCOVER_SOURCE_BANDS == ("FCOVER", "RMSE", "NOBS", "LBEFORE", "LAFTER", "QFLAG")


def test_science_reads_final_aoi_active_pair_assets():
    source = (ROOT / "src/execution/science.py").read_text(encoding="utf-8")
    assert "return pair_asset_id(final_aoi, year)" in source
    assert "active_processing_hash(contract)" in source
