# Unresolved issues

No undisclosed high-risk issue. The original MODIS raw archive lacked the required `QA` band; this run fetched it anew from the same MODIS/061/MOD09Q1 image IDs into `raw_assets/modis`, and records its checksum. No legacy derived products were reused.
