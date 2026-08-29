"""Deterministic, resumable engineering primitives for parity extraction.

These utilities deliberately contain no scientific QA, NDVI, aggregation, or
temporal-composite rule.  They only make extraction bounded and auditable.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np


DEFAULT_REQUEST_BUDGET_BYTES = 24 * 1024 * 1024


@dataclass(frozen=True)
class Tile:
    tile_id: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    parent_tile_id: str = ""

    @property
    def width(self) -> int:
        return self.col_end - self.col_start

    @property
    def height(self) -> int:
        return self.row_end - self.row_start


@dataclass(frozen=True)
class RequestPlan:
    width: int
    height: int
    requested_bands: tuple[str, ...]
    dtype_bytes_per_pixel: int
    estimated_bytes: int
    budget_bytes: int
    mode: str
    tile_width: int
    tile_height: int
    tiles: tuple[Tile, ...]


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class PixelRequestPlanner:
    """Plan requests conservatively before contacting Earth Engine."""

    def __init__(self, budget_bytes: int = DEFAULT_REQUEST_BUDGET_BYTES, max_tile_edge: int = 1024):
        if budget_bytes <= 0 or max_tile_edge <= 0:
            raise ValueError("REQUEST_PLANNER_CONFIGURATION_INVALID")
        self.budget_bytes = int(budget_bytes)
        self.max_tile_edge = int(max_tile_edge)

    @staticmethod
    def estimate_bytes(width: int, height: int, dtype_bytes_per_pixel: int) -> int:
        if min(width, height, dtype_bytes_per_pixel) <= 0:
            raise ValueError("REQUEST_DIMENSIONS_INVALID")
        return int(width) * int(height) * int(dtype_bytes_per_pixel)

    def plan(self, *, prefix: str, width: int, height: int, requested_bands: Sequence[str], dtype_bytes_per_pixel: int) -> RequestPlan:
        estimated = self.estimate_bytes(width, height, dtype_bytes_per_pixel)
        if estimated <= self.budget_bytes:
            tiles = (Tile(f"{prefix}_R000_C000", 0, height, 0, width),)
            return RequestPlan(width, height, tuple(requested_bands), dtype_bytes_per_pixel, estimated,
                               self.budget_bytes, "FULL_WINDOW", width, height, tiles)
        max_pixels = max(1, self.budget_bytes // dtype_bytes_per_pixel)
        edge = max(1, min(self.max_tile_edge, int(math.sqrt(max_pixels))))
        # At a fixed row width, choose the largest deterministic height that
        # remains below budget. This avoids a hidden oversize rightmost tile.
        tile_width = min(edge, width)
        tile_height = max(1, min(edge, max_pixels // tile_width, height))
        tiles = tuple(self._tiles(prefix, width, height, tile_width, tile_height))
        validate_tile_coverage(tiles, width, height)
        return RequestPlan(width, height, tuple(requested_bands), dtype_bytes_per_pixel, estimated,
                           self.budget_bytes, "TILED", tile_width, tile_height, tiles)

    @staticmethod
    def _tiles(prefix: str, width: int, height: int, tile_width: int, tile_height: int) -> Iterable[Tile]:
        for row in range(0, height, tile_height):
            for col in range(0, width, tile_width):
                yield Tile(f"{prefix}_R{row:05d}_C{col:05d}", row, min(height, row + tile_height),
                           col, min(width, col + tile_width))

    @staticmethod
    def subdivide(tile: Tile) -> tuple[Tile, ...]:
        """Deterministically split a rejected tile into non-overlapping quadrants."""
        if tile.width == 1 and tile.height == 1:
            raise ValueError("REQUEST_TOO_LARGE_AT_SINGLE_PIXEL")
        row_mid = tile.row_start + max(1, tile.height // 2)
        col_mid = tile.col_start + max(1, tile.width // 2)
        bounds = ((tile.row_start, row_mid, tile.col_start, col_mid),
                  (tile.row_start, row_mid, col_mid, tile.col_end),
                  (row_mid, tile.row_end, tile.col_start, col_mid),
                  (row_mid, tile.row_end, col_mid, tile.col_end))
        children = []
        for index, (r0, r1, c0, c1) in enumerate(bounds):
            if r0 < r1 and c0 < c1:
                children.append(Tile(f"{tile.tile_id}_Q{index + 1}", r0, r1, c0, c1, tile.tile_id))
        validate_tile_coverage(children, tile.width, tile.height, origin=(tile.row_start, tile.col_start))
        return tuple(children)


def validate_tile_coverage(tiles: Sequence[Tile], width: int, height: int, origin: tuple[int, int] = (0, 0)) -> None:
    """Reject tiles with gaps, overlaps, or extents outside their declared grid."""
    if not tiles:
        raise ValueError("TILE_COVERAGE_EMPTY")
    row0, col0 = origin
    expected = width * height
    # The planner uses at most 1024-pixel tiles; a compact boolean audit is
    # safe and detects every single-pixel gap/overlap deterministically.
    coverage = np.zeros((height, width), dtype=np.uint8)
    for tile in tiles:
        if tile.row_start < row0 or tile.col_start < col0 or tile.row_end > row0 + height or tile.col_end > col0 + width:
            raise ValueError("TILE_OUTSIDE_DECLARED_GRID")
        coverage[tile.row_start - row0:tile.row_end - row0, tile.col_start - col0:tile.col_end - col0] += 1
    if coverage.size != expected or np.any(coverage != 1):
        raise ValueError("TILE_COVERAGE_GAP_OR_OVERLAP")


def classify_request_error(error: BaseException | str) -> str:
    text = str(error).lower()
    if "request size" in text or "too large" in text or "50331648" in text:
        return "REQUEST_TOO_LARGE"
    if "429" in text or "rate" in text or "quota" in text:
        return "RATE_LIMITED"
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    if "401" in text or "403" in text or "auth" in text or "credential" in text:
        return "AUTH_ERROR"
    if "grid" in text or "crs" in text or "transform" in text or "dimensions" in text:
        return "INVALID_GRID"
    if "500" in text or "502" in text or "503" in text or "server" in text or "ssl" in text or "connection" in text or "eof" in text:
        return "TRANSIENT_SERVER_ERROR"
    return "OTHER"


class ExactQuantileStore:
    """Disk-backed exact absolute-difference store, isolated from science data."""

    def __init__(self, root: Path):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def add(self, tile_id: str, values: np.ndarray) -> Path:
        path = self.root / f"{tile_id}.npy"
        temporary = path.with_suffix(".npy.partial")
        with temporary.open("wb") as stream:
            np.save(stream, np.asarray(values, dtype="float64"))
        temporary.replace(path)
        return path

    def values(self) -> np.ndarray:
        paths = sorted(self.root.glob("*.npy"))
        return np.concatenate([np.load(path, allow_pickle=False) for path in paths]) if paths else np.empty(0, dtype="float64")


class StreamingMetrics:
    """Exact streaming sufficient statistics plus disk-backed exact quantiles."""

    def __init__(self, quantile_store: ExactQuantileStore | None = None):
        self.store = quantile_store
        self.total = self.valid_local = self.valid_gee = self.common = self.mask_disagreement = 0
        self.sum_local = self.sum_gee = self.sum_diff = self.sum_abs = self.sum_sq = self.max_abs = 0.0
        self.sum_x2 = self.sum_y2 = self.sum_xy = 0.0

    def add(self, tile_id: str, local: np.ndarray, gee: np.ndarray) -> None:
        local_ok, gee_ok = np.isfinite(local), np.isfinite(gee)
        common = local_ok & gee_ok
        self.total += int(local.size); self.valid_local += int(local_ok.sum()); self.valid_gee += int(gee_ok.sum())
        self.common += int(common.sum()); self.mask_disagreement += int(np.count_nonzero(local_ok != gee_ok))
        if not common.any():
            return
        x = local[common].astype("float64"); y = gee[common].astype("float64"); delta = x - y; absolute = np.abs(delta)
        self.sum_local += float(x.sum()); self.sum_gee += float(y.sum()); self.sum_diff += float(delta.sum())
        self.sum_abs += float(absolute.sum()); self.sum_sq += float(np.dot(delta, delta)); self.max_abs = max(self.max_abs, float(absolute.max()))
        self.sum_x2 += float(np.dot(x, x)); self.sum_y2 += float(np.dot(y, y)); self.sum_xy += float(np.dot(x, y))
        if self.store is not None:
            self.store.add(tile_id, absolute)

    def result(self) -> dict[str, float | int]:
        n = self.common
        if not n:
            return {"total_cells": self.total, "valid_local": self.valid_local, "valid_GEE": self.valid_gee, "common_valid": 0, "mask_disagreement": self.mask_disagreement}
        denominator = math.sqrt(max(0.0, (n * self.sum_x2 - self.sum_local ** 2) * (n * self.sum_y2 - self.sum_gee ** 2)))
        correlation = (n * self.sum_xy - self.sum_local * self.sum_gee) / denominator if denominator else 1.0
        values = self.store.values() if self.store else np.empty(0)
        return {"total_cells": self.total, "valid_local": self.valid_local, "valid_GEE": self.valid_gee, "common_valid": n, "mask_disagreement": self.mask_disagreement,
                "mean_signed_difference": self.sum_diff / n, "mean_absolute_difference": self.sum_abs / n,
                "median_absolute_difference": float(np.quantile(values, .5)) if values.size else math.nan,
                "P95_absolute_difference": float(np.quantile(values, .95)) if values.size else math.nan,
                "P99_absolute_difference": float(np.quantile(values, .99)) if values.size else math.nan,
                "implementation_RMSE": math.sqrt(self.sum_sq / n), "max_absolute_difference": self.max_abs,
                "Pearson_correlation": correlation}

    def payload(self) -> dict[str, float | int]:
        """Serializable sufficient statistics for one verified tile."""
        return {name: getattr(self, name) for name in ("total", "valid_local", "valid_gee", "common", "mask_disagreement", "sum_local", "sum_gee", "sum_diff", "sum_abs", "sum_sq", "max_abs", "sum_x2", "sum_y2", "sum_xy")}

    def merge_payload(self, payload: dict[str, float | int]) -> None:
        for name in ("total", "valid_local", "valid_gee", "common", "mask_disagreement", "sum_local", "sum_gee", "sum_diff", "sum_abs", "sum_sq", "sum_x2", "sum_y2", "sum_xy"):
            setattr(self, name, getattr(self, name) + payload[name])
        self.max_abs = max(self.max_abs, float(payload["max_abs"]))


class SQLiteCheckpoint:
    """Atomic parity-tile checkpoints; the identity tuple prevents stale reuse."""

    def __init__(self, path: Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS tile_checkpoint (
            tile_id TEXT PRIMARY KEY, identity_hash TEXT NOT NULL, status TEXT NOT NULL,
            payload_json TEXT NOT NULL, completed_at TEXT NOT NULL)""")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def verified(self, tile_id: str, identity: dict[str, Any]) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT identity_hash,status,payload_json FROM tile_checkpoint WHERE tile_id=?", (tile_id,)).fetchone()
        if row is None:
            return None
        expected = canonical_hash(identity)
        if row[0] != expected:
            self.connection.execute("UPDATE tile_checkpoint SET status='STALE', completed_at=? WHERE tile_id=?", (datetime.now(timezone.utc).isoformat(), tile_id)); self.connection.commit()
            return None
        return json.loads(row[2]) if row[1] == "VERIFIED_COMPLETE" else None

    def save(self, tile_id: str, identity: dict[str, Any], payload: dict[str, Any], status: str = "VERIFIED_COMPLETE") -> None:
        self.connection.execute("INSERT INTO tile_checkpoint(tile_id,identity_hash,status,payload_json,completed_at) VALUES(?,?,?,?,?) ON CONFLICT(tile_id) DO UPDATE SET identity_hash=excluded.identity_hash,status=excluded.status,payload_json=excluded.payload_json,completed_at=excluded.completed_at", (tile_id, canonical_hash(identity), status, json.dumps(payload, sort_keys=True), datetime.now(timezone.utc).isoformat()))
        self.connection.commit()
