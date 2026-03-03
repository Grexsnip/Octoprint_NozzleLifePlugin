# Immediate Actions
- Finalize Phase 2 architecture plan to transition from tool-based runtime tracking to a nozzle inventory model.
- Define the `nozzle_id` tracking model and confirm migration expectations from current tool runtime state.
- Specify tool-to-nozzle assignment and nozzle swap behavior so lifetime is preserved across swaps.
- Confirm Phase 2 test/governance guardrails for implementation: unit-testable logic, no OctoPrint imports in tests, deterministic minimal changes, and mandatory `python -m pytest -q`.

# Upcoming Tasks
- Implement `nozzle_id`-based runtime tracking flow.
- Add nozzle inventory persistence in plugin settings.
- Support multiple tools with explicit tool -> nozzle assignment.
- Expose current nozzle on the Dashboard.

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
