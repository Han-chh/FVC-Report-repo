# Rolling-origin experiment design

Question: does increasing historical calibration extent consistently improve forward-year agreement with the Copernicus FCOVER operational reference?

The primary matrix contains exactly six prespecified configurations: 1/2/3-year histories for target 2024 and the symmetric 1/2/3-year histories for target 2025. The 2021-2024→2025 window exists only as a disabled optional configuration and cannot enter the primary comparison.

For every AOI × sensor × window: build deterministic 5 km blocks; restrict Spatial GroupKFold and LOYO to Development; fit Development-only for the historical reserve diagnostic; refit Development+reserve; then apply to target NDVI. One-year windows report LOYO=`NOT_APPLICABLE`.

2024 is a retrospective/secondary forward-chaining target. 2025 remains the primary independent future-year evaluation. Neither is used to tune AOIs, QA, blocks, or windows.

