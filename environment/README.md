# Environment

Use Python 3.11 or later. The minimal, local numerical-verification environment is installed with `python -m pip install -r environment/requirements.txt`; it is sufficient for `python code/reproduce_results.py` and the bundled regression tests.

For the full source tree, install the project metadata with `python -m pip install -e code`. This adds the optional geospatial and upstream-acquisition dependencies declared in `code/pyproject.toml` (including Rasterio, GeoPandas, Shapely, PyProj, Earth Engine, and the HTTP clients). Geospatial wheels may require system libraries supplied by the platform package manager; package-specific installation guidance is outside this frozen repository.

Exact Earth Engine/cloud credentials are intentionally not part of this repository. The upstream-acquisition entry point reads a user-local environment file named by `FVC_EE_ENV_FILE` and requires `EE_PROJECT_ID`; it is not needed for the committed-data verification workflow.
