def normalize_tool_id(tool_id):
    if tool_id is None:
        return None
    value = str(tool_id).strip().upper()
    if len(value) < 2 or not value.startswith("T"):
        return None
    suffix = value[1:]
    if not suffix.isdigit():
        return None
    return "T{}".format(int(suffix))


def _coerce_nonnegative_int(value):
    try:
        coerced = int(float(value))
    except (TypeError, ValueError):
        return 0
    if coerced < 0:
        return 0
    return coerced


def _normalize_profile_entry(profile_key, profile, default_interval_hours):
    profile = profile if isinstance(profile, dict) else {}
    normalized_id = str(profile.get("id") or profile_key)
    try:
        interval_hours = float(profile.get("interval_hours", default_interval_hours))
    except (TypeError, ValueError):
        interval_hours = float(default_interval_hours)
    return {
        "id": normalized_id,
        "name": str(profile.get("name") or normalized_id),
        "interval_hours": interval_hours,
        "notes": str(profile.get("notes") or ""),
    }


def ensure_phase1_settings(
    nozzle_profiles,
    tool_state,
    replacement_log,
    default_profile_id="default_brass_0_4",
    default_profile_name="0.4 Brass",
    default_interval_hours=100.0,
):
    profiles_in = nozzle_profiles if isinstance(nozzle_profiles, dict) else {}
    profiles_fixed = {}
    for profile_key, profile in profiles_in.items():
        normalized = _normalize_profile_entry(profile_key, profile, default_interval_hours)
        profiles_fixed[normalized["id"]] = normalized

    default_profile = profiles_fixed.get(default_profile_id, {})
    try:
        default_interval = float(default_profile.get("interval_hours", default_interval_hours))
    except (TypeError, ValueError):
        default_interval = float(default_interval_hours)
    profiles_fixed[default_profile_id] = {
        "id": default_profile_id,
        "name": str(default_profile.get("name") or default_profile_name),
        "interval_hours": default_interval,
        "notes": str(default_profile.get("notes") or ""),
    }

    tool_state_in = tool_state if isinstance(tool_state, dict) else {}
    tool_state_fixed = {}
    for raw_tool_key, raw_entry in tool_state_in.items():
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        normalized_tool = normalize_tool_id(entry.get("tool_id") or raw_tool_key)
        if normalized_tool is None:
            continue
        profile_id = entry.get("profile_id") or default_profile_id
        if profile_id not in profiles_fixed:
            profile_id = default_profile_id
        tool_state_fixed[normalized_tool] = {
            "tool_id": normalized_tool,
            "profile_id": profile_id,
            "accumulated_seconds": _coerce_nonnegative_int(entry.get("accumulated_seconds", 0)),
        }

    if "T0" not in tool_state_fixed:
        tool_state_fixed["T0"] = {
            "tool_id": "T0",
            "profile_id": default_profile_id,
            "accumulated_seconds": 0,
        }

    replacement_in = replacement_log if isinstance(replacement_log, list) else []
    replacement_fixed = []
    for raw_entry in replacement_in:
        if not isinstance(raw_entry, dict):
            continue
        normalized_tool = normalize_tool_id(raw_entry.get("tool_id")) or "T0"
        profile_id = str(raw_entry.get("profile_id") or default_profile_id)
        if profile_id not in profiles_fixed:
            profile_id = default_profile_id
        replacement_fixed.append(
            {
                "timestamp": str(raw_entry.get("timestamp") or ""),
                "tool_id": normalized_tool,
                "profile_id": profile_id,
                "accumulated_seconds_at_reset": _coerce_nonnegative_int(
                    raw_entry.get("accumulated_seconds_at_reset", 0)
                ),
            }
        )

    return profiles_fixed, tool_state_fixed, replacement_fixed


def reset_tool_state(
    tool_state,
    replacement_log,
    tool_id,
    timestamp,
    profile_id=None,
    default_profile_id="default_brass_0_4",
):
    normalized_tool = normalize_tool_id(tool_id)
    if normalized_tool is None:
        raise ValueError("tool_id is invalid")

    tool_state_in = dict(tool_state or {})
    replacement_in = list(replacement_log or [])

    existing = tool_state_in.get(normalized_tool)
    if not isinstance(existing, dict):
        existing = {}

    resolved_profile_id = profile_id or existing.get("profile_id") or default_profile_id
    prior_seconds = _coerce_nonnegative_int(existing.get("accumulated_seconds", 0))

    tool_state_in[normalized_tool] = {
        "tool_id": normalized_tool,
        "profile_id": resolved_profile_id,
        "accumulated_seconds": 0,
    }
    replacement_in.append(
        {
            "timestamp": str(timestamp),
            "tool_id": normalized_tool,
            "profile_id": resolved_profile_id,
            "accumulated_seconds_at_reset": prior_seconds,
        }
    )

    return tool_state_in, replacement_in


def _tool_sort_key(tool_id):
    normalized = normalize_tool_id(tool_id)
    if normalized is None:
        return (1, str(tool_id))
    return (0, int(normalized[1:]), normalized)


def build_status_payload(
    nozzle_profiles,
    tool_state,
    *,
    now_ts=None,
):
    profiles_fixed, tool_state_fixed, _ = ensure_phase1_settings(
        nozzle_profiles,
        tool_state,
        [],
    )

    profiles_out = []
    for profile in sorted(profiles_fixed.values(), key=lambda p: (str(p.get("name") or ""), str(p.get("id") or ""))):
        notes_value = profile.get("notes") if isinstance(profile, dict) else None
        profiles_out.append(
            {
                "id": str(profile.get("id") or ""),
                "name": str(profile.get("name") or ""),
                "interval_hours": float(profile.get("interval_hours", 0.0) or 0.0),
                "notes": notes_value if notes_value is not None else None,
            }
        )

    tools_out = []
    for tool_id in sorted(tool_state_fixed.keys(), key=_tool_sort_key):
        tool = tool_state_fixed.get(tool_id) or {}
        profile_id = str(tool.get("profile_id") or "")
        profile = profiles_fixed.get(profile_id) or {}
        interval_hours = float(profile.get("interval_hours", 0.0) or 0.0)
        accumulated_seconds = _coerce_nonnegative_int(tool.get("accumulated_seconds", 0))
        accumulated_hours = round(accumulated_seconds / 3600.0, 2)
        if interval_hours <= 0:
            percent_to_interval = 0.0
            is_overdue = False
        else:
            percent_to_interval = round(min(100.0, (accumulated_hours / interval_hours) * 100.0), 1)
            is_overdue = accumulated_hours >= interval_hours

        tools_out.append(
            {
                "tool_id": str(tool.get("tool_id") or tool_id),
                "profile_id": profile_id,
                "profile_name": str(profile.get("name") or "Unknown"),
                "interval_hours": interval_hours,
                "accumulated_seconds": accumulated_seconds,
                "accumulated_hours": accumulated_hours,
                "percent_to_interval": percent_to_interval,
                "is_overdue": bool(is_overdue),
            }
        )

    return {
        "profiles": profiles_out,
        "tools": tools_out,
        "meta": {
            "generated_at": now_ts,
        },
    }
