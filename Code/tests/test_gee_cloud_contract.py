from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gee_cloud_is_active_and_execution_authority_is_external_contract():
    base = yaml.safe_load((ROOT / "configs/base_methodology.yaml").read_text())
    cloud = yaml.safe_load((ROOT / "configs/gee_cloud.yaml").read_text())
    assert base["data_execution_backend"] == "gee_cloud"
    assert "scientific_execution_enabled" not in base
    assert "scientific_results_enabled" not in cloud
    assert cloud["processing"]["source_data_downloaded_locally"] is False


def test_cloud_code_freezes_operation_order_and_minimum_count():
    source = (ROOT / "src/data_prep/gee_cloud.py").read_text()
    assert source.index("reduceResolution") < source.index(".median()")
    assert ".updateMask(count.gte(2))" in source
    assert "crsTransform" in source
    assert '"scientific_results_executed": 0' in source


def test_local_downloader_requires_explicit_deprecated_acknowledgement():
    source = (ROOT / "scripts/02_download_native_data.py").read_text()
    assert "LOCAL_NATIVE_BACKEND_DISABLED" in source
    assert "acknowledge-deprecated-local-backend" in source


def test_empty_catalog_windows_preserve_pair_cube_band_schema():
    source = (ROOT / "src/data_prep/gee_cloud.py").read_text()
    assert "placeholder = (ee.Image.constant(0).rename(\"NDVI\")" in source
    assert "safe = collection.merge(ee.ImageCollection([placeholder]))" in source
    assert "count = safe.select(\"NDVI\").count()" in source


def test_manifest_table_uses_non_null_placeholder_geometry():
    source = (ROOT / "src/data_prep/gee_cloud.py").read_text()
    assert "placeholder_geometry = ee.Geometry.Point([0, 0])" in source
    assert "ee.Feature(placeholder_geometry" in source


def test_active_registry_contains_only_two_experiments():
    registry = yaml.safe_load((ROOT / "configs/active_experiments.yaml").read_text())
    assert [item["id"] for item in registry["active_experiments"]] == ["multi_aoi", "rolling_origin"]
    assert registry["removed_from_active_design"][0]["id"] == "fcover_quality_sensitivity"


def test_preexecution_gate_requires_authoritative_cloud_audit():
    source = (ROOT / "scripts/08_run_preexecution_audit.py").read_text()
    assert 'checks["gee_cloud_asset_audit_ready"]' in source
    assert 'checks["gee_cloud_counts_exact"]' in source
    assert 'checks["gee_scientific_results_not_executed"]' in source
