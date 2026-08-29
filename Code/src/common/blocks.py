from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable


def block_id(x_m: float, y_m: float, *, origin=(525000.0, 4195000.0), size_m=5000.0) -> str:
    col = math.floor((x_m - origin[0]) / size_m)
    row = math.floor((y_m - origin[1]) / size_m)
    return f"b_{col}_{row}"


def reserve_blocks(blocks: Iterable[str], *, seed: int = 42, fraction: float = 0.20) -> set[str]:
    unique = sorted(set(blocks))
    count = int(round(len(unique) * fraction))
    ranked = sorted(unique, key=lambda value: hashlib.sha256(f"{seed}-{value}".encode()).hexdigest())
    return set(ranked[:count])

