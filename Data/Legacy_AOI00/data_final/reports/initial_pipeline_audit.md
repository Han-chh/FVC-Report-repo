# Initial pipeline audit

Generated 2026-08-04T08:41:28.991684+00:00 from executable source and current configuration.

## Products and real call chain

`backend.sources.registry → adapter.execute → adapter.acquire/canonicalize/validate/preprocess` is the active ingestion chain. Sentinel-2 is `COPERNICUS/S2_SR_HARMONIZED` (`B4`, `B8`, `SCL`, cloud-probability collection); Landsat is C2 L2 (`SR_B4`, `SR_B5`, `QA_PIXEL`, `QA_RADSAT`); MODIS is `MODIS/061/MOD09Q1` (`sur_refl_b01`, `sur_refl_b02`, `State`, `QA`). FCOVER input is Copernicus FCOVER 300 m V2 RT6 (`FCOVER`, `QFLAG`, `NOBS`, `dataMask`).

## Findings before change

* Sentinel configured SCL exclusion was `[0,1,3,6,8,9,10,11]`, cloud probability threshold 40, scale 0.0001; legacy validation did **not** require the cloud-probability asset and preprocessing silently accepted its absence.
* MODIS scale was 0.0001 and legacy code decoded only State cloud/shadow/internal-cloud/snow/adjacent-cloud. It neither decoded State bits 3–5 (land/water) nor acquired/decoded the MOD09Q1 `QA` band (MODLAND, band 1/2 quality, atmospheric correction): this was unsafe and is corrected in this revision.
* Landsat remains scale 0.0000275 and offset -0.2, invalid `QA_PIXEL` bits 0–5 plus nonzero `QA_RADSAT`; no new Landsat water rule is introduced.
* All source masks act before NDVI and median temporal composite. Frozen minimum per-pixel valid observations is 2. Training must aggregate NDVI to FCOVER support before OLS.
* The formal runner does not read any legacy `features`, `processed`, `training`, `models`, `applications`, `comparisons` or old statistics; it reads only `raw/acquisition/raw` and records checksums.

## Historical risks

Old jobs could silently reuse legacy processed/feature/model/application data; old MODIS jobs lack required QA; and old task manifests use distinct application/comparison inputs. The new run has one 2025 NDVI cube and one fixed evaluation mask per sensor, checked across all seven strategies.
