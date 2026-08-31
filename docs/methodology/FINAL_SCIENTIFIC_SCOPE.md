# Final Scientific Scope

## Study objective

This study evaluates agreement between NDVI-based FVC retrieval approaches and Copernicus FCOVER on a common native 300-m FCOVER target grid, emphasizing geographic heterogeneity and historical-window transfer. It is not a field-level FVC validation.

## Study area

Four deliberately selected contrasting Qinghai Plateau AOIs are analysed: AOI-00, AOI-01, AOI-02, and AOI-03. Each is approximately 583 km2; their registry and geographic context are in `repo/Data/Design/01_multi_aoi/final_four_aoi_registry.csv`.

## Time period

The authoritative years are 2021-2025. Nominal dates are 20 July, 31 July, and 10 August.

## Sensor and reference products

Sentinel-2 Harmonized surface reflectance; Landsat 8/9 Collection 2 Level-2 Tier-1 surface reflectance; MOD09Q1 Collection 6.1; and Copernicus FCOVER V2 RT6.

## Primary temporal protocol

**NON-OVERLAPPING NEAREST-NOMINAL ASSIGNMENT.** Every eligible observation within inclusive +/-15-day support is assigned to the nearest nominal date; exact ties go to the earlier date. A source identity is used at most once across composites. The existing cellwise median requires at least two finite contributions. Old overlapping nominal-date reuse is **DEPRECATED**.

## Primary target grid

The common grid is the native 300-m Copernicus FCOVER target grid. A common grid does not imply identical effective post-QA support across sensors.

## Primary modelling and historical windows

The locked formal matrix contains 72 Multi-AOI OLS runs, 72 Rolling-Origin OLS runs (144 total), and 48 DPM configurations. OLS is intercept-inclusive regression of paired target-cell FCOVER on NDVI. DPM is a descriptive endpoint comparator under separate target-year-NDVI information conditions. Multi-AOI windows are 2022, 2023, 2024, 2022-2023, 2023-2024, and 2022-2024. Rolling-Origin target 2024 uses H1=2023, H2=2022-2023, H3=2021-2023; target 2025 uses H1=2024, H2=2023-2024, H3=2022-2024.

## Primary spatial inference and statistics

Prespecified fixed-origin 5-km square blocks are the only inferential aggregation scale. They are substantially coarser than the 300-m grid, reduce local pseudo-replication, and retain within-AOI spatial replication. They are not an empirically calibrated independence threshold or an optimality claim. Block RMSE is compared using paired, two-sided t-tests, 95% confidence intervals where reported, and local Holm correction within each predefined three-contrast sensor-AOI-target-year family. The left-minus-right sign is positive when the longer right-hand history has lower RMSE.

## Active sensitivities

Only aggregation order and Landsat aerosol QA are active. Non-overlap is the primary protocol, not a sensitivity. No multiscale 5-km block-size sensitivity was performed.

## Inactive and deprecated analyses

Deprecated: old overlapping primary; old non-overlap-as-sensitivity framing; overlapping-baseline aggregation and aerosol sensitivity outputs; partial 10/20 aerosol outputs; and obsolete manuscript drafts. They remain only for provenance and must not supply manuscript numbers.

## Claim boundaries

The manuscript may claim FCOVER-reference agreement, geographic heterogeneity, configuration-specific history dependence, tested processing sensitivity, and 5-km conditional inference. It may not claim field-level absolute FVC accuracy, causal effects of added years, universal sensor superiority, 5-km spatial independence or optimality, cross-scale block robustness, or immunity to processing choices.
