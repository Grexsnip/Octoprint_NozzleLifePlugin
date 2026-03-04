# Phase 2 Nozzle Inventory Spec

## Goals
- Move runtime accumulation target from tool-level state to `nozzle_id` while preserving the existing time-based tracking model.
- Keep current print lifecycle behavior and cadence unchanged (5s tick, 60s persistence).
- Keep migration backward compatible and idempotent.

## Non-goals
- Extrusion-length tracking.
- Profile CRUD workflows.
- Replacement history workflows.

## Settings Schema (Additive)
Phase 1 keys remain in place for migration and backward compatibility.

### `nozzles`
Dictionary keyed by `nozzle_id`.

Required nozzle fields:
- `id` (string, must equal dict key)
- `name` (string)
- `profile_id` (string)
- `material` (string, default `"brass"`)
- `size_mm` (number, default `0.4`)
- `accumulated_seconds` (int)
- `retired` (bool, default `false`)

Optional nozzle fields:
- `life_seconds` (int override)
- `notes` (string)
- `created_at` (timestamp string or int)

### `tool_map`
Dictionary keyed by tool id (example: `"T0"`) with value:
- `active_nozzle_id` (string)

### `profiles`
- Keep existing Phase 1 structure; `interval_hours` remains canonical default life basis.
- Optional additive field: `profiles[profile_id].default_material` (string, default `"brass"`).

## Effective Life Resolution
Deterministic rule:

`effective_life_seconds = nozzle.life_seconds ?? (profiles[nozzle.profile_id].interval_hours * 3600)`

## Invariants and Guardrails
- Every tool must always have exactly one assigned active nozzle in steady state.
- API/UI must not allow unassign; assignment cannot be null or empty.
- Normalization/migration must auto-heal missing assignment by creating and assigning a legacy nozzle.
- Default uniqueness rule: a `nozzle_id` cannot be assigned to more than one tool at once.
- Conflict handling for uniqueness is deterministic rejection by normalization/API validation until an explicit reassignment is provided.

## Tick Accounting Rules (Spec Only)
- Active tool determination remains exactly the same as Phase 1.
- During printing, each 5s tick accrues runtime to the active nozzle assigned to the active tool.
- Persistence cadence remains unchanged: every 60s and on pause/stop transitions.
- If corrupt state yields missing nozzle assignment, tick accrues nothing and status must expose an explicit error flag.

## Migration Plan (Idempotent, Backward Compatible)
- If `nozzles` or `tool_map` is absent, create one legacy nozzle per tool with existing runtime.
- Stable legacy nozzle id format: `nozzle_<tool_id>_legacy` (example: `nozzle_T0_legacy`).
- For each created legacy nozzle:
  - `accumulated_seconds` copied from Phase 1 `tool_state[tool_id].accumulated_seconds`
  - `profile_id` copied from Phase 1 `tool_state[tool_id].profile_id`
  - `material = "brass"`
  - `size_mm = 0.4`
- Set `tool_map[tool_id].active_nozzle_id` to the created legacy nozzle id.
- Preserve Phase 1 `tool_state` accumulated fields for legacy/backward compatibility during transition.

## API Payload Evolution (Spec Only)
- Keep existing top-level keys: `meta`, `profiles`, `tools`.
- Add top-level keys: `nozzles`, `tool_map`.
- `tools` runtime remains available for Phase 1 clients; document whether each runtime field is legacy-stored or derived from assigned nozzle state.

## Minimal UI Impact (Spec Only)
- Sidebar should display active nozzle information (name and overdue status) and enforce no-unassigned state.
- Settings should add inventory list and create-nozzle workflow in Phase 2 implementation.
