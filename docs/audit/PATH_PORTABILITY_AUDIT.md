# Path Portability Audit

## Result

Active runnable code has no dependency on `/Users/hankchen`, `/Users`, or the former desktop workspace path.

## Changes

- Removed the machine-specific external-path configuration.
- Refactored the local verifier and active processing code to repository-relative `pathlib.Path` locations.
- Moved canonical inputs, metadata, and results to stable lowercase public paths.

## Retained provenance paths

The locked Phase 3 audit records historical source paths inside `docs/audit/` and `docs/methodology/`. These are provenance-only documentation, not runnable configuration.
