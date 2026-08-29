from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GridContract:
    crs: str
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    provenance: str = "native_fcover_product_grid"

    @classmethod
    def from_dataset(cls, dataset: Any) -> "GridContract":
        return cls(str(dataset.crs), tuple(float(v) for v in dataset.transform[:6]), dataset.width, dataset.height)

    def assert_same(self, other: "GridContract") -> None:
        if self != other:
            raise ValueError(f"FCOVER_NATIVE_GRID_CHANGED: expected={self!r}, actual={other!r}")

