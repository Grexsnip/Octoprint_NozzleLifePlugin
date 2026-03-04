# Immediate Actions

# Upcoming Tasks

# Future Tasks
- Implement profile CRUD after the inventory model is stable.

# Completed
## 2026-03-03
- Implemented Phase 1 time-based runtime tracking cadence (5s tick / 60s persist).
- Separated pure function logic from plugin module for unit testing.
- Added and maintained pytest harness (`python -m pytest -q`).
- Added settings normalization and profile deduplication safeguards.
- Enforced version synchronization across `setup.py`, `plugin.yaml`, and `__init__.py`.
- Fixed template injection by correcting `.jinja2` template paths in `get_template_configs`.
- Removed duplicate OctoPrint wrapper container divs from sidebar/settings templates.
- Confirmed Sidebar + Settings Knockout bindings are wired and rendering.
- Added overdue visual indicator (row styling + badge) in Sidebar and Settings.
- Prevented committing `__pycache__` artifacts.
- Applied strict patch version bump discipline for release increments.
- Finalized Phase 2 architecture plan for transition from tool-based runtime to nozzle inventory (`nozzle_id`) model.
- Defined `nozzle_id` model details with migration expectations from existing tool runtime state.
- Specified tool-to-nozzle assignment and swap behavior to preserve lifetime across swaps.
- Confirmed Phase 2 guardrails: unit-testable logic, no OctoPrint imports in tests, deterministic minimal changes, and mandatory `python -m pytest -q`.
- Implemented `nozzle_id`-based runtime tracking flow with additive migration/backward compatibility.
- Added nozzle inventory persistence in plugin settings (`nozzles` + `tool_map`) with normalization/auto-heal.
- Added support for explicit tool -> nozzle assignment with uniqueness validation.
- Exposed active tool/nozzle status in UI via minimal dashboard element.
