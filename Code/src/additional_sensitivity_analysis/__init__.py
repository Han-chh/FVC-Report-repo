"""Thin, configuration-driven sensitivity extensions for the frozen FVC pipeline.

The package deliberately provides no automatic execution entry point.  Future
production runs must be explicitly requested through one of the wrappers in
``Code/Additional Sensitivity Analysis``.
"""

from .schemas import SensitivityDatasetConfig

__all__ = ["SensitivityDatasetConfig"]
