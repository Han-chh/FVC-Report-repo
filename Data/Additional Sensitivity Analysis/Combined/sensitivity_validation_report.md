# Sensitivity Validation Report

| Validation | Status | Evidence |
|---|---|---|
| Aggregation Route A reproduction | PASS | 100.00% (13/13) |
| Aggregation Route B checkpoints | PASS | Route A PASS; Route B 60/60; canonical pairs and downstream outputs readable |
| Aggregation matched support | PASS | canonical paired identity intersection |
| Frozen primary integrity | PASS | hash ledger confirmed |
| Temporal checkpoints | PASS | 60/60 |
| Temporal duplicate source identities | PASS | 0 |
| Temporal schema validation | PASS | canonical downstream pair schema |
| Temporal downstream completion | PASS | full and matched-support evaluation |
| Aerosol provenance | PASS | exact Landsat C2 L2 scene IDs |
| Aerosol decoder | PASS | USGS LaSRC bits |
| Aerosol exact-scene association | PASS | same-image band selection |
| Aerosol downstream completion | PASS | four modes, full and matched-support evaluation |
| Combined output integrity | PASS | summary rows=40; matrix rows=15 |
