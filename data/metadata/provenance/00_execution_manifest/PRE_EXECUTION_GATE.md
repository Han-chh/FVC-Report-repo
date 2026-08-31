# Pre-execution gate

**Result: PASS**

| Gate | Status | Evidence |
|---|---|---|
| readiness config | PASS | readiness validation active; scientific execution remains disabled |
| frozen design hash | PASS | b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b |
| four AOIs | PASS | registered AOIs: ['AOI-00', 'AOI-01', 'AOI-02', 'AOI-03'] |
| 2021–2025 data availability | PASS | all final-AOI AOI-year products READY |
| Sentinel source manifests | PASS | 807 exact asset-verified source-scene rows across 60 AOI/date groups |
| Landsat source manifests | PASS | 765 exact asset-verified source-scene rows across 60 AOI/date groups |
| MODIS source manifests | PASS | 420 exact asset-verified source-scene rows across 60 AOI/date groups |
| MODIS temporal rule | PASS | 8-day_best_observation_with_support_interval_overlapping_nominal_window |
| FCOVER valid-domain semantics | PASS | derived valid-domain mask; QFLAG/NOBS remain product-provided |
| FCOVER source schema | PASS | all active FCOVER revisions are schema- and provenance-verified |
| FCOVER active asset provenance | PASS | all active FCOVER revisions are schema- and provenance-verified |
| processing hashes | PASS | persisted active processing identity matches source/design contract |
| FCOVER grid | PASS | all three source/GEE/local target grids align |
| GEE/local Sentinel parity | PASS | active metric-derived three-sensor parity evidence passes |
| GEE/local Landsat parity | PASS | active metric-derived three-sensor parity evidence passes |
| GEE/local MODIS parity | PASS | active metric-derived three-sensor parity evidence passes |
| 5 km block stability | PASS | persisted namespaced cross-year block manifest verified |
| reserve isolation | PASS | seed=42 SHA-256 deterministic reserve contract; runner asserts development-only diagnostics |
| rolling chronology | PASS | all six primary windows precede their targets |
| target-label leakage | PASS | chronology guard and target-isolated runner path are active |
| Paired-cube provenance | PASS | all active paired cubes have verified FCOVER lineage |
| output-path readiness | PASS | output root writable |
| scientific input manifest | PASS | final scientific input manifest frozen |
| GEE task completeness | PASS | 60 FCOVER and 20 paired-cube preparation assets verified |
| removed experiment exclusion | PASS | Normal/Strict sensitivity excluded |
| scientific execution interlock | PASS | formal execution remains disabled and unacknowledged |
| no premature scientific results | PASS | no model/result artifacts; validated extraction-only paired cache present |
