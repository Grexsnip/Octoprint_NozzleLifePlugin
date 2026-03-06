import copy
import json
import os
import tempfile


RUNTIME_STATE_FILENAME = "runtime_state.json"


def default_runtime_state():
    return {
        "tool_state": {},
        "replacement_log": [],
        "nozzle_runtime": {},
    }


def normalize_runtime_state(runtime_state):
    state_in = runtime_state if isinstance(runtime_state, dict) else {}
    tool_state_in = state_in.get("tool_state") if isinstance(state_in.get("tool_state"), dict) else {}
    replacement_log_in = state_in.get("replacement_log") if isinstance(state_in.get("replacement_log"), list) else []
    nozzle_runtime_in = state_in.get("nozzle_runtime") if isinstance(state_in.get("nozzle_runtime"), dict) else {}

    normalized_tool_state = {}
    for tool_id, entry in tool_state_in.items():
        if not isinstance(entry, dict):
            continue
        normalized_tool_state[str(tool_id)] = copy.deepcopy(entry)

    normalized_replacement_log = []
    for entry in replacement_log_in:
        if isinstance(entry, dict):
            normalized_replacement_log.append(copy.deepcopy(entry))

    normalized_nozzle_runtime = {}
    for nozzle_id, entry in nozzle_runtime_in.items():
        if not isinstance(entry, dict):
            continue
        try:
            accumulated_seconds = int(float(entry.get("accumulated_seconds", 0)))
        except (TypeError, ValueError):
            accumulated_seconds = 0
        if accumulated_seconds < 0:
            accumulated_seconds = 0
        normalized_nozzle_runtime[str(nozzle_id)] = {
            "accumulated_seconds": accumulated_seconds,
        }

    return {
        "tool_state": normalized_tool_state,
        "replacement_log": normalized_replacement_log,
        "nozzle_runtime": normalized_nozzle_runtime,
    }


def build_runtime_state(tool_state, replacement_log, nozzles):
    nozzle_runtime = {}
    nozzles_in = nozzles if isinstance(nozzles, dict) else {}
    for nozzle_id, nozzle in nozzles_in.items():
        if not isinstance(nozzle, dict):
            continue
        try:
            accumulated_seconds = int(float(nozzle.get("accumulated_seconds", 0)))
        except (TypeError, ValueError):
            accumulated_seconds = 0
        if accumulated_seconds < 0:
            accumulated_seconds = 0
        nozzle_runtime[str(nozzle_id)] = {
            "accumulated_seconds": accumulated_seconds,
        }

    return normalize_runtime_state(
        {
            "tool_state": copy.deepcopy(tool_state if isinstance(tool_state, dict) else {}),
            "replacement_log": copy.deepcopy(replacement_log if isinstance(replacement_log, list) else []),
            "nozzle_runtime": nozzle_runtime,
        }
    )


def has_legacy_runtime_state(tool_state, replacement_log, nozzles):
    if isinstance(replacement_log, list) and len(replacement_log) > 0:
        return True

    tool_state_in = tool_state if isinstance(tool_state, dict) else {}
    for entry in tool_state_in.values():
        if not isinstance(entry, dict):
            continue
        try:
            accumulated_seconds = int(float(entry.get("accumulated_seconds", 0)))
        except (TypeError, ValueError):
            accumulated_seconds = 0
        if accumulated_seconds > 0:
            return True

    nozzles_in = nozzles if isinstance(nozzles, dict) else {}
    for nozzle in nozzles_in.values():
        if not isinstance(nozzle, dict):
            continue
        try:
            accumulated_seconds = int(float(nozzle.get("accumulated_seconds", 0)))
        except (TypeError, ValueError):
            accumulated_seconds = 0
        if accumulated_seconds > 0:
            return True

    return False


def strip_runtime_state_from_settings(tool_state, replacement_log, nozzles):
    tool_state_in = tool_state if isinstance(tool_state, dict) else {}
    nozzles_in = nozzles if isinstance(nozzles, dict) else {}

    sanitized_tool_state = {}
    for tool_id, entry in tool_state_in.items():
        if not isinstance(entry, dict):
            continue
        sanitized_tool_state[str(tool_id)] = {
            "tool_id": str(entry.get("tool_id") or tool_id),
            "profile_id": str(entry.get("profile_id") or ""),
            "accumulated_seconds": 0,
        }

    sanitized_nozzles = {}
    for nozzle_id, entry in nozzles_in.items():
        if not isinstance(entry, dict):
            continue
        sanitized_entry = copy.deepcopy(entry)
        sanitized_entry["accumulated_seconds"] = 0
        sanitized_nozzles[str(nozzle_id)] = sanitized_entry

    return sanitized_tool_state, [], sanitized_nozzles


def apply_runtime_state_to_nozzles(nozzles, runtime_state):
    nozzles_in = copy.deepcopy(nozzles if isinstance(nozzles, dict) else {})
    normalized_runtime = normalize_runtime_state(runtime_state)
    nozzle_runtime = normalized_runtime["nozzle_runtime"]
    for nozzle_id, nozzle in nozzles_in.items():
        if not isinstance(nozzle, dict):
            continue
        nozzle_runtime_entry = nozzle_runtime.get(str(nozzle_id)) or {}
        nozzle["accumulated_seconds"] = int(nozzle_runtime_entry.get("accumulated_seconds", 0))
    return nozzles_in


def load_runtime_state_file(path):
    if not path or not os.path.exists(path):
        return default_runtime_state(), "missing"

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError, TypeError):
        return default_runtime_state(), "malformed"

    return normalize_runtime_state(raw), "loaded"


def _fsync_directory(directory_path):
    try:
        directory_fd = os.open(directory_path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def save_runtime_state_file(path, runtime_state):
    normalized = normalize_runtime_state(runtime_state)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=os.path.basename(path) + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(normalized, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        _fsync_directory(directory)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
