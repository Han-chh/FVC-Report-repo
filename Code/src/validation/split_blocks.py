from __future__ import annotations

from common.blocks import reserve_blocks


def split_complete_blocks(block_ids, seed=42, reserve_fraction=0.20):
    all_blocks = set(block_ids); reserve = reserve_blocks(all_blocks, seed=seed, fraction=reserve_fraction)
    return {"development": all_blocks - reserve, "reserve": reserve}


def assert_development_only(rows, reserve):
    observed = set(rows["block_id"] if hasattr(rows, "__getitem__") else rows)
    overlap = observed & set(reserve)
    if overlap: raise ValueError(f"RESERVE_LEAKAGE:{sorted(overlap)}")

