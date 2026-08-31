"""Thin, configuration-driven sensitivity extensions for the frozen FVC pipeline.

The package deliberately provides no automatic execution entry point.  Future
production runs must be explicitly requested through one of the wrappers in
the final processing-sensitivity workflows.
"""

from .schemas import SensitivityDatasetConfig

__all__ = ["SensitivityDatasetConfig"]
