from octoprint_nozzlelifetracker.runtime_state import (
    apply_runtime_state_to_nozzles,
    build_runtime_state,
    has_legacy_runtime_state,
    load_runtime_state_file,
    save_runtime_state_file,
    should_snapshot_runtime_state,
    strip_runtime_state_from_settings,
)


def test_load_runtime_state_file_missing_returns_defaults(tmp_path):
    runtime_state, status = load_runtime_state_file(str(tmp_path / "runtime_state.json"))

    assert status == "missing"
    assert runtime_state == {
        "tool_state": {},
        "replacement_log": [],
        "nozzle_runtime": {},
    }


def test_runtime_state_round_trip_save_and_load(tmp_path):
    runtime_path = tmp_path / "runtime_state.json"
    runtime_state = {
        "tool_state": {
            "T0": {
                "tool_id": "T0",
                "profile_id": "default_0_4_brass",
                "accumulated_seconds": 12,
            }
        },
        "replacement_log": [
            {
                "timestamp": "2026-03-06 10:00:00",
                "tool_id": "T0",
                "profile_id": "default_0_4_brass",
                "accumulated_seconds_at_reset": 40,
            }
        ],
        "nozzle_runtime": {
            "nozzle_T0_legacy": {
                "accumulated_seconds": 12,
            }
        },
    }

    save_runtime_state_file(str(runtime_path), runtime_state)
    loaded_state, status = load_runtime_state_file(str(runtime_path))

    assert status == "loaded"
    assert loaded_state == runtime_state


def test_runtime_state_atomic_write_leaves_no_temp_files(tmp_path):
    runtime_path = tmp_path / "runtime_state.json"

    save_runtime_state_file(
        str(runtime_path),
        {
            "tool_state": {},
            "replacement_log": [],
            "nozzle_runtime": {"n1": {"accumulated_seconds": 3}},
        },
    )

    assert runtime_path.exists()
    assert list(tmp_path.glob("runtime_state.json.*.tmp")) == []


def test_legacy_settings_runtime_migration_helpers():
    tool_state = {
        "T0": {
            "tool_id": "T0",
            "profile_id": "default_0_4_brass",
            "accumulated_seconds": 15,
        }
    }
    replacement_log = [
        {
            "timestamp": "2026-03-06 09:00:00",
            "tool_id": "T0",
            "profile_id": "default_0_4_brass",
            "accumulated_seconds_at_reset": 25,
        }
    ]
    nozzles = {
        "nozzle_T0_legacy": {
            "id": "nozzle_T0_legacy",
            "name": "Legacy T0",
            "profile_id": "default_0_4_brass",
            "material": "brass",
            "size_mm": 0.4,
            "accumulated_seconds": 15,
            "retired": False,
        }
    }

    assert has_legacy_runtime_state(tool_state, replacement_log, nozzles) is True

    runtime_state = build_runtime_state(tool_state, replacement_log, nozzles)
    merged_nozzles = apply_runtime_state_to_nozzles({"nozzle_T0_legacy": {"id": "nozzle_T0_legacy"}}, runtime_state)
    sanitized_tool_state, sanitized_replacement_log, sanitized_nozzles = strip_runtime_state_from_settings(
        tool_state,
        replacement_log,
        nozzles,
    )

    assert runtime_state["tool_state"]["T0"]["accumulated_seconds"] == 15
    assert runtime_state["nozzle_runtime"]["nozzle_T0_legacy"]["accumulated_seconds"] == 15
    assert merged_nozzles["nozzle_T0_legacy"]["accumulated_seconds"] == 15
    assert sanitized_tool_state["T0"]["accumulated_seconds"] == 0
    assert sanitized_replacement_log == []
    assert sanitized_nozzles["nozzle_T0_legacy"]["accumulated_seconds"] == 0


def test_should_snapshot_runtime_state_only_when_actively_printing():
    should_snapshot = should_snapshot_runtime_state(
        is_printing=True,
        is_dirty=True,
        last_snapshot_ts=100.0,
        now_ts=160.0,
        interval_seconds=60,
    )

    assert should_snapshot is True


def test_should_snapshot_runtime_state_not_when_idle():
    should_snapshot = should_snapshot_runtime_state(
        is_printing=False,
        is_dirty=True,
        last_snapshot_ts=100.0,
        now_ts=160.0,
        interval_seconds=60,
    )

    assert should_snapshot is False


def test_should_snapshot_runtime_state_respects_interval_boundary():
    before_boundary = should_snapshot_runtime_state(
        is_printing=True,
        is_dirty=True,
        last_snapshot_ts=100.0,
        now_ts=159.0,
        interval_seconds=60,
    )
    at_boundary = should_snapshot_runtime_state(
        is_printing=True,
        is_dirty=True,
        last_snapshot_ts=100.0,
        now_ts=160.0,
        interval_seconds=60,
    )

    assert before_boundary is False
    assert at_boundary is True


def test_should_snapshot_runtime_state_does_not_double_trigger_without_new_interval():
    first_snapshot = should_snapshot_runtime_state(
        is_printing=True,
        is_dirty=True,
        last_snapshot_ts=100.0,
        now_ts=160.0,
        interval_seconds=60,
    )
    second_snapshot = should_snapshot_runtime_state(
        is_printing=True,
        is_dirty=True,
        last_snapshot_ts=160.0,
        now_ts=165.0,
        interval_seconds=60,
    )

    assert first_snapshot is True
    assert second_snapshot is False
