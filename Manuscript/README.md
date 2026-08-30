# Integrated Applied Geomatics manuscript snapshot

This directory is the source and compiled-PDF snapshot of the final manuscript integration. It includes the primary paper, supplementary material, the compact main-text sensitivity table, and detailed Supplementary Tables S7--S9. The authoritative sensitivity values and the manuscript traceability audit are in `../Data/Additional Sensitivity Analysis/Combined/`.

From this directory, compile the main paper with:

```bash
tectonic -X compile manuscript_final_submission.tex
```

Compile the supplementary material from `supplementary/`. The DPM inputs used there are retained under `../Ripple/`.
