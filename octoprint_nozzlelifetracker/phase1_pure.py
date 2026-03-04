import re


DEFAULT_PROFILE_ID = "default_0_4_brass"
TOOL_CHANGE_CMD_RE = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$", re.IGNORECASE)


def compute_elapsed_seconds(last_tick_ts, now_ts):
    if last_tick_ts is None or now_ts is None:
        return 0
    try:
        delta = float(now_ts) - float(last_tick_ts)
    except (TypeError, ValueError):
        return 0
    if delta <= 0:
        return 0
    return int(delta)


def accumulate_tool_seconds(tool_state, tool_id, delta_seconds, default_profile_id=DEFAULT_PROFILE_ID):
    if not tool_id:
        return tool_state or {}, False

    try:
        delta_seconds = int(delta_seconds)
    except (TypeError, ValueError):
        return tool_state or {}, False

    if delta_seconds <= 0:
        return dict(tool_state or {}), False

    updated = dict(tool_state or {})
    normalized_tool_id = str(tool_id).upper()
    entry = dict(updated.get(normalized_tool_id) or {})
    entry["tool_id"] = normalized_tool_id
    entry["profile_id"] = entry.get("profile_id") or default_profile_id
    try:
        current_seconds = int(float(entry.get("accumulated_seconds", 0)))
    except (TypeError, ValueError):
        current_seconds = 0
    entry["accumulated_seconds"] = max(0, current_seconds) + delta_seconds
    updated[normalized_tool_id] = entry
    return updated, True


def accumulate_nozzle_seconds(nozzles, nozzle_id, delta_seconds, default_profile_id=DEFAULT_PROFILE_ID):
    if not nozzle_id:
        return nozzles or {}, False

    try:
        delta_seconds = int(delta_seconds)
    except (TypeError, ValueError):
        return nozzles or {}, False

    if delta_seconds <= 0:
        return dict(nozzles or {}), False

    updated = dict(nozzles or {})
    normalized_nozzle_id = str(nozzle_id).strip()
    entry = dict(updated.get(normalized_nozzle_id) or {})
    entry["id"] = str(entry.get("id") or normalized_nozzle_id)
    entry["name"] = str(entry.get("name") or normalized_nozzle_id)
    entry["profile_id"] = str(entry.get("profile_id") or default_profile_id)
    entry["material"] = str(entry.get("material") or "brass")
    try:
        size_mm = float(entry.get("size_mm", 0.4))
    except (TypeError, ValueError):
        size_mm = 0.4
    if size_mm <= 0:
        size_mm = 0.4
    entry["size_mm"] = size_mm
    entry["retired"] = bool(entry.get("retired", False))
    try:
        current_seconds = int(float(entry.get("accumulated_seconds", 0)))
    except (TypeError, ValueError):
        current_seconds = 0
    entry["accumulated_seconds"] = max(0, current_seconds) + delta_seconds
    updated[normalized_nozzle_id] = entry
    return updated, True


def extract_tool_id_from_command(cmd):
    if not cmd:
        return None
    match = TOOL_CHANGE_CMD_RE.match(str(cmd))
    if not match:
        return None
    return "T{}".format(match.group(1))
