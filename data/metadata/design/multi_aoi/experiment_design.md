# Multi-AOI experiment design

The future experiment applies the exact frozen publication pipeline independently to AOI-00 through AOI-03 for Sentinel-2, Landsat 8/9, and MODIS. AOI-specific tuning is forbidden. Every AOI uses the same three nominal dates, ±15-day window, n≥2, native FCOVER support, blocks, reserve logic, OLS, clipping, metrics, and baseline FCOVER screening (QFLAG, NOBS, and the derived source-validity domain).

Primary summaries are AOI×sensor×target-year. Block inference remains within AOI; cross-AOI claims use replication/consistency rather than treating all blocks as iid. Multi-AOI results are not generated in the preparation phase.
