# Formal scientific execution authorization — 2026-08-11

## Authorization

Authorization source: `explicit_user_authorization`

Authorization scope: `frozen_scientific_execution_only`

The user explicitly authorized formal Scientific Execution after successful
implementation remediation and readiness re-audit.

## Execution boundary

Authorized:

- execute every registered Multi-AOI unit;
- execute every registered Rolling-Origin unit;
- obtain and validate formal scientific data and result artifacts;
- compute only the metrics, block results, statistics, and comparisons already
  present in the frozen protocol;
- produce machine-readable master tables, manifests, figures, factual data
  overview, and researcher summary.

Not authorized:

- modify manuscript prose, tables, bibliography, or compiled manuscript files;
- change the frozen design, processing payload, samples, thresholds, years,
  windows, blocks, model, metrics, or inference rules;
- add the excluded Normal-vs-Strict FCOVER sensitivity experiment;
- write Discussion-style causal or ecological interpretation.

## Preflight snapshot

- frozen design hash: `b21c8cc7f3d4d35e1db4dfa1c8245ff10ba657c0a0a001992b552808766cc49b`;
- frozen processing hash: `3fab57b81623045f745beeaa0c1615c51b0d44344beaa74a1025ee4450b699c7`;
- publication tests: 85/85 PASS;
- protected evidence: 84/84 unchanged;
- paired extraction groups: 60/60;
- Multi-AOI dry-run: 72;
- Rolling-Origin dry-run: 72;
- active GEE tasks: 0;
- unregistered model-result files: 0.

State transition uses the existing contract fields only:

```text
phase: scientific_execution
scientific_execution_enabled: true
execution_acknowledged: true
```

