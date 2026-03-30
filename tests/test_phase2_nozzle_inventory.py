from octoprint_nozzlelifetracker.phase1_pure import accumulate_nozzle_seconds
from octoprint_nozzlelifetracker.phase1_settings import (
    RETIRE_ASSIGNED_NOZZLE_MESSAGE,
    build_status_payload,
    ensure_phase2_settings,
    generate_nozzle_id,
    known_tool_ids,
    resolve_effective_life_seconds,
    validate_add_nozzle_payload,
    validate_assign_nozzle_allowed,
    validate_create_nozzle_payload,
    validate_existing_nozzle_id,
    validate_existing_profile_id,
    validate_known_tool_id,
    validate_metadata_field,
    validate_retire_nozzle_allowed,
    validate_unique_nozzle_assignments,
)


def test_phase2_migration_is_idempotent_and_creates_legacy_nozzles():
    profiles = {
        "default_0_4_brass": {
            "id": "default_0_4_brass",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
        }
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_0_4_brass", "accumulated_seconds": 12},
        "T1": {"tool_id": "T1", "profile_id": "default_0_4_brass", "accumulated_seconds": 4},
    }

    first = ensure_phase2_settings(profiles, tool_state, [], None, None)
    second = ensure_phase2_settings(first[0], first[1], first[2], first[3], first[4])

    _, first_tool_state, _, first_nozzles, first_tool_map, first_errors = first
    _, second_tool_state, _, second_nozzles, second_tool_map, second_errors = second

    assert "nozzle_T0_legacy" in first_nozzles
    assert "nozzle_T1_legacy" in first_nozzles
    assert first_nozzles["nozzle_T0_legacy"]["accumulated_seconds"] == 12
    assert first_tool_map["T0"]["active_nozzle_id"] == "nozzle_T0_legacy"
    assert first_errors == {}

    assert second_nozzles == first_nozzles
    assert second_tool_map == first_tool_map
    assert second_tool_state == first_tool_state
    assert second_errors == {}


def test_validate_unique_nozzle_assignments_rejects_dupe_usage():
    conflicts = validate_unique_nozzle_assignments(
        {
            "T0": {"active_nozzle_id": "n_shared"},
            "T1": {"active_nozzle_id": "n_shared"},
        }
    )

    assert conflicts == {"n_shared": ["T0", "T1"]}


def test_tick_accrual_targets_assigned_nozzle_via_tool_map():
    profiles = {
        "default_0_4_brass": {
            "id": "default_0_4_brass",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
        }
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_0_4_brass", "accumulated_seconds": 7},
    }
    nozzles = {
        "nozzle_T0_legacy": {
            "id": "nozzle_T0_legacy",
            "name": "Legacy T0",
            "profile_id": "default_0_4_brass",
            "material": "brass",
            "size_mm": 0.4,
            "accumulated_seconds": 7,
            "retired": False,
        }
    }
    tool_map = {"T0": {"active_nozzle_id": "nozzle_T0_legacy"}}

    _, _, _, nozzles_fixed, _, _ = ensure_phase2_settings(
        profiles,
        tool_state,
        [],
        nozzles,
        tool_map,
    )
    updated, changed = accumulate_nozzle_seconds(nozzles_fixed, "nozzle_T0_legacy", 5)

    assert changed is True
    assert updated["nozzle_T0_legacy"]["accumulated_seconds"] == 12


def test_effective_life_resolution_override_vs_profile_interval():
    profiles = {
        "p1": {"id": "p1", "name": "P1", "interval_hours": 2.0},
    }
    nozzle_profile_based = {"profile_id": "p1"}
    nozzle_override = {"profile_id": "p1", "life_seconds": 9000}

    assert resolve_effective_life_seconds(nozzle_profile_based, profiles) == 7200
    assert resolve_effective_life_seconds(nozzle_override, profiles) == 9000


def test_metadata_defaults_normalization():
    profiles = {
        "default_0_4_brass": {"id": "default_0_4_brass", "name": "0.4 Brass", "interval_hours": 100.0},
    }
    _, _, _, nozzles, _, _ = ensure_phase2_settings(
        profiles,
        {"T0": {"tool_id": "T0", "profile_id": "default_0_4_brass", "accumulated_seconds": 0}},
        [],
        {
            "n1": {
                "id": "n1",
                "name": "Nozzle 1",
                "profile_id": "default_0_4_brass",
                "material": "brass",
                "size_mm": 0.4,
                "accumulated_seconds": 0,
                "retired": False,
            }
        },
        {"T0": {"active_nozzle_id": "n1"}},
    )

    assert nozzles["n1"]["metadata"] == {}


def test_generate_nozzle_id_is_deterministic_with_collisions():
    existing = {"my-nozzle", "my-nozzle-2", "my-nozzle-3"}
    generated = generate_nozzle_id("My Nozzle", existing)
    assert generated == "my-nozzle-4"


def test_retire_nozzle_blocked_when_assigned():
    allowed, message = validate_retire_nozzle_allowed(
        "n1",
        {"T0": {"active_nozzle_id": "n1"}},
    )

    assert allowed is False
    assert message == RETIRE_ASSIGNED_NOZZLE_MESSAGE


def test_assign_retired_nozzle_is_rejected():
    allowed, message = validate_assign_nozzle_allowed(
        "T0",
        "n1",
        {"n1": {"id": "n1", "retired": True}},
        {"T1": {"active_nozzle_id": "n2"}},
    )

    assert allowed is False
    assert message == "Cannot assign a retired nozzle."


def test_known_tool_ids_and_validation_reject_unknown_tool():
    tool_ids = known_tool_ids(
        {"T0": {"tool_id": "T0"}},
        {"t1": {"active_nozzle_id": "n1"}},
    )
    normalized, error = validate_known_tool_id(
        "T2",
        {"T0": {"tool_id": "T0"}},
        {"t1": {"active_nozzle_id": "n1"}},
    )

    assert tool_ids == ["T0", "T1"]
    assert normalized is None
    assert error == "tool_id not found"


def test_create_nozzle_payload_validation_normalizes_valid_input():
    payload, error = validate_create_nozzle_payload(
        {
            "name": "  New Nozzle  ",
            "profile_id": "p1",
            "material": "  hardened steel  ",
            "size_mm": "0.6",
            "life_seconds": "7200",
            "notes": "Ready",
            "metadata": {"vendor": "Bondtech"},
        },
        {"p1": {"id": "p1", "name": "Profile 1", "interval_hours": 10}},
    )

    assert error is None
    assert payload == {
        "name": "New Nozzle",
        "profile_id": "p1",
        "notes": "Ready",
        "life_seconds": 7200,
        "material": "hardened steel",
        "size_mm": 0.6,
        "metadata": {"vendor": "Bondtech"},
    }


def test_create_nozzle_payload_validation_rejects_bad_metadata_and_numbers():
    payload, error = validate_create_nozzle_payload(
        {
            "name": "Bad Nozzle",
            "profile_id": "p1",
            "size_mm": 0,
            "metadata": {"vendor": 5},
        },
        {"p1": {"id": "p1", "name": "Profile 1", "interval_hours": 10}},
    )

    assert payload is None
    assert error == "size_mm must be a positive number"

    payload, error = validate_create_nozzle_payload(
        {
            "name": "Bad Nozzle",
            "profile_id": "p1",
            "metadata": {"vendor": 5},
        },
        {"p1": {"id": "p1", "name": "Profile 1", "interval_hours": 10}},
    )

    assert payload is None
    assert error == "metadata values must be strings"


def test_existing_object_validation_rejects_missing_profile_and_nozzle():
    profile_id, profile_error = validate_existing_profile_id("missing", {"p1": {"id": "p1"}})
    nozzle_id, nozzle_error = validate_existing_nozzle_id("n2", {"n1": {"id": "n1"}})

    assert profile_id is None
    assert profile_error == "profile_id not found"
    assert nozzle_id is None
    assert nozzle_error == "nozzle_id not found"


def test_add_nozzle_payload_validation_rejects_invalid_input():
    payload, error = validate_add_nozzle_payload({"size": "", "material": "brass"})
    assert payload is None
    assert error == "size is required"

    payload, error = validate_add_nozzle_payload({"size": True, "material": "brass"})
    assert payload is None
    assert error == "size must be a positive number"


def test_metadata_field_validation_rejects_non_object():
    metadata, error = validate_metadata_field("vendor=bondtech")

    assert metadata is None
    assert error == "metadata must be an object"


def test_status_payload_includes_retired_flag_for_nozzles():
    payload = build_status_payload(
        {"default_0_4_brass": {"id": "default_0_4_brass", "name": "0.4 Brass", "interval_hours": 100.0}},
        {"T0": {"tool_id": "T0", "profile_id": "default_0_4_brass", "accumulated_seconds": 0}},
        nozzles={
            "n1": {
                "id": "n1",
                "name": "Retired",
                "profile_id": "default_0_4_brass",
                "material": "brass",
                "size_mm": 0.4,
                "accumulated_seconds": 0,
                "retired": True,
            }
        },
        tool_map={"T0": {"active_nozzle_id": "n1"}},
    )

    nozzles_by_id = {entry["id"]: entry for entry in payload["nozzles"]}
    assert nozzles_by_id["n1"]["retired"] is True
