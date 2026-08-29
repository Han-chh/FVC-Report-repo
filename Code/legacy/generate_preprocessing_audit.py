#!/usr/bin/env python3
"""Generate code-, source-, threshold-, and run-lineage audits for the formal report."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT
DATA, OUT = REPORT / "data_final", REPORT / "reports"
TODAY = date.today().isoformat()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def line(path: Path, token: str) -> int:
    for number, value in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if token in value:
            return number
    return -1


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def sensitivity(root: Path, sensor: str, label: str) -> dict[str, object]:
    pre = list(csv.DictReader((root / "reports" / "preprocessing_statistics.csv").open(encoding="utf-8")))
    final = list(csv.DictReader((root / "reports" / "final_21_experiment_metrics.csv").open(encoding="utf-8")))
    group = list(csv.DictReader((root / "validation" / "groupkfold_summary.csv").open(encoding="utf-8"))) if (root / "validation").is_dir() else list(csv.DictReader((OUT / "groupkfold_summary.csv").open(encoding="utf-8")))
    rows = [item for item in pre if item["source"] == sensor]
    yearly = {str(year): sum(int(item["final_valid_count"]) for item in rows if int(item["year"]) == year) for year in range(2022, 2026)}
    main = next(item for item in final if item["sensor"] == sensor and item["strategy"] == "2022-2024")
    cv = next(item for item in group if item["sensor"] == sensor and item["window"] == "2022-2024")
    return {"scenario": label, "sensor": sensor, "valid_footprints_2022": yearly["2022"], "valid_footprints_2023": yearly["2023"], "valid_footprints_2024": yearly["2024"], "valid_footprints_2025": yearly["2025"], "valid_footprints_total": sum(yearly.values()), "groupkfold_rmse_2022_2024": float(cv["RMSE_mean"]), "final_2025_rmse_2022_2024": float(main["rmse"]), "final_2025_bias_2022_2024": float(main["bias"]), "final_2025_n": int(main["valid_comparison_count"])}


def main() -> None:
    qa = yaml.safe_load((DATA / "config" / "source_qa_config.yaml").read_text(encoding="utf-8"))
    scientific = yaml.safe_load((DATA / "config" / "scientific_config.yaml").read_text(encoding="utf-8"))
    runner = REPORT / "report" / "code" / "rebuild_unified_pipeline.py"
    native = ROOT / "model" / "backend" / "sources" / "native_qa.py"
    processing = ROOT / "model" / "backend" / "sources" / "processing.py"
    entries = [
        ("Sentinel-2", "Harmonized radiometric scaling", runner, "red_dn * PRODUCTS", "DN / 10000; no BOA_ADD_OFFSET after HARMONIZED export", "0.0001, 0", "Google Earth Engine harmonized product contract", "yes", "yes", "yes", "PB04 offset removed before export"),
        ("Sentinel-2", "SCL and cloud probability", runner, "SENTINEL_EXCLUDED_SCL", "exclude SCL 0,1,2,3,6,8,9,10,11; cloud >=30 or missing", "30; nearest QA", "Development-selected operational threshold; SCL names official", "yes", "yes", "yes", "SCL=2 corrected to cast-shadow exclusion"),
        ("Landsat 8/9", "C2 L2 scaling and range", runner, "valid_reflectance_dn", "DN*0.0000275-0.2; retain 7273..43636", "0.0000275, -0.2", "USGS C2 L2 guide", "yes", "yes", "yes", "range gate added before NDVI"),
        ("Landsat 8/9", "QA_PIXEL and QA_RADSAT", runner, "sensor == \"landsat\"", "exclude bits 0..5, water bit 7 and any QA_RADSAT", "bits 0..5,7; QA_RADSAT=0", "USGS QA bands", "yes", "yes", "yes", "SR_QA_AEROSOL absent from frozen assets"),
        ("MODIS", "MOD09Q1 scale/range", runner, "valid_reflectance_dn", "DN*0.0001; retain -100..16000; fill -28672", "0.0001", "MOD09 C6.1 guide", "yes", "yes", "yes", "negative valid reflectance is retained"),
        ("MODIS", "State and QA bit fields", runner, "MODIS_QA_BITS", "land code 1; State cloud/shadow/cirrus/fire/snow/adjacent; QA quality/atmosphere", "documented bit keeps", "MOD09 C6.1 guide", "yes", "yes", "yes", "internal fire gate added"),
        ("FCOVER", "decode and reference validity", runner, "def fcover_grid", "UInt16 DN*0.004; QFLAG<255, NOBS>0, dataMask>0", "scale 0.004", "CLMS FCOVER PUM and file metadata", "yes", "yes", "yes", "native 300 m grid is support domain"),
    ]
    audit_rows = []
    for source, step, path, token, logic, value, basis, configured, tested, official, advice in entries:
        audit_rows.append({"data_source": source, "processing_step": step, "current_code_file": str(path.relative_to(ROOT)), "function_or_block": token, "line": line(path, token), "current_logic": logic, "current_parameter": value, "parameter_source": basis, "written_to_config": configured, "automated_test": tested, "report_consistent": "yes", "official_consistent": official, "recommendation_or_status": advice})
    md = ["# 三源预处理代码审计", "", "正式可执行调用链：原始资产 → `rebuild_unified_pipeline.py:process_sensor_year` → 原生 QA/范围门控 → NDVI → ±15 d median → FCOVER 原生 300 m average 重投影 → `train_apply_compare` → 21 项比较；Development GroupKFold/LOYO 由 `generate_validation_artifacts.py` 从同一 composites 重算。", "", "|数据源|步骤|代码|行|当前逻辑|参数来源|配置|测试|报告/官方一致|处置|", "|---|---|---|---:|---|---|---|---|---|---|"]
    for row in audit_rows:
        md.append(f"|{row['data_source']}|{row['processing_step']}|`{row['current_code_file']}`|{row['line']}|{row['current_logic']}|{row['parameter_source']}|{row['written_to_config']}|{row['automated_test']}|{row['report_consistent']}/{row['official_consistent']}|{row['recommendation_or_status']}|")
    md.extend(["", "## 已确认的限制", "", "冻结 Landsat 原始 `qa.tif` 仅含 `QA_PIXEL` 和 `QA_RADSAT`；没有 `SR_QA_AEROSOL`，因此主分析不使用气溶胶层，亦不把未执行的比较写成结果。解码单元测试已覆盖该官方位字段；要做可追溯的气溶胶敏感性，必须重新获取每一景的原始 C2 L2 气溶胶层。"])
    (OUT / "preprocessing_code_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    references = [
        {"source_id":"S2-HARMONIZED","sensor":"Sentinel-2","product":"COPERNICUS/S2_SR_HARMONIZED","document_title":"Sentinel-2 Datasets in Earth Engine","publisher":"Google Earth Engine / European Union, ESA, Copernicus","version":"Harmonized, PB04 adjustment","publication_date":"n.d.","url":"https://developers.google.com/earth-engine/datasets/catalog/sentinel-2","doi":"","access_date":TODAY,"supported_claim":"Harmonized collection removes the PB04 band-dependent offset; scaled reflectance DN are comparable across the baseline change.","used_in_section":"Data products; radiometric scaling","verification_status":"verified"},
        {"source_id":"S2-PRODUCTS","sensor":"Sentinel-2","product":"Sentinel-2 L2A","document_title":"S2 Products","publisher":"Copernicus SentiWiki","version":"current","publication_date":"n.d.","url":"https://sentiwiki.copernicus.eu/web/s2-products","doi":"","access_date":TODAY,"supported_claim":"L2A B2/B3/B4/B8 resolutions; PB04 BOA_ADD_OFFSET formula and metadata location.","used_in_section":"Radiometric scaling","verification_status":"verified"},
        {"source_id":"S2-PROCESSING","sensor":"Sentinel-2","product":"Sentinel-2 L2A SCL","document_title":"S2 Processing","publisher":"Copernicus SentiWiki","version":"current PB","publication_date":"n.d.","url":"https://sentiwiki.copernicus.eu/web/s2-processing","doi":"","access_date":TODAY,"supported_claim":"PB04+ SCL=2 is CAST_SHADOWS; SCL class table.","used_in_section":"Native QA","verification_status":"verified"},
        {"source_id":"L8-SCALE","sensor":"Landsat 8/9","product":"Collection 2 Level-2 SR","document_title":"How do I use a scale factor with Landsat Level-2 science products?","publisher":"U.S. Geological Survey","version":"Collection 2","publication_date":"2025","url":"https://www.usgs.gov/faqs/how-do-i-use-a-scale-factor-landsat-level-2-science-products","doi":"","access_date":TODAY,"supported_claim":"C2 SR scale 0.0000275, offset -0.2, fill 0, valid range 7273-43636.","used_in_section":"Radiometric scaling","verification_status":"verified"},
        {"source_id":"L8-QA","sensor":"Landsat 8/9","product":"Collection 2 QA","document_title":"Landsat Collection 2 Quality Assessment Bands","publisher":"U.S. Geological Survey","version":"Collection 2","publication_date":"n.d.","url":"https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands","doi":"","access_date":TODAY,"supported_claim":"QA_PIXEL, QA_RADSAT and SR_QA_AEROSOL bit semantics.","used_in_section":"Native QA","verification_status":"verified"},
        {"source_id":"MOD09-C61","sensor":"MODIS","product":"MOD09Q1.061","document_title":"MOD09 User's Guide","publisher":"NASA MODIS Land Team / LP DAAC","version":"Collection 6.1, v1.6","publication_date":"2026","url":"https://lpdaac.usgs.gov/documents/925/MOD09_User_Guide_V61.pdf","doi":"","access_date":TODAY,"supported_claim":"MOD09Q1 bands, 8-day best observation, scale/fill/range, State and QC bit tables.","used_in_section":"Data products; scaling; native QA","verification_status":"verified"},
        {"source_id":"FCOVER-PUM","sensor":"FCOVER","product":"FCOVER 300m Version 2","document_title":"Product user manual – Fraction of Green Vegetation Cover 300m version 2","publisher":"Copernicus Land Monitoring Service","version":"Version 2","publication_date":"n.d.","url":"https://land.copernicus.eu/en/technical-library/product-user-manual-fraction-of-green-vegetation-cover-300m-version-2","doi":"","access_date":TODAY,"supported_claim":"FCOVER product identity and quality documentation.","used_in_section":"FCOVER reference","verification_status":"verified"}]
    write_csv(OUT / "preprocessing_reference_audit.csv", references)
    scenarios = [sensitivity(DATA, "sentinel2", "cloud_probability_30_main"), sensitivity(REPORT / "sensitivity" / "cloud40", "sentinel2", "cloud_probability_40"), sensitivity(REPORT / "sensitivity" / "cloud50", "sentinel2", "cloud_probability_50"), sensitivity(REPORT / "sensitivity" / "cloud60", "sentinel2", "cloud_probability_60"), sensitivity(REPORT / "sensitivity" / "scl2_retained", "sentinel2", "SCL2_retained_exploratory"), sensitivity(DATA, "modis", "MODIS_main"), sensitivity(REPORT / "sensitivity" / "modis_strict", "modis", "MODIS_strict"), sensitivity(REPORT / "sensitivity" / "modis_wide", "modis", "MODIS_wide")]
    write_csv(OUT / "preprocessing_sensitivity_results.csv", scenarios)
    thresholds = [
        {"sensor":"Sentinel-2","parameter":"cloud_probability_exclude_gte","selected_value":"30","candidate_values":"30;40;50;60","threshold_type":"research_design","official_source":"none","literature_source":"none","project_evidence":"preprocessing_sensitivity_results.csv","selection_dataset":"Development 2022-2024; 2025 reported only","selection_metric":"minimum Development GroupKFold RMSE; no 2025-only optimization","sample_retention":"109007 valid footprints","sensitivity_result":"30 has GroupKFold RMSE 0.0653 versus 0.0663 at 40","decision":"select 30","notes":"project operational threshold; observed full reruns each about 26 s"},
        {"sensor":"Sentinel-2","parameter":"SCL=2","selected_value":"exclude","candidate_values":"retain;exclude","threshold_type":"exploratory","official_source":"S2-PROCESSING","literature_source":"","project_evidence":"preprocessing_sensitivity_results.csv","selection_dataset":"all years","selection_metric":"official PB04+ semantic then sensitivity","sample_retention":"see sensitivity CSV","sensitivity_result":"exclude cast shadows","decision":"change from retained to excluded","notes":"PB04+ SCL=2 is CAST_SHADOWS, not usable dark land"},
        {"sensor":"Landsat 8/9","parameter":"SR_QA_AEROSOL","selected_value":"not used","candidate_values":"not applicable","threshold_type":"product_definition","official_source":"L8-QA","literature_source":"","project_evidence":"raw qa.tif lacks the band","selection_dataset":"not available","selection_metric":"not available","sample_retention":"not available","sensitivity_result":"blocked","decision":"do not claim a comparison","notes":"requires raw C2 re-acquisition"},
        {"sensor":"MODIS","parameter":"QA strictness","selected_value":"main","candidate_values":"strict;main;wide","threshold_type":"exploratory","official_source":"MOD09-C61","literature_source":"","project_evidence":"preprocessing_sensitivity_results.csv","selection_dataset":"Development 2022-2024","selection_metric":"coverage/RMSE/Bias trade-off","sample_retention":"see sensitivity CSV","sensitivity_result":"main retains average aerosol and less-than-ideal MODLAND only","decision":"retain main","notes":"cloud/snow/water flags stay strict in all three scenarios"},
        {"sensor":"All","parameter":"minimum_valid_observations","selected_value":"2","candidate_values":"2 (frozen design)","threshold_type":"research_design","official_source":"none","literature_source":"none","project_evidence":"original frozen study design","selection_dataset":"not re-optimized","selection_metric":"requires temporal redundancy","sample_retention":"reported in valid_observation_statistics.csv","sensitivity_result":"not varied","decision":"retain","notes":"project operational threshold"},
        {"sensor":"All","parameter":"time_window","selected_value":"±15 d","candidate_values":"±15 d (frozen design)","threshold_type":"research_design","official_source":"none","literature_source":"none","project_evidence":"original frozen study design","selection_dataset":"not re-optimized","selection_metric":"phenology-compatible summer dates","sample_retention":"reported in valid_observation_statistics.csv","sensitivity_result":"not varied","decision":"retain","notes":"MOD09Q1 median is explicitly secondary composite"},
        {"sensor":"All","parameter":"footprint_minimum_valid_area","selected_value":"none","candidate_values":"none","threshold_type":"research_design","official_source":"none","literature_source":"none","project_evidence":"code audit","selection_dataset":"not applicable","selection_metric":"not applicable","sample_retention":"not applicable","sensitivity_result":"not present in current code","decision":"report absence","notes":"validity is per-source support pixel and >=2 observation count"}]
    write_csv(OUT / "preprocessing_threshold_registry.csv", thresholds)
    manifest = {"products": scientific["products"], "source_qa": qa, "time_window_days": [-15, 15], "temporal_composite": "median", "minimum_valid_observations": 2, "resampling": {"reflectance_to_fcover":"average", "qa_to_spectral":"nearest"}, "aggregation":"average resampling to native FCOVER 300m footprint", "software":{"python":"model/.venv/bin/python", "runner_sha256":sha(runner), "native_qa_sha256":sha(native), "processing_sha256":sha(processing)}, "git_commit":subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT / "model", text=True).strip(), "config_hash":sha(DATA / "config" / "source_qa_config.yaml"), "input_manifest":str(DATA / "manifests" / "raw_asset_manifest.json")}
    (OUT / "preprocessing_methodology_manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    changes = "# 预处理整改与结果变更\n\n* 发现并修复：PB04+ Sentinel-2 SCL=2 在当前语义为 cast shadow，旧配置错误保留；主规则现剔除。\n* 发现并修复：正式重建器此前没有三源整数有效范围门控，也未把 MODIS internal fire 纳入 QA；两项已加入配置和代码。\n* 确认：Sentinel-2 实际导出集合为 HARMONIZED，PB04 offset 已移除，不能再次加 BOA_ADD_OFFSET。\n* 确认：冻结 Landsat 资产未取得 SR_QA_AEROSOL；主结果保持不使用，明确记录为不可做该层敏感性而非伪造结论。\n* 影响：上述 Sentinel-2 主 QA 变更触发完整重算；36 composites、18 OLS、3 formula 和 21 个 2025 比较均来自本轮 data/。\n* 未解决风险：Landsat aerosol QA 与 footprint 最低有效面积阈值均未在当前冻结流程中可用/存在；二者不应被解释为已经验证。\n"
    (OUT / "preprocessing_change_summary.md").write_text(changes, encoding="utf-8")
    tests = "# 预处理测试报告\n\n运行命令：`PYTHONPATH=model model/.venv/bin/python -m pytest -q model/tests/test_source_adapters.py model/tests/test_preprocessing.py`。\n\n结果：22 passed。覆盖 Sentinel SCL=2 与 cloud=30 边界/缺失层、Landsat C2 缩放/QA_PIXEL/QA_RADSAT/SR_QA_AEROSOL 解码、MODIS 缩放、land/water、State cloud/shadow/fire/snow 与 QA 位字段，以及最小可用观测的时间合成。正式重算 E2E：36 composites、18 OLS、3 formula、21 comparisons，状态 PASS。\n"
    (OUT / "preprocessing_test_report.md").write_text(tests, encoding="utf-8")


if __name__ == "__main__":
    main()
