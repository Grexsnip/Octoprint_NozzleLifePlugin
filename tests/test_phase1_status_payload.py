from octoprint_nozzlelifetracker.phase1_settings import (
    build_status_payload,
    ensure_phase1_settings,
)


def test_build_status_payload_basic_structure_from_defaults():
    profiles, tool_state, _ = ensure_phase1_settings(None, None, None)
    payload = build_status_payload(profiles, tool_state, now_ts="2026-02-24T12:00:00Z")

    assert list(payload.keys()) == ["profiles", "tools", "meta"]
    assert isinstance(payload["profiles"], list)
    assert isinstance(payload["tools"], list)
    assert payload["meta"] == {"generated_at": "2026-02-24T12:00:00Z"}

    default_profile = next(p for p in payload["profiles"] if p["id"] == "default_brass_0_4")
    assert set(default_profile.keys()) == {"id", "name", "interval_hours", "notes"}
    assert default_profile["name"] == "0.4 Brass"
    assert isinstance(default_profile["interval_hours"], float)

    t0 = next(t for t in payload["tools"] if t["tool_id"] == "T0")
    assert set(t0.keys()) == {
        "tool_id",
        "profile_id",
        "profile_name",
        "interval_hours",
        "accumulated_seconds",
        "accumulated_hours",
        "percent_to_interval",
        "is_overdue",
    }
    assert t0["profile_id"] == "default_brass_0_4"
    assert t0["accumulated_seconds"] == 0
    assert t0["accumulated_hours"] == 0.0
    assert t0["percent_to_interval"] == 0.0
    assert t0["is_overdue"] is False


def test_build_status_payload_percent_rounding_and_overdue_logic():
    profiles = {
        "p1": {"id": "p1", "name": "Brass", "interval_hours": 100.0, "notes": ""},
        "default_brass_0_4": {"id": "default_brass_0_4", "name": "0.4 Brass", "interval_hours": 100.0, "notes": ""},
    }

    payload = build_status_payload(
        profiles,
        {
            "T0": {"tool_id": "T0", "profile_id": "p1", "accumulated_seconds": 50 * 3600},
            "T1": {"tool_id": "T1", "profile_id": "p1", "accumulated_seconds": 100 * 3600},
            "T2": {"tool_id": "T2", "profile_id": "p1", "accumulated_seconds": 120 * 3600},
        },
    )
    tools = {t["tool_id"]: t for t in payload["tools"]}

    assert tools["T0"]["percent_to_interval"] == 50.0
    assert tools["T0"]["is_overdue"] is False
    assert tools["T1"]["percent_to_interval"] == 100.0
    assert tools["T1"]["is_overdue"] is True
    assert tools["T2"]["percent_to_interval"] == 100.0
    assert tools["T2"]["is_overdue"] is True


def test_build_status_payload_zero_interval_handling():
    payload = build_status_payload(
        {
            "p0": {"id": "p0", "name": "Test", "interval_hours": 0.0, "notes": None},
            "default_brass_0_4": {
                "id": "default_brass_0_4",
                "name": "0.4 Brass",
                "interval_hours": 100.0,
                "notes": "",
            },
        },
        {"T0": {"tool_id": "T0", "profile_id": "p0", "accumulated_seconds": 9999}},
    )
    t0 = next(t for t in payload["tools"] if t["tool_id"] == "T0")
    assert t0["interval_hours"] == 0.0
    assert t0["percent_to_interval"] == 0.0
    assert t0["is_overdue"] is False


def test_build_status_payload_tool_sorting_by_numeric_index():
    payload = build_status_payload(
        {
            "default_brass_0_4": {
                "id": "default_brass_0_4",
                "name": "0.4 Brass",
                "interval_hours": 100.0,
                "notes": "",
            }
        },
        {
            "T2": {"tool_id": "T2", "profile_id": "default_brass_0_4", "accumulated_seconds": 0},
            "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 0},
            "T10": {"tool_id": "T10", "profile_id": "default_brass_0_4", "accumulated_seconds": 0},
            "T1": {"tool_id": "T1", "profile_id": "default_brass_0_4", "accumulated_seconds": 0},
        },
    )

    assert [t["tool_id"] for t in payload["tools"]] == ["T0", "T1", "T2", "T10"]


def test_build_status_payload_profiles_sorted_by_name():
    payload = build_status_payload(
        {
            "p_b": {"id": "p_b", "name": "B", "interval_hours": 10.0},
            "p_a": {"id": "p_a", "name": "A", "interval_hours": 10.0},
            "p_c": {"id": "p_c", "name": "C", "interval_hours": 10.0},
        },
        {"T0": {"tool_id": "T0", "profile_id": "p_a", "accumulated_seconds": 0}},
    )

    # Includes the ensured default profile; verify our chosen ordering rule (name asc).
    names = [p["name"] for p in payload["profiles"]]
    assert names == sorted(names)
