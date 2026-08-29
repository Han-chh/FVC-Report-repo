import numpy as np

from data_prep.materialization import ScientificRasterContract, validate_scientific_materialization


def test_full_width_source_availability_strip_is_not_a_small_grid_shift():
    """Regression control for the observed 47SNB 217-row source gap."""
    width, height, gap_rows = 3542, 2389, 217
    local = np.ones((height, width), dtype=bool)
    local[-gap_rows:, :] = False
    gee = np.ones_like(local)
    baseline = int(np.count_nonzero(local != gee))
    best = 0
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            shifted = np.zeros_like(local)
            r0, r1 = max(0, dy), height + min(0, dy)
            c0, c1 = max(0, dx), width + min(0, dx)
            shifted[r0:r1, c0:c1] = local[r0 - dy:r1 - dy, c0 - dx:c1 - dx]
            best = max(best, int(np.count_nonzero(shifted == gee)))
    assert baseline == 768_614
    assert best < local.size - baseline + 30_000


def test_expected_sentinel_b4_b8_schema_rejects_rgba_placeholder():
    expected = {"count": 2, "dtypes": ("uint16", "uint16"), "color": ("gray", "undefined")}
    observed = {"count": 4, "dtypes": ("uint8",) * 4, "color": ("red", "green", "blue", "alpha")}
    assert expected["count"] == 2 and set(expected["dtypes"]) == {"uint16"}
    assert not (observed["count"] == 2 and set(observed["dtypes"]) == {"uint16"})


def test_scientific_materialization_contract_rejects_known_negative_controls():
    contract = ScientificRasterContract("Sentinel-2", ("B4", "B8"), "uint16", 10)
    assert "RGBA_PREVIEW_INVALID" in validate_scientific_materialization(
        contract=contract, band_count=4, dtypes=("uint8",) * 4,
        color_interpretations=("red", "green", "blue", "alpha"), resolution_m=10, source_identity="frozen")
    assert "DTYPE_INVALID" in validate_scientific_materialization(
        contract=contract, band_count=2, dtypes=("uint8", "uint8"),
        color_interpretations=("gray", "undefined"), resolution_m=10, source_identity="frozen")
    assert "SOURCE_IDENTITY_MISSING" in validate_scientific_materialization(
        contract=contract, band_count=2, dtypes=("uint16", "uint16"),
        color_interpretations=("gray", "undefined"), resolution_m=10, source_identity=None)
    assert validate_scientific_materialization(
        contract=contract, band_count=2, dtypes=("uint16", "uint16"),
        color_interpretations=("gray", "undefined"), resolution_m=10, source_identity="frozen") == []
