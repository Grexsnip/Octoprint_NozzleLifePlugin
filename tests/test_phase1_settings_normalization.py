from octoprint_nozzlelifetracker.phase1_settings import (
    ensure_phase1_settings,
    normalize_tool_id,
)


def test_ensure_phase1_settings_creates_defaults_for_invalid_inputs():
    profiles, tool_state, replacement_log = ensure_phase1_settings(None, None, None)

    assert "default_brass_0_4" in profiles
    assert profiles["default_brass_0_4"]["name"] == "0.4 Brass"
    assert profiles["default_brass_0_4"]["interval_hours"] == 100.0
    assert "T0" in tool_state
    assert tool_state["T0"]["profile_id"] == "default_brass_0_4"
    assert tool_state["T0"]["accumulated_seconds"] == 0
    assert replacement_log == []


def test_ensure_phase1_settings_repairs_bad_tool_entries():
    profiles, tool_state, _ = ensure_phase1_settings(
        {"p1": {"id": "p1", "name": "Hardened", "interval_hours": 250}},
        {
            "t0": {"profile_id": "missing", "accumulated_seconds": -5},
            "T1": {"accumulated_seconds": "12.7"},
            "T2": {"profile_id": "unknown_profile", "accumulated_seconds": "3"},
        },
        [],
        default_profile_id="p_default",
        default_profile_name="Default",
        default_interval_hours=100.0,
    )

    assert "p_default" in profiles
    assert tool_state["T0"]["profile_id"] == "p_default"
    assert tool_state["T0"]["accumulated_seconds"] == 0
    assert tool_state["T1"]["profile_id"] == "p_default"
    assert tool_state["T1"]["accumulated_seconds"] == 12
    assert tool_state["T2"]["profile_id"] == "p_default"
    assert tool_state["T2"]["accumulated_seconds"] == 3


def test_ensure_phase1_settings_preserves_valid_data():
    input_profiles = {
        "p1": {"id": "p1", "name": "0.6 Hardened", "interval_hours": 300.0, "notes": "Primary"},
        "default_brass_0_4": {
            "id": "default_brass_0_4",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        },
    }
    input_tool_state = {
        "T1": {"tool_id": "T1", "profile_id": "p1", "accumulated_seconds": 42},
        "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 5},
    }
    input_log = [
        {
            "timestamp": "2026-02-24 10:00:00",
            "tool_id": "T1",
            "profile_id": "p1",
            "accumulated_seconds_at_reset": 99,
        }
    ]

    profiles, tool_state, replacement_log = ensure_phase1_settings(
        input_profiles,
        input_tool_state,
        input_log,
    )

    assert profiles["p1"]["name"] == "0.6 Hardened"
    assert profiles["p1"]["interval_hours"] == 300.0
    assert tool_state["T1"]["profile_id"] == "p1"
    assert tool_state["T1"]["accumulated_seconds"] == 42
    assert replacement_log == input_log


def test_normalize_tool_id():
    assert normalize_tool_id("t0") == "T0"
    assert normalize_tool_id(" T2 ") == "T2"
    assert normalize_tool_id("") is None
    assert normalize_tool_id(None) is None
    assert normalize_tool_id("X0") is None
    assert normalize_tool_id("T") is None

