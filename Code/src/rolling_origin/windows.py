from __future__ import annotations

from validation.leakage_audit import assert_chronology

PRIMARY = (
    (2024, (2023,)), (2024, (2022, 2023)), (2024, (2021, 2022, 2023)),
    (2025, (2024,)), (2025, (2023, 2024)), (2025, (2022, 2023, 2024)),
)


def primary_windows():
    rows = []
    for target, history in PRIMARY:
        assert_chronology(history, target)
        rows.append({"target_year": target, "history_years": history, "history_length": len(history),
                     "target_role": "retrospective" if target == 2024 else "primary_independent_future_year",
                     "loyo": "NOT_APPLICABLE" if len(history) == 1 else "PLANNED"})
    return rows

