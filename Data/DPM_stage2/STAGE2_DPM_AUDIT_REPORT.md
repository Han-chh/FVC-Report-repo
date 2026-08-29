# Stage 2 DPM replication and synchronization audit

## 1. AOI-00 reproduction

**PASS.** The active AOI-00 source table was reproduced at full stored precision using `publication/code/src/models/endpoint.py:endpoint_predict`, pooled eligible 2025 target-grid NDVI, NumPy linear empirical percentiles, and the frozen clipping/metric rules.

Active source: `reports/endpoint_sensitivity_metrics.csv` (SHA-256 `5929bb223c897d161506a63b3de273fa25bafdcc462401fa758d7a1211a5b049`).

| sensor | quantile_configuration | NDVI_low_expected | NDVI_low_reconstructed | NDVI_high_expected | NDVI_high_reconstructed | RMSE_expected | RMSE_reconstructed | max_absolute_difference | pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sentinel2 | P1/P99 | 0.041730416380 | 0.041730416380 | 0.786186197400 | 0.786186197400 | 0.219391259729 | 0.219391259729 | 0.000000000000 | True |
| sentinel2 | P2/P98 | 0.085362933129 | 0.085362933129 | 0.774415155649 | 0.774415155649 | 0.224010785386 | 0.224010785386 | 0.000000000000 | True |
| sentinel2 | P5/P95 | 0.232315513492 | 0.232315513492 | 0.754014208913 | 0.754014208913 | 0.230018247175 | 0.230018247175 | 0.000000000000 | True |
| sentinel2 | P10/P90 | 0.348933720589 | 0.348933720589 | 0.729101264477 | 0.729101264477 | 0.252772835862 | 0.252772835862 | 0.000000000000 | True |
| landsat | P1/P99 | 0.169647317678 | 0.169647317678 | 0.784361215234 | 0.784361215234 | 0.240732394596 | 0.240732394596 | 0.000000000000 | True |
| landsat | P2/P98 | 0.242167372704 | 0.242167372704 | 0.774499906301 | 0.774499906301 | 0.235745770018 | 0.235745770018 | 0.000000000000 | True |
| landsat | P5/P95 | 0.416761825979 | 0.416761825979 | 0.758248817921 | 0.758248817921 | 0.216714282919 | 0.216714282919 | 0.000000000000 | True |
| landsat | P10/P90 | 0.530840617418 | 0.530840617418 | 0.742109179497 | 0.742109179497 | 0.237050201622 | 0.237050201622 | 0.000000000000 | True |
| modis | P1/P99 | 0.263550421596 | 0.263550421596 | 0.808872684240 | 0.808872684240 | 0.225673382567 | 0.225673382567 | 0.000000000000 | True |
| modis | P2/P98 | 0.334960007668 | 0.334960007668 | 0.799800673723 | 0.799800673723 | 0.217942911996 | 0.217942911996 | 0.000000000000 | True |
| modis | P5/P95 | 0.473963017762 | 0.473963017762 | 0.787076145411 | 0.787076145411 | 0.204662359076 | 0.204662359076 | 0.000000000000 | True |
| modis | P10/P90 | 0.567373645306 | 0.567373645306 | 0.773658949137 | 0.773658949137 | 0.235941822287 | 0.235941822287 | 0.000000000000 | True |

A similarly named earlier file, `reports/formula_endpoint_sensitivity_metrics.csv`, was not used: it is inconsistent with the current executable input path and with `reports/formula_vs_ols_comparison.csv`. It was retained untouched as a stale historical artefact; this resolution is explicit rather than silent.

## 2. New experiment matrix

**PASS.** Thirty-six new configurations (AOI-01/02/03) and 48 total configurations were executed. Every AOI has Sentinel-2, Landsat 8/9, and MODIS, and every sensor--AOI pair has P1/P99, P2/P98, P5/P95, and P10/P90.

## 3. DPM endmember table

| AOI | sensor | quantile_configuration | NDVI_low | NDVI_high |
| --- | --- | --- | --- | --- |
| AOI-00 | landsat | P1/P99 | 0.222592 | 0.786996 |
| AOI-00 | landsat | P2/P98 | 0.305262 | 0.776135 |
| AOI-00 | landsat | P5/P95 | 0.463648 | 0.761090 |
| AOI-00 | landsat | P10/P90 | 0.562826 | 0.745769 |
| AOI-00 | modis | P1/P99 | 0.306554 | 0.806359 |
| AOI-00 | modis | P2/P98 | 0.392017 | 0.796979 |
| AOI-00 | modis | P5/P95 | 0.518894 | 0.782914 |
| AOI-00 | modis | P10/P90 | 0.589069 | 0.769716 |
| AOI-00 | sentinel2 | P1/P99 | 0.147918 | 0.786911 |
| AOI-00 | sentinel2 | P2/P98 | 0.230740 | 0.775910 |
| AOI-00 | sentinel2 | P5/P95 | 0.377955 | 0.756068 |
| AOI-00 | sentinel2 | P10/P90 | 0.470028 | 0.734008 |
| AOI-01 | landsat | P1/P99 | 0.034777 | 0.078397 |
| AOI-01 | landsat | P2/P98 | 0.038377 | 0.073791 |
| AOI-01 | landsat | P5/P95 | 0.041878 | 0.068493 |
| AOI-01 | landsat | P10/P90 | 0.044554 | 0.064324 |
| AOI-01 | modis | P1/P99 | 0.043220 | 0.083861 |
| AOI-01 | modis | P2/P98 | 0.045218 | 0.079093 |
| AOI-01 | modis | P5/P95 | 0.047208 | 0.073568 |
| AOI-01 | modis | P10/P90 | 0.048774 | 0.069590 |
| AOI-01 | sentinel2 | P1/P99 | 0.012014 | 0.052319 |
| AOI-01 | sentinel2 | P2/P98 | 0.014187 | 0.046379 |
| AOI-01 | sentinel2 | P5/P95 | 0.016529 | 0.040543 |
| AOI-01 | sentinel2 | P10/P90 | 0.018291 | 0.036806 |
| AOI-02 | landsat | P1/P99 | 0.147829 | 0.792553 |
| AOI-02 | landsat | P2/P98 | 0.172037 | 0.779763 |
| AOI-02 | landsat | P5/P95 | 0.250106 | 0.753243 |
| AOI-02 | landsat | P10/P90 | 0.373197 | 0.729181 |
| AOI-02 | modis | P1/P99 | 0.171018 | 0.807279 |
| AOI-02 | modis | P2/P98 | 0.190314 | 0.794096 |
| AOI-02 | modis | P5/P95 | 0.249349 | 0.773756 |
| AOI-02 | modis | P10/P90 | 0.354680 | 0.749691 |
| AOI-02 | sentinel2 | P1/P99 | 0.070770 | 0.802926 |
| AOI-02 | sentinel2 | P2/P98 | 0.088106 | 0.786542 |
| AOI-02 | sentinel2 | P5/P95 | 0.123161 | 0.757543 |
| AOI-02 | sentinel2 | P10/P90 | 0.214841 | 0.727217 |
| AOI-03 | landsat | P1/P99 | 0.083072 | 0.588023 |
| AOI-03 | landsat | P2/P98 | 0.090185 | 0.552010 |
| AOI-03 | landsat | P5/P95 | 0.103925 | 0.466934 |
| AOI-03 | landsat | P10/P90 | 0.117801 | 0.375375 |
| AOI-03 | modis | P1/P99 | 0.101573 | 0.561351 |
| AOI-03 | modis | P2/P98 | 0.109323 | 0.524801 |
| AOI-03 | modis | P5/P95 | 0.121365 | 0.449628 |
| AOI-03 | modis | P10/P90 | 0.136854 | 0.369857 |
| AOI-03 | sentinel2 | P1/P99 | 0.042842 | 0.562011 |
| AOI-03 | sentinel2 | P2/P98 | 0.051024 | 0.510478 |
| AOI-03 | sentinel2 | P5/P95 | 0.063519 | 0.418813 |
| AOI-03 | sentinel2 | P10/P90 | 0.076187 | 0.343647 |

## 4. Full DPM performance

| AOI | sensor | quantile_configuration | target_evaluation_pairs | RMSE | MAE | Bias | R2 | Pearson_r | low_clip_ratio | high_clip_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AOI-00 | landsat | P1/P99 | 20251 | 0.227810 | 0.217308 | 0.205169 | -4.374954 | 0.873663 | 0.010024 | 0.010024 |
| AOI-00 | landsat | P2/P98 | 20251 | 0.220646 | 0.207647 | 0.185142 | -4.042190 | 0.869590 | 0.019999 | 0.019999 |
| AOI-00 | landsat | P5/P95 | 20251 | 0.206132 | 0.180694 | 0.106283 | -3.400652 | 0.845703 | 0.050022 | 0.050022 |
| AOI-00 | landsat | P10/P90 | 20251 | 0.245207 | 0.207915 | 0.016961 | -5.227207 | 0.804288 | 0.099995 | 0.099995 |
| AOI-00 | modis | P1/P99 | 20256 | 0.207636 | 0.195786 | 0.186089 | -3.441404 | 0.917512 | 0.010022 | 0.010022 |
| AOI-00 | modis | P2/P98 | 20256 | 0.194799 | 0.177771 | 0.153845 | -2.909219 | 0.911044 | 0.020043 | 0.020043 |
| AOI-00 | modis | P5/P95 | 20256 | 0.195419 | 0.165437 | 0.071141 | -2.934115 | 0.879931 | 0.050010 | 0.050010 |
| AOI-00 | modis | P10/P90 | 20256 | 0.243635 | 0.206601 | -0.001408 | -5.114951 | 0.839585 | 0.100020 | 0.100020 |
| AOI-00 | sentinel2 | P1/P99 | 19233 | 0.197261 | 0.176979 | 0.155649 | -3.053219 | 0.802747 | 0.010035 | 0.010035 |
| AOI-00 | sentinel2 | P2/P98 | 19233 | 0.193628 | 0.170650 | 0.130013 | -2.905270 | 0.792420 | 0.020018 | 0.020018 |
| AOI-00 | sentinel2 | P5/P95 | 19233 | 0.208446 | 0.177749 | 0.059206 | -3.525879 | 0.752309 | 0.050018 | 0.050018 |
| AOI-00 | sentinel2 | P10/P90 | 19233 | 0.258527 | 0.221237 | -0.000833 | -5.961919 | 0.704583 | 0.100036 | 0.099984 |
| AOI-01 | landsat | P1/P99 | 14738 | 0.485953 | 0.449701 | 0.449701 | -80855.448639 | 0.422592 | 0.010042 | 0.010042 |
| AOI-01 | landsat | P2/P98 | 14738 | 0.502003 | 0.451925 | 0.451925 | -86284.508927 | 0.400608 | 0.020016 | 0.020016 |
| AOI-01 | landsat | P5/P95 | 14738 | 0.539360 | 0.467709 | 0.467709 | -99604.665402 | 0.359651 | 0.050007 | 0.050007 |
| AOI-01 | landsat | P10/P90 | 14738 | 0.584329 | 0.489132 | 0.489132 | -116906.046061 | 0.311191 | 0.100014 | 0.100014 |
| AOI-01 | modis | P1/P99 | 19878 | 0.430313 | 0.381586 | 0.381586 | -60970.944166 | 0.469581 | 0.010011 | 0.009961 |
| AOI-01 | modis | P2/P98 | 19878 | 0.460206 | 0.397699 | 0.397699 | -69736.570565 | 0.435854 | 0.020022 | 0.020022 |
| AOI-01 | modis | P5/P95 | 19878 | 0.513508 | 0.431405 | 0.431404 | -86826.416761 | 0.379035 | 0.049955 | 0.050005 |
| AOI-01 | modis | P10/P90 | 19878 | 0.562714 | 0.463014 | 0.463013 | -104263.702902 | 0.324784 | 0.100010 | 0.100010 |
| AOI-01 | sentinel2 | P1/P99 | 19878 | 0.421517 | 0.378039 | 0.378039 | -58503.880355 | 0.456435 | 0.010011 | 0.010011 |
| AOI-01 | sentinel2 | P2/P98 | 19878 | 0.462201 | 0.404229 | 0.404229 | -70342.371410 | 0.416189 | 0.020022 | 0.020022 |
| AOI-01 | sentinel2 | P5/P95 | 19878 | 0.520181 | 0.439832 | 0.439831 | -89097.649448 | 0.358498 | 0.049955 | 0.050005 |
| AOI-01 | sentinel2 | P10/P90 | 19878 | 0.568611 | 0.467643 | 0.467643 | -106460.470735 | 0.309163 | 0.100010 | 0.100010 |
| AOI-02 | landsat | P1/P99 | 7600 | 0.211092 | 0.191117 | 0.186675 | -0.904330 | 0.929384 | 0.009868 | 0.010000 |
| AOI-02 | landsat | P2/P98 | 7600 | 0.217203 | 0.195741 | 0.188295 | -1.016185 | 0.928830 | 0.019868 | 0.019868 |
| AOI-02 | landsat | P5/P95 | 7600 | 0.225137 | 0.199436 | 0.177959 | -1.166169 | 0.922301 | 0.050000 | 0.049868 |
| AOI-02 | landsat | P10/P90 | 7600 | 0.229137 | 0.198198 | 0.129024 | -1.243818 | 0.891007 | 0.100000 | 0.099868 |
| AOI-02 | modis | P1/P99 | 16568 | 0.203979 | 0.186310 | 0.183335 | -0.469287 | 0.958724 | 0.010019 | 0.010019 |
| AOI-02 | modis | P2/P98 | 16568 | 0.212057 | 0.192802 | 0.187546 | -0.587969 | 0.958569 | 0.020039 | 0.020039 |
| AOI-02 | modis | P5/P95 | 16568 | 0.217685 | 0.195292 | 0.179608 | -0.673370 | 0.956263 | 0.050036 | 0.050036 |
| AOI-02 | modis | P10/P90 | 16568 | 0.221600 | 0.194420 | 0.146517 | -0.734106 | 0.939877 | 0.100012 | 0.100012 |
| AOI-02 | sentinel2 | P1/P99 | 18534 | 0.180035 | 0.155961 | 0.142930 | -0.118153 | 0.939230 | 0.010036 | 0.010036 |
| AOI-02 | sentinel2 | P2/P98 | 18534 | 0.190065 | 0.165003 | 0.148259 | -0.246211 | 0.938815 | 0.020017 | 0.020017 |
| AOI-02 | sentinel2 | P5/P95 | 18534 | 0.208708 | 0.181851 | 0.156938 | -0.502678 | 0.936464 | 0.050016 | 0.050016 |
| AOI-02 | sentinel2 | P10/P90 | 18534 | 0.222199 | 0.192571 | 0.139268 | -0.703234 | 0.922185 | 0.100032 | 0.100032 |
| AOI-03 | landsat | P1/P99 | 14402 | 0.209687 | 0.174044 | 0.172194 | -3.301035 | 0.936724 | 0.010068 | 0.010068 |
| AOI-03 | landsat | P2/P98 | 14402 | 0.228265 | 0.186755 | 0.184187 | -4.096936 | 0.935304 | 0.020067 | 0.020067 |
| AOI-03 | landsat | P5/P95 | 14402 | 0.284168 | 0.229981 | 0.225206 | -6.899205 | 0.921117 | 0.050062 | 0.050062 |
| AOI-03 | landsat | P10/P90 | 14402 | 0.371869 | 0.303180 | 0.295338 | -12.527299 | 0.874418 | 0.100056 | 0.100056 |
| AOI-03 | modis | P1/P99 | 17860 | 0.219341 | 0.189951 | 0.189464 | -3.552454 | 0.965277 | 0.010022 | 0.010022 |
| AOI-03 | modis | P2/P98 | 17860 | 0.240866 | 0.205074 | 0.204071 | -4.489830 | 0.963456 | 0.020045 | 0.020045 |
| AOI-03 | modis | P5/P95 | 17860 | 0.300291 | 0.252336 | 0.249970 | -7.532777 | 0.948923 | 0.050000 | 0.050000 |
| AOI-03 | modis | P10/P90 | 17860 | 0.390798 | 0.325761 | 0.320776 | -13.451431 | 0.903589 | 0.100000 | 0.100000 |
| AOI-03 | sentinel2 | P1/P99 | 18857 | 0.207473 | 0.172003 | 0.169253 | -3.154114 | 0.922312 | 0.010023 | 0.010023 |
| AOI-03 | sentinel2 | P2/P98 | 18857 | 0.235718 | 0.192738 | 0.189159 | -4.362178 | 0.920217 | 0.020046 | 0.019993 |
| AOI-03 | sentinel2 | P5/P95 | 18857 | 0.302940 | 0.245983 | 0.240452 | -7.856641 | 0.903973 | 0.050008 | 0.049955 |
| AOI-03 | sentinel2 | P10/P90 | 18857 | 0.378065 | 0.307433 | 0.298833 | -12.793915 | 0.869708 | 0.100016 | 0.100016 |

## 5. DPM versus OLS summary

| AOI | sensor | quantile_configuration | RMSE_DPM | OLS_history | RMSE_OLS | Delta_RMSE_DPM_minus_OLS | RMSE_ratio_DPM_over_OLS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AOI-00 | landsat | P5/P95 | 0.206132 | W2023 | 0.047623 | 0.158509 | 4.328436 |
| AOI-01 | landsat | P1/P99 | 0.485953 | W2023 | 0.001356 | 0.484597 | 358.473277 |
| AOI-02 | landsat | P1/P99 | 0.211092 | W2022 | 0.056423 | 0.154669 | 3.741234 |
| AOI-03 | landsat | P1/P99 | 0.209687 | W2022 | 0.035253 | 0.174433 | 5.948005 |
| AOI-00 | modis | P2/P98 | 0.194799 | W2022_2023 | 0.038868 | 0.155932 | 5.011845 |
| AOI-01 | modis | P1/P99 | 0.430313 | W2022 | 0.001397 | 0.428915 | 307.916177 |
| AOI-02 | modis | P1/P99 | 0.203979 | W2023 | 0.048153 | 0.155826 | 4.236039 |
| AOI-03 | modis | P1/P99 | 0.219341 | W2024 | 0.028290 | 0.191051 | 7.753263 |
| AOI-00 | sentinel2 | P2/P98 | 0.193628 | W2022 | 0.063083 | 0.130544 | 3.069389 |
| AOI-01 | sentinel2 | P1/P99 | 0.421517 | W2022 | 0.001324 | 0.420193 | 318.303453 |
| AOI-02 | sentinel2 | P1/P99 | 0.180035 | W2022_2024 | 0.058442 | 0.121593 | 3.080583 |
| AOI-03 | sentinel2 | P1/P99 | 0.207473 | W2022 | 0.039519 | 0.167954 | 5.249990 |

## 6. Geographic interpretation

The selected DPM pair varied: P1/P99 was selected in 9/12 comparisons, P2/P98 in 2/12, and P5/P95 in 1/12. OLS had lower descriptive RMSE in all 12 comparisons. DPM/OLS ratios ranged from 3.069389 (Sentinel-2 AOI-00) to 358.473277 (Landsat 8/9 AOI-01). AOI-01 is anomalous because its FCOVER reference is near zero; its very small OLS errors make the ratio especially unstable for interpretation. The results do not establish universal algorithm superiority.

## 7. Manuscript synchronization

- [x] Abstract
- [x] Introduction and RQ1
- [x] Methods
- [x] Validation-design table
- [x] Results and all-AOI DPM table
- [x] Discussion
- [x] Limitations
- [x] Conclusion
- [x] Cover Letter

The workflow figure did not state that DPM was AOI-00-only and was therefore not redrawn. The DPM benchmark remains separate from historical OLS fitting and Rolling-Origin evaluation.

## 8. Old AOI-00 language audit

Active main-manuscript and cover-letter sources contain no remaining AOI-00-only DPM design statement. Remaining AOI-00/DPM mentions are legitimate AOI-specific numerical results, not claims that DPM was only evaluated in AOI-00. The retained supplementary source was also changed to all-AOI wording; it is not submitted.

## 9. Numerical regression audit

Stage 2 did not rerun or alter OLS fitting. The source Multi-AOI and Rolling-Origin files remain immutable inputs. The 72 Multi-AOI OLS runs, 72 Rolling-Origin OLS runs, 144 formal OLS-run taxonomy, 10/24 versus 14/24 trajectory classification, paired block statistics, LOYO, reserve, and Holm family structure were preserved.

## 10. Deferred-task confirmation

Stage 2 did not change the 5 km block scale, run block-size or temporal-window sensitivity, introduce a valid-area threshold, rerun Landsat aerosol QA, redesign DPM, or perform final Applied Geomatics formatting.

## Execution and integrity record

```json
{
  "timestamp_utc": "2026-08-29T10:32:47.988219+00:00",
  "status": "PASS",
  "code": "publication/code/scripts/33_run_stage2_dpm.py",
  "code_sha256": "ec2342d8ce98d031aefd82de1913921218066870ddaf88ff8bca327b513493d1",
  "endpoint_function": "publication/code/src/models/endpoint.py:endpoint_predict",
  "legacy_source": "reports/endpoint_sensitivity_metrics.csv",
  "legacy_source_sha256": "5929bb223c897d161506a63b3de273fa25bafdcc462401fa758d7a1211a5b049",
  "all_aoi_target_pairs": "publication/new_experiments/08_scientific_execution/raw_machine_outputs/paired_observations.csv.gz",
  "all_aoi_target_pairs_sha256": "cb439b63d5d346abdc8d2b8bf0e1a2204045c784e73ab8225e67c4fa47cbccfb",
  "ols_source": "publication/new_experiments/08_scientific_execution/04_master_tables/multi_aoi_run_results.csv",
  "ols_source_sha256": "d09e6738d38cc2a3a5e84ed4c4619eb65e82d0e5c3484b0fe8fb27f3e8488565",
  "quantile_method": "numpy.percentile default linear interpolation",
  "quantile_input": "pooled finite 2025 NDVI values per AOI x sensor across nominal dates",
  "clip_rule": "numpy.clip((NDVI-NDVI_low)/(NDVI_high-NDVI_low), 0, 1)",
  "bias_rule": "prediction minus FCOVER",
  "checks": {
    "aoi00_reproduction_pass": true,
    "candidate_rows": 48,
    "expected_candidate_rows": 48,
    "candidate_matrix_complete": true,
    "best_summary_rows": 12,
    "expected_best_summary_rows": 12,
    "all_target_year_2025": true,
    "all_predictions_clipped_0_1": true,
    "quantiles_computed_without_fcover": true,
    "ols_target_pair_counts_match_dpm": true
  }
}
```
