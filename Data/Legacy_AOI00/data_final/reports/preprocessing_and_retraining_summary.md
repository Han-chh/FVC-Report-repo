# Preprocessing and retraining summary

## Execution summary

All 12 source-year × target-date support-domain composites were rebuilt from raw assets into this output directory; 18 OLS models, 3 P5/P95 formula baselines, and 21 2025 application/comparison tasks were emitted. Configuration hash: `f11871b0cab9e78afd499cc23a4f9a106b6ba9448ff313b3ed91d83ec7716beb`. QA hash: `0909096b4ec2554e55705d25a822e1c1d912cb3dc73d579e3026d4be3f239912`.

## QA treatment

Sentinel-2 excludes SCL 0,1,3,6,8,9,10,11 and cloud probability ≥40 per observation before NDVI. MODIS uses State land/water bits 3–5 (only value 1 land retained) plus State cloud/shadow/cirrus/internal-cloud/snow/adjacent-cloud/aerosol and QA MODLAND/band1/band2/atmospheric-correction flags. Landsat keeps its frozen QA_PIXEL/QA_RADSAT rule and receives no new water rule.

## Support and evaluation

Every sample is one FCOVER 300-m footprint × date × year. The prediction operation is NDVI aggregation on FCOVER support, then `a × NDVI + b`, clip [0,1]. Difference is prediction minus FCOVER.

## Common-mask verification

{
  "sentinel2": {
    "checksums": [
      "a540cc82c5be604e850c9d1aad6fa78d67e069cbd85de06e542d0459c31110a7"
    ],
    "n": [
      28540
    ]
  },
  "landsat": {
    "checksums": [
      "d5d8cf7a001072d7ec58057b3e5974ba985842015b89f030a14f6fa2e187357a"
    ],
    "n": [
      30220
    ]
  },
  "modis": {
    "checksums": [
      "b9374536b152093b1c881ddc9e5c291fed43a39e7f441e9252b1fcdd3ad8edd8"
    ],
    "n": [
      29214
    ]
  }
}

## Result table

See `final_21_experiment_metrics.csv`, `model_parameters.csv`, and per-task manifests. Metrics are generated from `comparison_stats.json`, never transcribed from a plot.

## Limits

Product-native QA classes differ across sources. Landsat water behavior remains intentionally unchanged. FCOVER is a 300-m reference, not ground truth; results do not validate a hypothetical finer-grid product.
