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


def _coerce_positive_float(value, default):
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        coerced = float(default)
    if coerced <= 0:
        return float(default)
    return coerced


def _normalize_profile_entry(profile_key, profile, default_interval_hours):
    profile = profile if isinstance(profile, dict) else {}
    normalized_id = str(profile.get("id") or profile_key)
    try:
        interval_hours = float(profile.get("interval_hours", default_interval_hours))
    except (TypeError, ValueError):
        interval_hours = float(default_interval_hours)
    default_material = str(profile.get("default_material") or "brass")
    return {
        "id": normalized_id,
        "name": str(profile.get("name") or normalized_id),
        "interval_hours": interval_hours,
        "notes": str(profile.get("notes") or ""),
        "default_material": default_material,
    }


def _profiles_equivalent(left_profile, right_profile):
    left = left_profile if isinstance(left_profile, dict) else {}
    right = right_profile if isinstance(right_profile, dict) else {}
    left_name = str(left.get("name") or "").strip().lower()
    right_name = str(right.get("name") or "").strip().lower()
    if left_name != right_name:
        return False
    try:
        left_interval = float(left.get("interval_hours", 0.0))
    except (TypeError, ValueError):
        left_interval = 0.0
    try:
        right_interval = float(right.get("interval_hours", 0.0))
    except (TypeError, ValueError):
        right_interval = 0.0
    return abs(left_interval - right_interval) <= 1e-9


def _legacy_nozzle_id_for_tool(tool_id):
    return "nozzle_{}_legacy".format(str(tool_id).upper())


def _coerce_life_seconds(value):
    try:
        coerced = int(float(value))
    except (TypeError, ValueError):
        return None
    if coerced <= 0:
        return None
    return coerced


def _normalize_nozzle_entry(
    nozzle_id,
    nozzle,
    *,
    profiles,
    default_profile_id,
):
    entry = nozzle if isinstance(nozzle, dict) else {}
    normalized_id = str(entry.get("id") or nozzle_id)
    profile_id = str(entry.get("profile_id") or default_profile_id)
    if profile_id not in profiles:
        profile_id = default_profile_id

    notes_value = entry.get("notes")
    created_at_value = entry.get("created_at")

    normalized = {
        "id": normalized_id,
        "name": str(entry.get("name") or normalized_id),
        "profile_id": profile_id,
        "material": str(entry.get("material") or "brass"),
        "size_mm": _coerce_positive_float(entry.get("size_mm"), 0.4),
        "accumulated_seconds": _coerce_nonnegative_int(entry.get("accumulated_seconds", 0)),
        "retired": bool(entry.get("retired", False)),
    }

    life_seconds = _coerce_life_seconds(entry.get("life_seconds"))
    if life_seconds is not None:
        normalized["life_seconds"] = life_seconds

    if notes_value is not None:
        normalized["notes"] = str(notes_value)
    if created_at_value is not None:
        normalized["created_at"] = created_at_value

    return normalized


def _build_legacy_nozzle(tool_id, tool_entry, default_profile_id):
    profile_id = str((tool_entry or {}).get("profile_id") or default_profile_id)
    return {
        "id": _legacy_nozzle_id_for_tool(tool_id),
        "name": "Legacy {}".format(str(tool_id).upper()),
        "profile_id": profile_id,
        "material": "brass",
        "size_mm": 0.4,
        "accumulated_seconds": _coerce_nonnegative_int((tool_entry or {}).get("accumulated_seconds", 0)),
        "retired": False,
    }


def validate_unique_nozzle_assignments(tool_map):
    tool_map_in = tool_map if isinstance(tool_map, dict) else {}
    nozzle_to_tools = {}
    for raw_tool_id, raw_mapping in tool_map_in.items():
        tool_id = normalize_tool_id(raw_tool_id)
        if tool_id is None:
            continue
        mapping = raw_mapping if isinstance(raw_mapping, dict) else {}
        nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if not nozzle_id:
            continue
        nozzle_to_tools.setdefault(nozzle_id, []).append(tool_id)

    conflicts = {}
    for nozzle_id, tools in nozzle_to_tools.items():
        if len(tools) > 1:
            conflicts[nozzle_id] = sorted(tools)
    return conflicts


def dedupe_profiles(
    nozzle_profiles,
    tool_state,
    *,
    canonical_default_id="default_0_4_brass",
    aliases=None,
):
    aliases_map = {"default_brass_0_4": "default_0_4_brass"}
    if isinstance(aliases, dict):
        aliases_map.update(aliases)

    profiles_fixed = dict(nozzle_profiles or {})
    tool_state_in = tool_state if isinstance(tool_state, dict) else {}
    tool_state_fixed = {}
    changed = False

    for alias_id, target_id in aliases_map.items():
        if target_id != canonical_default_id:
            continue
        if alias_id not in profiles_fixed:
            continue
        alias_profile = profiles_fixed.get(alias_id)
        canonical_profile = profiles_fixed.get(target_id)
        if canonical_profile is None:
            moved_profile = dict(alias_profile or {})
            moved_profile["id"] = target_id
            profiles_fixed[target_id] = moved_profile
            del profiles_fixed[alias_id]
            changed = True
            continue
        if _profiles_equivalent(canonical_profile, alias_profile):
            del profiles_fixed[alias_id]
            changed = True

    for tool_key, raw_entry in tool_state_in.items():
        entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
        profile_id = entry.get("profile_id")
        mapped_profile = aliases_map.get(profile_id, profile_id)
        if mapped_profile != profile_id:
            entry["profile_id"] = mapped_profile
            changed = True
        tool_state_fixed[tool_key] = entry

    return profiles_fixed, tool_state_fixed, changed


def ensure_phase1_settings(
    nozzle_profiles,
    tool_state,
    replacement_log,
    default_profile_id="default_0_4_brass",
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
        "default_material": str(default_profile.get("default_material") or "brass"),
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


def ensure_phase2_settings(
    nozzle_profiles,
    tool_state,
    replacement_log,
    nozzles,
    tool_map,
    *,
    default_profile_id="default_0_4_brass",
    default_profile_name="0.4 Brass",
    default_interval_hours=100.0,
):
    profiles_fixed, tool_state_fixed, replacement_fixed = ensure_phase1_settings(
        nozzle_profiles,
        tool_state,
        replacement_log,
        default_profile_id=default_profile_id,
        default_profile_name=default_profile_name,
        default_interval_hours=default_interval_hours,
    )

    nozzles_in = nozzles if isinstance(nozzles, dict) else {}
    tool_map_in = tool_map if isinstance(tool_map, dict) else {}
    nozzles_fixed = {}
    for raw_nozzle_id, raw_nozzle in nozzles_in.items():
        normalized = _normalize_nozzle_entry(
            raw_nozzle_id,
            raw_nozzle,
            profiles=profiles_fixed,
            default_profile_id=default_profile_id,
        )
        nozzles_fixed[normalized["id"]] = normalized

    tool_map_fixed = {}
    for raw_tool_id, raw_mapping in tool_map_in.items():
        tool_id = normalize_tool_id(raw_tool_id)
        if tool_id is None:
            continue
        mapping = raw_mapping if isinstance(raw_mapping, dict) else {}
        nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if nozzle_id:
            tool_map_fixed[tool_id] = {"active_nozzle_id": nozzle_id}

    for tool_id, tool_entry in tool_state_fixed.items():
        mapping = tool_map_fixed.get(tool_id)
        nozzle_id = str((mapping or {}).get("active_nozzle_id") or "").strip()
        has_valid_assignment = nozzle_id and nozzle_id in nozzles_fixed
        if not has_valid_assignment:
            legacy_id = _legacy_nozzle_id_for_tool(tool_id)
            if legacy_id not in nozzles_fixed:
                nozzles_fixed[legacy_id] = _build_legacy_nozzle(tool_id, tool_entry, default_profile_id)
            tool_map_fixed[tool_id] = {"active_nozzle_id": legacy_id}
            nozzle_id = legacy_id

        assigned = nozzles_fixed.get(nozzle_id) or {}
        profile_id = str(assigned.get("profile_id") or tool_entry.get("profile_id") or default_profile_id)
        if profile_id not in profiles_fixed:
            profile_id = default_profile_id
        tool_state_fixed[tool_id]["profile_id"] = profile_id

    for tool_id, mapping in list(tool_map_fixed.items()):
        nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if not nozzle_id or nozzle_id not in nozzles_fixed:
            legacy_id = _legacy_nozzle_id_for_tool(tool_id)
            if legacy_id not in nozzles_fixed:
                nozzles_fixed[legacy_id] = _build_legacy_nozzle(tool_id, tool_state_fixed.get(tool_id), default_profile_id)
            tool_map_fixed[tool_id] = {"active_nozzle_id": legacy_id}

    for tool_id, mapping in tool_map_fixed.items():
        if tool_id not in tool_state_fixed:
            nozzle_id = str(mapping.get("active_nozzle_id") or "")
            nozzle = nozzles_fixed.get(nozzle_id) or {}
            profile_id = str(nozzle.get("profile_id") or default_profile_id)
            if profile_id not in profiles_fixed:
                profile_id = default_profile_id
            tool_state_fixed[tool_id] = {
                "tool_id": tool_id,
                "profile_id": profile_id,
                "accumulated_seconds": _coerce_nonnegative_int(nozzle.get("accumulated_seconds", 0)),
            }

    conflicts = validate_unique_nozzle_assignments(tool_map_fixed)
    errors = {}
    if conflicts:
        errors["duplicate_nozzle_assignment"] = conflicts

    return profiles_fixed, tool_state_fixed, replacement_fixed, nozzles_fixed, tool_map_fixed, errors


def resolve_effective_life_seconds(nozzle, profiles):
    nozzle_entry = nozzle if isinstance(nozzle, dict) else {}
    life_override = _coerce_life_seconds(nozzle_entry.get("life_seconds"))
    if life_override is not None:
        return life_override

    profiles_in = profiles if isinstance(profiles, dict) else {}
    profile_id = str(nozzle_entry.get("profile_id") or "")
    profile = profiles_in.get(profile_id) if isinstance(profiles_in.get(profile_id), dict) else {}
    try:
        interval_hours = float(profile.get("interval_hours", 0.0) or 0.0)
    except (TypeError, ValueError):
        interval_hours = 0.0
    if interval_hours <= 0:
        return 0
    return int(interval_hours * 3600)


def reset_tool_state(
    tool_state,
    replacement_log,
    tool_id,
    timestamp,
    profile_id=None,
    default_profile_id="default_0_4_brass",
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
    nozzles=None,
    tool_map=None,
    errors=None,
    active_tool_id=None,
    now_ts=None,
):
    (
        profiles_fixed,
        tool_state_fixed,
        _,
        nozzles_fixed,
        tool_map_fixed,
        normalize_errors,
    ) = ensure_phase2_settings(
        nozzle_profiles,
        tool_state,
        [],
        nozzles,
        tool_map,
    )

    error_flags = {}
    if isinstance(normalize_errors, dict):
        error_flags.update(normalize_errors)
    if isinstance(errors, dict):
        error_flags.update(errors)

    profiles_out = []
    for profile in sorted(profiles_fixed.values(), key=lambda p: (str(p.get("name") or ""), str(p.get("id") or ""))):
        notes_value = profile.get("notes") if isinstance(profile, dict) else None
        profiles_out.append(
            {
                "id": str(profile.get("id") or ""),
                "name": str(profile.get("name") or ""),
                "interval_hours": float(profile.get("interval_hours", 0.0) or 0.0),
                "notes": notes_value if notes_value is not None else None,
                "default_material": str(profile.get("default_material") or "brass"),
            }
        )

    nozzles_out = []
    for nozzle_id in sorted(nozzles_fixed.keys()):
        nozzle = nozzles_fixed.get(nozzle_id) or {}
        profile = profiles_fixed.get(str(nozzle.get("profile_id") or "")) or {}
        effective_life_seconds = resolve_effective_life_seconds(nozzle, profiles_fixed)
        accumulated_seconds = _coerce_nonnegative_int(nozzle.get("accumulated_seconds", 0))
        accumulated_hours = round(accumulated_seconds / 3600.0, 2)
        if effective_life_seconds <= 0:
            percent_to_interval = 0.0
            is_overdue = False
        else:
            percent_to_interval = round(min(100.0, (float(accumulated_seconds) / float(effective_life_seconds)) * 100.0), 1)
            is_overdue = accumulated_seconds >= effective_life_seconds

        nozzle_entry = {
            "id": str(nozzle.get("id") or nozzle_id),
            "name": str(nozzle.get("name") or nozzle_id),
            "profile_id": str(nozzle.get("profile_id") or ""),
            "profile_name": str(profile.get("name") or "Unknown"),
            "material": str(nozzle.get("material") or "brass"),
            "size_mm": float(nozzle.get("size_mm") or 0.4),
            "accumulated_seconds": accumulated_seconds,
            "accumulated_hours": accumulated_hours,
            "effective_life_seconds": effective_life_seconds,
            "percent_to_interval": percent_to_interval,
            "is_overdue": bool(is_overdue),
            "retired": bool(nozzle.get("retired", False)),
            "notes": str(nozzle.get("notes") or ""),
            "created_at": nozzle.get("created_at"),
        }
        if "life_seconds" in nozzle:
            nozzle_entry["life_seconds"] = _coerce_nonnegative_int(nozzle.get("life_seconds"))
        nozzles_out.append(nozzle_entry)

    tools_out = []
    for tool_id in sorted(tool_state_fixed.keys(), key=_tool_sort_key):
        tool = tool_state_fixed.get(tool_id) or {}
        mapping = tool_map_fixed.get(tool_id) or {}
        nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        assigned_nozzle = nozzles_fixed.get(nozzle_id) or {}

        if nozzle_id and assigned_nozzle:
            profile_id = str(assigned_nozzle.get("profile_id") or tool.get("profile_id") or "")
            accumulated_seconds = _coerce_nonnegative_int(assigned_nozzle.get("accumulated_seconds", 0))
            runtime_source = "derived_from_assigned_nozzle"
        else:
            profile_id = str(tool.get("profile_id") or "")
            accumulated_seconds = _coerce_nonnegative_int(tool.get("accumulated_seconds", 0))
            runtime_source = "legacy_tool_state"
            if not nozzle_id:
                error_flags.setdefault("missing_tool_assignment", {})[tool_id] = True
            elif nozzle_id not in nozzles_fixed:
                error_flags.setdefault("missing_assigned_nozzle", {})[tool_id] = nozzle_id

        profile = profiles_fixed.get(profile_id) or {}
        interval_hours = float(profile.get("interval_hours", 0.0) or 0.0)
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
                "active_nozzle_id": nozzle_id or None,
                "runtime_source": runtime_source,
            }
        )

    active_tool = normalize_tool_id(active_tool_id) if active_tool_id is not None else None
    active_nozzle_out = None
    if active_tool:
        mapping = tool_map_fixed.get(active_tool) or {}
        active_nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if active_nozzle_id and active_nozzle_id in nozzles_fixed:
            active_nozzle = nozzles_fixed.get(active_nozzle_id) or {}
            profile_id = str(active_nozzle.get("profile_id") or "")
            profile = profiles_fixed.get(profile_id) or {}
            effective_life_seconds = resolve_effective_life_seconds(active_nozzle, profiles_fixed)
            accumulated_seconds = _coerce_nonnegative_int(active_nozzle.get("accumulated_seconds", 0))
            if effective_life_seconds <= 0:
                percent_to_interval = 0.0
                is_overdue = False
            else:
                percent_to_interval = round(min(100.0, (float(accumulated_seconds) / float(effective_life_seconds)) * 100.0), 1)
                is_overdue = accumulated_seconds >= effective_life_seconds

            active_nozzle_out = {
                "tool_id": active_tool,
                "id": active_nozzle_id,
                "name": str(active_nozzle.get("name") or active_nozzle_id),
                "material": str(active_nozzle.get("material") or "brass"),
                "size_mm": float(active_nozzle.get("size_mm") or 0.4),
                "profile_id": profile_id,
                "profile_name": str(profile.get("name") or "Unknown"),
                "accumulated_seconds": accumulated_seconds,
                "accumulated_hours": round(accumulated_seconds / 3600.0, 2),
                "effective_life_seconds": effective_life_seconds,
                "percent_to_interval": percent_to_interval,
                "is_overdue": bool(is_overdue),
            }

    return {
        "profiles": profiles_out,
        "tools": tools_out,
        "nozzles": nozzles_out,
        "tool_map": tool_map_fixed,
        "meta": {
            "generated_at": now_ts,
            "error_flags": error_flags,
            "active_tool_id": active_tool,
            "active_nozzle": active_nozzle_out,
        },
    }
