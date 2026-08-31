# Scientific Content Preservation Audit

## Result: PASS

The canonical paired dataset was moved without row or value changes and gzip-compressed for repository distribution. Its SHA-256 is `ca7237ba51a164c1f3247fa423dbbd10e0be2954aa19c6f31fb9262d703e7381`.

`code/reproduce_results.py` recomputed and exactly matched all 72 Multi-AOI OLS rows, all 72 Rolling-Origin OLS rows, and all 48 DPM rows. The locked result manifest and final sensitivity summaries were transferred without regeneration.

The pre-consolidation checksum ledger is `PRECONSOLIDATION_AUTHORITATIVE_SHA256.txt`; it preserves hashes for pure file moves.
