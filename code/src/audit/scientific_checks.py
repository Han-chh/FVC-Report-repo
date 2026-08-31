def require_all_ready(status_frame):
    not_ready = status_frame[status_frame.status != "READY"]
    if len(not_ready): raise RuntimeError(f"DATA_NOT_READY:{len(not_ready)} rows")
    return True

