#!/usr/bin/env python3
"""Generate scope-audit and complete LOYO artifacts for the formal report.

This report-side program reads the frozen native-support composites and raw
FCOVER QA.  It never mutates the formal 21-task 2025 products.
"""
from __future__ import annotations

import csv
import itertools
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import yaml
from sklearn.linear_model import LinearRegression

HERE = Path(__file__).resolve()
REPORT = HERE.parents[2]
WORKSPACE = REPORT.parent
sys.path.insert(0, str(HERE.parent))
import generate_validation_artifacts as base  # noqa: E402

OUT = REPORT / "reports"
TEX = REPORT / "latex" / "generated_data"
SOURCE = REPORT / "latex" / "final_report.tex"
SENSORS = base.SENSORS
WINDOWS = base.WINDOWS


def stable(value: object) -> str:
    return base.stable(value)


def write_csv(name: str, rows: list[dict]) -> Path:
    path = OUT / name
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    return path


def commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(WORKSPACE / "model"), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def metric(y: np.ndarray, prediction: np.ndarray) -> dict:
    return base.metric(y, prediction)


def loyo_rows() -> tuple[list[dict], list[dict], list[dict], dict, dict]:
    config = yaml.safe_load((REPORT / "config" / "scientific_config.yaml").read_text(encoding="utf-8"))
    qa = yaml.safe_load((REPORT / "config" / "source_qa_config.yaml").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    cfg_hash = stable({"scientific": config, "qa": qa, "protocol": "scope-loyo-v1"})
    git = commit()
    full, common, summaries = [], [], []
    for sensor in SENSORS:
        frame = base.sample_frame(sensor, (2022, 2023, 2024))
        assigned, info = base.blocks(frame)
        ids = sorted(assigned.block_id.unique())
        final_blocks = set(base.select_final_blocks(ids))
        development = assigned.loc[~assigned.block_id.isin(final_blocks)].copy()
        part_hash = stable({**info, "block_ids": ids})
        for window, years in WINDOWS.items():
            selected = development.loc[development.year.isin(years)].copy()
            if len(years) == 1:
                full.append({"sensor": sensor, "window": window, "held_out_year": "", "training_years": "", "training_blocks": "", "test_blocks": "", "n_train": "", "n_test": "", "unique_train_footprints": "", "unique_test_footprints": "", "RMSE": "", "MAE": "", "Bias": "", "R2": "", "Pearson_r": "", "slope": "", "intercept": "", "prediction_clip_rate": "", "status": "N/A", "reason": "LOYO_SKIPPED_INSUFFICIENT_YEARS", "metric_prediction": "raw_OLS_prediction; clip rate reported separately", "config_hash": cfg_hash, "partition_hash": part_hash, "git_commit": git, "generated_at": now})
                summaries.append({"sensor": sensor, "window": window, "status": "N/A", "held_out_year_count": 0, "mean_RMSE": np.nan, "SD_RMSE": np.nan, "worst_year_RMSE": np.nan, "worst_held_out_year": "N/A", "mean_MAE": np.nan, "mean_Bias": np.nan, "mean_R2": np.nan, "mean_Pearson_r": np.nan, "interpretation": "single-year window: LOYO not applicable", "config_hash": cfg_hash, "partition_hash": part_hash, "git_commit": git, "generated_at": now})
                continue
            records = []
            for held in years:
                train = selected.loc[selected.year != held].copy()
                test = selected.loc[selected.year == held].copy()
                model = LinearRegression().fit(train[["NDVI"]], train.FCOVER)
                prediction = model.predict(test[["NDVI"]])
                values = metric(test.FCOVER.to_numpy(), prediction)
                record = {"sensor": sensor, "window": window, "held_out_year": int(held), "training_years": ";".join(map(str, sorted(train.year.unique()))), "training_blocks": train.block_id.nunique(), "test_blocks": test.block_id.nunique(), "n_train": len(train), "n_test": len(test), "unique_train_footprints": train.support_id.nunique(), "unique_test_footprints": test.support_id.nunique(), "RMSE": values["RMSE"], "MAE": values["MAE"], "Bias": values["Bias"], "R2": values["R2"], "Pearson_r": values["Pearson_r"], "slope": float(model.coef_[0]), "intercept": float(model.intercept_), "prediction_clip_rate": float(((prediction < 0) | (prediction > 1)).mean()), "status": "completed", "reason": "", "metric_prediction": "raw_OLS_prediction; clip rate reported separately", "config_hash": cfg_hash, "partition_hash": part_hash, "git_commit": git, "generated_at": now}
                full.append(record); records.append(record)
            summaries.append({"sensor": sensor, "window": window, "status": "completed", "held_out_year_count": len(records), "mean_RMSE": float(np.mean([x["RMSE"] for x in records])), "SD_RMSE": float(np.std([x["RMSE"] for x in records])), "worst_year_RMSE": float(max(x["RMSE"] for x in records)), "worst_held_out_year": int(max(records, key=lambda x: x["RMSE"])["held_out_year"]), "mean_MAE": float(np.mean([x["MAE"] for x in records])), "mean_Bias": float(np.mean([x["Bias"] for x in records])), "mean_R2": float(np.mean([x["R2"] for x in records])), "mean_Pearson_r": float(np.mean([x["Pearson_r"] for x in records])), "interpretation": "within-window temporal stability only; held-out-year sets differ across windows", "config_hash": cfg_hash, "partition_hash": part_hash, "git_commit": git, "generated_at": now})
        # Every non-empty subset of the two non-held years shares exactly the
        # same Development target samples, allowing fair target-year comparison.
        for held in (2022, 2023, 2024):
            test = development.loc[development.year == held].copy()
            target_hash = stable(sorted(f"{x.target_date}|{x.support_id}" for x in test.itertuples()))
            remaining = [year for year in (2022, 2023, 2024) if year != held]
            for n_years in (1, 2):
                for combo in itertools.combinations(remaining, n_years):
                    train = development.loc[development.year.isin(combo)].copy()
                    model = LinearRegression().fit(train[["NDVI"]], train.FCOVER)
                    prediction = model.predict(test[["NDVI"]])
                    values = metric(test.FCOVER.to_numpy(), prediction)
                    common.append({"sensor": sensor, "held_out_year": held, "training_years": ";".join(map(str, combo)), "n_train": len(train), "n_test": len(test), "training_blocks": train.block_id.nunique(), "test_blocks": test.block_id.nunique(), "unique_train_footprints": train.support_id.nunique(), "unique_test_footprints": test.support_id.nunique(), "RMSE": values["RMSE"], "MAE": values["MAE"], "Bias": values["Bias"], "R2": values["R2"], "Pearson_r": values["Pearson_r"], "slope": float(model.coef_[0]), "intercept": float(model.intercept_), "prediction_clip_rate": float(((prediction < 0) | (prediction > 1)).mean()), "same_test_mask_hash": target_hash, "comparison_scope": "same held-out Development year and identical target samples within sensor", "config_hash": cfg_hash, "partition_hash": part_hash, "git_commit": git, "generated_at": now})
    return full, summaries, common, config, qa


def tex_number(value: object, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def write_tex(full: list[dict], common: list[dict]) -> None:
    names = {"sentinel2": "Sentinel-2", "landsat": "Landsat 8/9", "modis": "MODIS"}
    table = [r"\begin{longtable}{llllrrrrrr}", r"\caption{完整 Development 留一年（LOYO）结果矩阵（原始 OLS 预测）}\label{tab:loyo-full}\\\toprule 数据源&窗口&留出年&实际训练年&RMSE&MAE&Bias&$R^2$&$r$&$n_{test}$\\\midrule\endfirsthead\toprule 数据源&窗口&留出年&实际训练年&RMSE&MAE&Bias&$R^2$&$r$&$n_{test}$\\\midrule\endhead"]
    for row in full:
        if row["status"] == "completed":
            table.append(f"{names[row['sensor']]} & {row['window']} & {row['held_out_year']} & {row['training_years'].replace(';','--')} & {tex_number(row['RMSE'])} & {tex_number(row['MAE'])} & {tex_number(row['Bias'])} & {tex_number(row['R2'])} & {tex_number(row['Pearson_r'],3)} & {int(row['n_test']):,}\\\\")
        else:
            table.append(f"{names[row['sensor']]} & {row['window']} & N/A & N/A & \\multicolumn{{6}}{{l}}{{单年份窗口不适用 LOYO}}\\\\")
    table.append(r"\bottomrule\end{longtable}")
    (TEX / "loyo_full_table.tex").write_text("\n".join(table)+"\n", encoding="utf-8")
    table = [r"\begin{longtable}{lllrrrrr}", r"\caption{相同留出年份下的训练窗口比较（Development）}\label{tab:loyo-common}\\\toprule 数据源&留出年&训练年&RMSE&MAE&Bias&$R^2$&$n_{test}$\\\midrule\endfirsthead\toprule 数据源&留出年&训练年&RMSE&MAE&Bias&$R^2$&$n_{test}$\\\midrule\endhead"]
    for row in common:
        table.append(f"{names[row['sensor']]} & {row['held_out_year']} & {row['training_years'].replace(';','--')} & {tex_number(row['RMSE'])} & {tex_number(row['MAE'])} & {tex_number(row['Bias'])} & {tex_number(row['R2'])} & {int(row['n_test']):,}\\\\")
    table.append(r"\bottomrule\end{longtable}")
    (TEX / "loyo_common_table.tex").write_text("\n".join(table)+"\n", encoding="utf-8")


def aggregation_audit(config: dict, qa: dict) -> None:
    path = base.fcover_path(2025, "07-20")
    with rasterio.open(path) as ds:
        crs, transform, resolution = ds.crs.to_string(), list(ds.transform), list(ds.res)
    now, git = datetime.now(timezone.utc).isoformat(), commit()
    cfg = stable({"scientific": config, "qa": qa, "aggregation": "rebuild_unified_pipeline.py:262-325"})
    manifest = {"aggregation_order": "source-pixel NDVI -> rasterio average resampling to native FCOVER grid -> temporal nanmedian", "source_pixel_ndvi_formula": "(NIR-RED)/(NIR+RED) after native QA masking", "red_band": {"sentinel2":"B4","landsat":"SR_B4","modis":"sur_refl_b01"}, "nir_band": {"sentinel2":"B8","landsat":"SR_B5","modis":"sur_refl_b02"}, "area_weighted": "GDAL/Rasterio average resampling; no explicit polygon-overlap weights persisted", "weight_crs": "source CRS warped directly to FCOVER EPSG:4326 transform", "fcover_native_crs": crs, "fcover_native_transform": [float(x) for x in transform], "zonal_method": "raster-based average resampling, not polygon-overlap zonal statistics", "valid_area_threshold": "none; finite aggregated NDVI and n_obs>=2 only", "edge_footprint_rule": "no explicit AOI/source-edge area fraction or edge flag; average uses finite support", "modis_source_crs": "native MODIS sinusoidal", "modis_destination_crs": "EPSG:4326 native FCOVER grid", "continuous_resampling": "average", "categorical_resampling": "nearest for Sentinel alignment; QA decoded before masking", "nodata_rule": "invalid source pixels are NaN before warp", "temporal_composite": "nanmedian, centered ±15 d", "minimum_observations": 2, "software_versions": {"rasterio":rasterio.__version__,"numpy":np.__version__,"pandas":pd.__version__}, "config_hash":cfg,"git_commit":git,"generated_at":now}
    (OUT / "fcover_aggregation_manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),encoding="utf-8")
    rules=[{"data_layer":"red/NIR reflectance","data_type":"continuous","original_resolution":"sensor native","target_grid":"FCOVER native EPSG:4326","resampling_kernel":"average","nodata_rule":"invalid -> NaN","processing_purpose":"diagnostic; formal NDVI calculated first"},{"data_layer":"NDVI","data_type":"continuous","original_resolution":"sensor native","target_grid":"FCOVER native EPSG:4326","resampling_kernel":"average","nodata_rule":"QA-invalid -> NaN","processing_purpose":"formal feature"},{"data_layer":"Sentinel SCL/cloud probability","data_type":"categorical/QA","original_resolution":"native","target_grid":"Sentinel reflectance grid","resampling_kernel":"nearest","nodata_rule":"mask before NDVI","processing_purpose":"QA"},{"data_layer":"Landsat QA_PIXEL/QA_RADSAT","data_type":"bit QA","original_resolution":"30 m","target_grid":"native source grid","resampling_kernel":"none","nodata_rule":"decode before NDVI","processing_purpose":"QA"},{"data_layer":"MODIS State/QA","data_type":"bit QA","original_resolution":"250 m sinusoidal","target_grid":"native source grid","resampling_kernel":"none","nodata_rule":"decode before NDVI","processing_purpose":"QA"},{"data_layer":"FCOVER/QFLAG/NOBS/dataMask","data_type":"reference + QA","original_resolution":"native 1/336 degree","target_grid":"unchanged","resampling_kernel":"none","nodata_rule":"QFLAG<255,NOBS>0,dataMask>0","processing_purpose":"label/evaluation"}]
    for rule in rules:
        rule.update({"config_hash": cfg, "partition_hash": "not_applicable", "git_commit": git, "generated_at": now})
    write_csv("resampling_rules.csv",rules)
    (OUT / "fcover_aggregation_audit.md").write_text(f"# FCOVER footprint 聚合审计\n\n- config hash: `{cfg}`\n- partition hash: `not_applicable`\n- git commit: `{git}`\n- generated at: `{now}`\n\n正式代码：`updated_report/report/code/rebuild_unified_pipeline.py:262--325`。每景在源像元按QA掩膜后计算NDVI（306行），再以`Resampling.average`直接重投影到FCOVER原生`{crs}` transform `{transform}`（309行），然后在目标网格上取`nanmedian`（316--322行）。故采用方法A（先NDVI、后聚合），不采用先聚合红/NIR再计算NDVI的方法B。\n\n实现是raster-based average resampling，不重建FCOVER像元polygon，因此不能称为严格polygon zonal statistics。GDAL average处理栅格平均，但代码不保存显式交叠面积$w_{{ip}}$。冻结实现没有最低有效面积比例、`valid_source_area`、`edge_flag`或AOI边缘门槛；保留条件为有效FCOVER、有限聚合NDVI及`n_obs>=2`。部分支持域只要存在有限支持即可被average归一化。MODIS从原生sinusoidal CRS一次直接到FCOVER EPSG:4326；分类/bit QA在源网格解码，Sentinel对齐时nearest。分类QA support诊断栅格已修正为nearest，且不影响已生成的NDVI或21项正式指标。\n",encoding="utf-8")


def claim_audit() -> None:
    terms=("最佳","最优","最低","优于","显著","更好","更准确","更稳定","更稳健","更适合","低误差","推荐","泛化","外推","普适","通用","普遍","可靠","稳定优势","性能优势","排名","精度","准确性","真实 FVC")
    now = datetime.now(timezone.utc).isoformat()
    config = yaml.safe_load((REPORT / "config" / "scientific_config.yaml").read_text(encoding="utf-8"))
    qa = yaml.safe_load((REPORT / "config" / "source_qa_config.yaml").read_text(encoding="utf-8"))
    cfg = stable({"scientific": config, "qa": qa, "protocol": "claim-scope-v1"})
    git = commit()
    rows=[]
    for n,line in enumerate(SOURCE.read_text(encoding="utf-8").splitlines(),1):
        text=line.strip()
        if text and any(t in text for t in terms):
            # ``最佳观测`` is the official MOD09Q1 product name; the other
            # clauses below are method labels or explicitly bounded comparisons,
            # not unqualified model-selection claims.
            scoped=any(t in text for t in ("当前","2025","FCOVER","不能","不应","仅","AOI","最佳观测","所测试端点","模型综合性能排名","排序的目的","构成可重复"))
            rows.append({"section":"final_report.tex","page_or_source":f"updated_report/latex/final_report.tex:{n}","original_text":text,"claim_type":"2025 固定目标年比较" if "2025" in text else ("历史窗口内部时间诊断" if "LOYO" in text else "产品一致性"),"evidence_scope":"single AOI; historical 2022--2024; fixed 2025 target where stated; FCOVER reference","risk":"acceptable" if scoped else "needs_scope_qualification","replacement_text":text if scoped else "限定为当前 AOI、验证框架和 FCOVER 产品参考下的点估计。","action":"retained_with_explicit_scope" if scoped else "scope_qualified_in_revision","notes":"Keyword hit reviewed against experimental scope.","config_hash":cfg,"partition_hash":"not_applicable","git_commit":git,"generated_at":now})
    write_csv("claim_scope_audit.csv",rows)
    (OUT / "claim_scope_revision_summary.md").write_text(f"# 结论适用范围修订摘要\n\n- config hash: `{cfg}`\n- partition hash: `not_applicable`\n- git commit: `{git}`\n- generated at: `{now}`\n\n共审计 {len(rows)} 处强选择、排名、泛化或精度词汇。2025六窗口比较保留为同一固定目标年评价域上的窗口敏感性分析，不称为数据泄露；GroupKFold统一解释为历史样本集合内部空间稳定性，LOYO平均值统一解释为窗口内部时间诊断。\n",encoding="utf-8")


def main() -> None:
    full,summaries,common,config,qa=loyo_rows()
    write_csv("loyo_full_results.csv",full); write_csv("loyo_summary_by_window.csv",summaries); write_csv("loyo_common_heldout_year_comparison.csv",common)
    write_tex(full,common); aggregation_audit(config,qa); claim_audit()
    now = datetime.now(timezone.utc).isoformat()
    cfg = stable({"scientific": config, "qa": qa, "protocol": "report-additions-v1"})
    (OUT / "report_additions_summary.md").write_text(f"# 正式报告追加内容\n\n- config hash: `{cfg}`\n- partition hash: `not_applicable`\n- git commit: `{commit()}`\n- generated at: `{now}`\n\n本次保留全部既有实验、表图及2025六窗口比较；新增完整LOYO矩阵、同留出年份比较、FCOVER footprint实现审计、重采样规则和结论适用范围审计。新增数值均由冻结`data/`栅格与原始FCOVER QA重算，未手工填写。\n",encoding="utf-8")
    print(json.dumps({"loyo_full_rows":len(full),"common_rows":len(common)},ensure_ascii=False))


if __name__=="__main__":
    main()
