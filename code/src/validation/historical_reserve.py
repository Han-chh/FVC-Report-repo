from __future__ import annotations


def domains(rows):
    return rows[rows.spatial_role == "development"], rows[rows.spatial_role == "reserve"]


def final_refit_rows(rows):
    return rows[rows.spatial_role.isin(["development", "reserve"])]

