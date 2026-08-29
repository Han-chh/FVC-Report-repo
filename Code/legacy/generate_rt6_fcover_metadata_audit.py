#!/usr/bin/env python3
"""Generate read-only FCOVER provenance and processing audits for the formal report.

The program only reads frozen input rasters, sidecar metadata, code and report
tables.  It deliberately does not rebuild models or alter numerical results.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio


HERE = Path(__file__).resolve().parent
REPORT_ROOT = HERE.parents[1]
WORKSPACE = REPORT_ROOT.parent
PROJECT = next((WORKSPACE / "qh-fvc-data" / "storage" / "projects").glob("prj_*__*"))
FCOVER_ROOT = PROJECT / "data-center" / "fcover" / "series"
OUT = REPORT_ROOT / "reports"
RAW_OUT = OUT / "fcover_metadata_raw"
FORMAL_CODE = HERE / "rebuild_unified_pipeline.py"
METRICS = OUT / "final_21_experiment_metrics.csv"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE))
    except ValueError:
        return str(path)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def year_from(path: Path) -> int:
    return int(path.name.split("_")[1][:4])


def date_from(path: Path) -> str:
    return path.name.removeprefix("fcover_").removesuffix(".tif")


def info_payload(path: Path, sidecar: dict) -> dict:
    with rasterio.open(path) as ds:
        return {
            "audit_tool": "rasterio/GDAL Python bindings (gdalinfo executable unavailable in this workspace)",
            "file": str(path),
            "driver": ds.driver,
            "width": ds.width,
            "height": ds.height,
            "count": ds.count,
            "dtypes": list(ds.dtypes),
            "nodata": ds.nodata,
            "crs": str(ds.crs),
            "transform": list(ds.transform),
            "res": list(ds.res),
            "descriptions": list(ds.descriptions),
            "scales": list(ds.scales),
            "offsets": list(ds.offsets),
            "profile": ds.profile,
            "dataset_tags": ds.tags(),
            "band_tags": {str(i): ds.tags(i) for i in range(1, ds.count + 1)},
            "sidecar_metadata_verbatim": sidecar,
        }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW_OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    files = sorted(FCOVER_ROOT.glob("*/years/*/*/raw/acquisition/raw/fcover/fcover_*.tif"))
    if len(files) != 12:
        raise RuntimeError(f"Expected 12 formal FCOVER files, found {len(files)}")

    inventory: list[dict] = []
    checksums: list[dict] = []
    mask_rows: list[dict] = []
    raw_original_present = False
    gdalinfo_available = shutil.which("gdalinfo") is not None

    for path in files:
        sidecar_path = path.with_suffix(path.suffix + ".metadata.json")
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        payload = info_payload(path, sidecar)
        out_json = RAW_OUT / f"{path.name}.rasterio_metadata.json"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (RAW_OUT / f"{path.name}.source_sidecar.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if gdalinfo_available:
            output = subprocess.check_output(["gdalinfo", "-json", str(path)], text=True)
            (RAW_OUT / f"{path.name}.gdalinfo.json").write_text(output, encoding="utf-8")

        with rasterio.open(path) as ds:
            bands = {name: index + 1 for index, name in enumerate(ds.descriptions)}
            raw = ds.read(bands["FCOVER"])
            qflag = ds.read(bands["QFLAG"])
            nobs = ds.read(bands["NOBS"])
            data_mask = ds.read(bands["dataMask"])
            nodata = ds.nodata
            scale = float(sidecar["quality_metadata"]["fcover_scale"])
            non_nodata = raw != nodata
            decoded = raw.astype("float64") * scale
            code_valid = (
                non_nodata
                & (qflag != nodata)
                & (nobs != nodata)
                & (data_mask != nodata)
                & (qflag < 255)
                & (nobs > 0)
                & (data_mask > 0)
                & np.isfinite(decoded)
                & (decoded >= 0)
                & (decoded <= 1)
            )
            nominal_date = date_from(path)
            year = year_from(path)
            product_id = sidecar["source_product_id"]
            assets = sidecar.get("source_assets", {})
            fcover_asset = assets.get("FCOVER", {})
            inventory.append({
                "year": year,
                "nominal_date": nominal_date,
                "complete_filename": product_id,
                "relative_path": rel(path),
                "collection": "clms_fcover_global_300m_10daily_v2_cog (runtime configuration)",
                "product_name": sidecar.get("product", "未从本地证据确认"),
                "product_version": sidecar.get("source_product_version", "未从本地证据确认"),
                "run": "RT6 (source_product_id)",
                "download_interface": "Copernicus Data Space Ecosystem OData $value endpoint (recorded https_href)",
                "source_url_or_endpoint_type": fcover_asset.get("https_href", "未从本地证据确认"),
                "acquisition_or_product_date": sidecar.get("acquisition_date", "未从本地证据确认"),
                "local_download_time": "未从本地证据确认",
                "original_container_format": "原始全球资产未本地留存，无法直接验证",
                "current_input_format": ds.driver,
                "band_name": "FCOVER (band 1 of local four-band input)",
                "crs": str(ds.crs),
                "raster_width": ds.width,
                "raster_height": ds.height,
                "transform": " ".join(map(str, ds.transform)),
                "pixel_size": " x ".join(map(str, ds.res)),
                "original_dtype": "原始全球资产未本地留存，无法直接验证",
                "current_dtype": ds.dtypes[bands["FCOVER"] - 1],
                "original_nodata": "原始全球资产未本地留存，无法直接验证",
                "current_nodata": nodata,
                "scale": scale,
                "offset": 0,
                "compression": ds.profile.get("compress", "未从本地文件验证"),
                "sha256": digest(path),
            })
            checksums.append({
                "filename": path.name,
                "relative_path": rel(path),
                "file_size_bytes": path.stat().st_size,
                "sha256": digest(path),
                "calculated_at": now,
                "role": "formal FCOVER input: training and evaluation reference",
                "year": year,
                "nominal_date": nominal_date,
            })
            mask_rows.append({
                "year": year,
                "nominal_date": nominal_date,
                "file": path.name,
                "total_pixels": raw.size,
                "fcover_non_nodata": int(non_nodata.sum()),
                "qflag_read": "yes",
                "qflag_condition_in_formal_code": "QFLAG < 255",
                "qflag_failed_among_fcover_non_nodata": int((non_nodata & ~(qflag < 255)).sum()),
                "nobs_read": "yes",
                "nobs_condition_in_formal_code": "NOBS > 0",
                "nobs_failed_among_fcover_non_nodata": int((non_nodata & ~(nobs > 0)).sum()),
                "dataMask_read": "yes",
                "dataMask_condition_in_formal_code": "dataMask > 0",
                "dataMask_failed_among_fcover_non_nodata": int((non_nodata & ~(data_mask > 0)).sum()),
                "formal_code_valid": int(code_valid.sum()),
                "additional_conditions_removed": int((non_nodata & ~code_valid).sum()),
                "qflag_values": json.dumps({str(x): int((qflag == x).sum()) for x in np.unique(qflag)}),
                "nobs_values": json.dumps({str(x): int((nobs == x).sum()) for x in np.unique(nobs)}),
                "dataMask_values": json.dumps({str(x): int((data_mask == x).sum()) for x in np.unique(data_mask)}),
            })

    write_csv(OUT / "fcover_source_inventory.csv", inventory)
    write_csv(OUT / "fcover_checksums.csv", checksums)
    write_csv(OUT / "fcover_mask_execution_audit.csv", mask_rows)
    raw_original_present = any(FCOVER_ROOT.glob("**/c_gls_FCOVER300-FCOVER-RT6_*.tiff"))

    trace = [
        {"stage": "formal input discovery", "file_or_script": rel(FORMAL_CODE), "function_or_lines": "fcover_year_dir(), lines 171--174", "input": "project raw root and annual FCOVER directories", "output": "local fcover_YYYY-MM-DD.tif", "actual_behavior": "Locates local extracted four-band FCOVER GeoTIFF files.", "evidence": "Source code."},
        {"stage": "local input read", "file_or_script": rel(FORMAL_CODE), "function_or_lines": "fcover_grid(), lines 192--200", "input": "local GeoTIFF and .metadata.json sidecar", "output": "FCOVER DN, QFLAG, NOBS, dataMask arrays; scale", "actual_behavior": "Reads all four local bands and metadata scale.", "evidence": "Source code and twelve raster inspections."},
        {"stage": "FCOVER mask", "file_or_script": rel(FORMAL_CODE), "function_or_lines": "fcover_grid(), lines 203--205", "input": "FCOVER, QFLAG, NOBS, dataMask", "output": "valid Boolean mask", "actual_behavior": "Requires non-NoData for all four bands, QFLAG<255, NOBS>0, dataMask>0, finite decoded value and 0<=F<=1.", "evidence": "Source code; fcover_mask_execution_audit.csv."},
        {"stage": "value decoding", "file_or_script": rel(FORMAL_CODE), "function_or_lines": "fcover_grid(), lines 197--205", "input": "FCOVER DN and sidecar fcover_scale", "output": "F=DN*0.004", "actual_behavior": "Scale is read from local sidecar; no /255 conversion.", "evidence": "Source code and sidecars."},
        {"stage": "sample construction", "file_or_script": rel(FORMAL_CODE), "function_or_lines": "load_cube(), lines 333--346; train_apply_compare(), lines 276--297", "input": "finite masked FCOVER, finite NDVI and NDVI observation count>=2", "output": "training and 2025 evaluation samples", "actual_behavior": "Only finite FCOVER values returned by fcover_grid can enter samples.", "evidence": "Source code."},
        {"stage": "conversion provenance", "file_or_script": "local .metadata.json sidecars", "function_or_lines": "processing_history", "input": "source assets", "output": "local four-band GeoTIFF", "actual_behavior": "Records native-grid window extraction without resampling and local dataMask derivation from native asset NoData masks.", "evidence": "Verbatim sidecars retained under reports/fcover_metadata_raw/."},
    ]
    write_csv(OUT / "fcover_processing_code_trace.csv", trace)

    gdal_note = "gdalinfo was run and JSON is retained." if gdalinfo_available else "gdalinfo executable was unavailable; equivalent local-input metadata was exported through Rasterio/GDAL bindings and each original sidecar was retained verbatim."
    (RAW_OUT / "README.md").write_text(
        f"# FCOVER metadata capture\n\nGenerated at: `{now}`.\n\n{gdal_note}\n\nThe original global source assets are not stored locally, so their direct gdalinfo/ncdump outputs cannot be generated from this workspace.\n",
        encoding="utf-8",
    )
    audit = f"""# FCOVER 元数据与处理审计

## 审计范围

本审计读取 2022--2025 年、每年三个名义产品日期的 12 个正式 FCOVER 输入文件，以及正式报告重建代码。未运行模型训练、未改写任何指标。生成时间：`{now}`。

## 已验证的本地文件事实

- 当前正式输入为 12 个本地四波段 GeoTIFF；每个文件包含 `FCOVER`、`QFLAG`、`NOBS` 和 `dataMask`。
- 当前 FCOVER 波段 dtype 为 `uint16`，当前 NoData 为 `65535`；当前 CRS 为 EPSG:4326。
- `fcover_scale=0.004` 来自每个当前输入的本地 sidecar metadata；正式代码按 `F=DN*0.004` 解码。
- sidecar 标识产品为 `CLMS_FCOVER_300m`、source product version `V2.0.1`、run `RT6`，并记录 CDSE OData `$value` 下载 URL。
- sidecar 的处理历史只记录 `window_extraction`（不改变网格、无重采样）与 `derive_data_mask_from_native_nodata`；因此 `dataMask` 是项目从原生资产 NoData 掩膜派生的本地有效域层，不应称作 FCOVER 官方质量等级波段。

## 实际样本筛选代码

`updated_report/report/code/rebuild_unified_pipeline.py:192--207` 明确读取 QFLAG、NOBS 和 dataMask；第 203--205 行将以下条件并入正式有效掩膜：四层非 NoData、`QFLAG<255`、`NOBS>0`、`dataMask>0`、有限值和 `0<=F<=1`。因此，不能据该代码写成“QFLAG、NOBS 和 dataMask 未参与正式筛选”。

逐文件结果见 `fcover_mask_execution_audit.csv`：本次 12 个局部输入内 QFLAG 全为 0、NOBS 全大于 0、dataMask 全为 1；所以这些附加条件的实际剔除数均为 0，但它们仍是正式代码中的掩膜条件。没有本地证据表明已开展 QFLAG 分层或敏感性分析。

## 数据来源与转换链

已证实链路：记录的 CDSE OData `$value` source asset URL -> 本地项目 sidecar 所记录的 `window_extraction`（原生网格、无重采样） -> 本地四波段 GeoTIFF -> `fcover_grid()` 解码和有效掩膜 -> `load_cube()` / `train_apply_compare()` 样本。

原始全球 `.tiff` 容器未在本地保留，故其直接 dtype、直接 NoData、原始 gdalinfo 与下载时间均为“当前本地证据不足，无法确认”。当前输入的 `uint16` / `65535` 不能单独证明是否发生了 255->65535 转换；结论为 **C：当前证据不足，无法确认**。同样，未直接验证原始产品是否为 UInt8 或原始 NoData 是否为 255。

## 机器可读交付物

- `fcover_source_inventory.csv`：12 个正式输入的完整来源、空间和编码记录。
- `fcover_checksums.csv`：12 个当前正式输入的 SHA-256。
- `fcover_metadata_raw/`：当前输入 Rasterio/GDAL metadata capture 与原始 sidecar 的逐文件副本。
- `fcover_processing_code_trace.csv`：从输入到样本的代码证据表。
- `fcover_mask_execution_audit.csv`：逐文件质量层值域和实际剔除数。
"""
    (OUT / "fcover_metadata_audit.md").write_text(audit, encoding="utf-8")

    discrepancy = """# FCOVER 处理表述不一致报告

## 结论：发现阻断性表述不一致

用户拟要求的“QFLAG、NOBS 和 dataMask 未参与正式样本筛选”与当前正式重建代码不一致。`updated_report/report/code/rebuild_unified_pipeline.py:192--207` 读取三层，并在第 203--205 行将 `QFLAG<255`、`NOBS>0` 和 `dataMask>0` 纳入有效掩膜。

## 实际影响

对当前 12 个正式局部输入文件的逐文件审计显示：QFLAG 均为 0、NOBS 均大于 0、dataMask 均为 1，因此这些附加条件在已审计栅格中各自剔除 0 个 FCOVER 非 NoData 像元。数值结果不能因本次语义修订被静默改写；但代码层面的筛选事实仍不可改写为“未参与”。

## 需要的后续决定

在不重跑模型的前提下，报告可以准确表述为“代码包含 QFLAG/NOBS/dataMask 门控，但在当前 12 个局部输入中其额外剔除数为 0；未开展 QFLAG 分层或敏感性分析”。若必须采用“全部非 NoData 且 QFLAG 未参与”的表述，则需要用户授权修改处理代码、重建数据和重新计算全部受影响结果（即使本次输入的数值可能保持不变）。在该冲突解决前，不生成声称已满足该表述的最终 PDF。
"""
    (OUT / "fcover_processing_discrepancy_report.md").write_text(discrepancy, encoding="utf-8")

    metric_hash = digest(METRICS) if METRICS.is_file() else "MISSING"
    regression = f"""# 数值结果回归核验

生成时间：`{now}`。

本次审计未运行重建、训练或评价代码，未修改模型输入、模型参数或评价数值。冻结的 `reports/final_21_experiment_metrics.csv` SHA-256 为 `{metric_hash}`。由于发现 FCOVER 筛选表述与代码不一致，本次未生成替换正式 PDF，也没有第二次重跑数值可对比。当前结论：**数值未改变；语义修订被阻断，等待处理规则决定。**
"""
    (OUT / "numerical_results_regression_check.md").write_text(regression, encoding="utf-8")

    terminology_rules = [
        ("RT6", "必须明确为时间整合产品；名义日期只是配对锚点"),
        ("名义", "说明不代表瞬时地表状态"),
        ("目标日期", "改为名义产品日期或明确仅为时间配对锚点"),
        ("瞬时", "只能以否定性边界说明出现"),
        ("地面真值", "保留为否定性边界，不得作为 FCOVER 定义"),
        ("QFLAG", "须按实际代码表述：正式 mask 含 QFLAG<255；未做分层或敏感性分析"),
        ("NOBS", "须按实际代码表述：正式 mask 含 NOBS>0"),
        ("dataMask", "须按实际代码表述：正式 mask 含 dataMask>0；其来源为本地 NoData 派生层"),
        ("NoData", "须区分当前输入 NoData 与原始全球文件未验证的 NoData"),
    ]
    source_lines = REPORT_ROOT / "latex" / "final_report.tex"
    text_lines = source_lines.read_text(encoding="utf-8").splitlines()
    audit_rows = []
    for keyword, replacement in terminology_rules:
        hits = [(index, text) for index, text in enumerate(text_lines, 1) if keyword.lower() in text.lower()]
        if not hits:
            audit_rows.append({"keyword": keyword, "location": "no occurrence", "current_text": "", "required_revision": replacement, "status": "not applicable"})
        for index, text in hits:
            audit_rows.append({"keyword": keyword, "location": f"latex/final_report.tex:{index}", "current_text": text, "required_revision": replacement, "status": "BLOCKED: formal wording not revised while processing-rule conflict remains"})
    terminology = ["# 术语一致性审计", "", "本次仅审计，未改写正式 LaTeX。由于 FCOVER mask 的拟写事实与正式代码冲突，所有需要修订的位置均标记为 BLOCKED；不得将此文件理解为已完成全文措辞修订。", "", "| 关键词 | 出现位置 | 原表述 | 所需新表述 | 是否通过 |", "|---|---|---|---|---|"]
    for row in audit_rows:
        old = row["current_text"].replace("|", "\\|")
        new = row["required_revision"].replace("|", "\\|")
        terminology.append(f"| {row['keyword']} | {row['location']} | {old} | {new} | {row['status']} |")
    (OUT / "terminology_consistency_audit.md").write_text("\n".join(terminology) + "\n", encoding="utf-8")

    changelog = """# RT6 / FCOVER 元数据修订记录

## 本轮已完成

- 新增 FCOVER 当前输入来源、checksum、metadata capture、代码链和掩膜执行审计。
- 记录 RT6、V2.0.1、CDSE OData endpoint 等仅由本地 sidecar 支持的信息。
- 记录原始全球容器、原始 dtype/NoData 和 255->65535 转换缺少直接本地证据。
- 生成全文术语审计；因发现处理规则冲突，其待修订位置均标为阻断状态。

## 未修改正式论文及原因

发现正式代码将 QFLAG、NOBS 和 dataMask 用于有效掩膜，和拟写的“未用于筛选”冲突。按照可复现性要求，尚未将相反的表述写入 LaTeX 或 PDF；详见 `fcover_processing_discrepancy_report.md`。模型数值未变。
"""
    (OUT / "rt6_fcover_metadata_revision_changelog.md").write_text(changelog, encoding="utf-8")


if __name__ == "__main__":
    main()
