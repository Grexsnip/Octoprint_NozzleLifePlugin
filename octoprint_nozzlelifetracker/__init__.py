# NozzleLifeTracker Plugin - OctoPrint Plugin Scaffold

try:
    from octoprint.plugin import (
        StartupPlugin,
        ShutdownPlugin,
        SettingsPlugin,
        AssetPlugin,
        TemplatePlugin,
        EventHandlerPlugin,
        SimpleApiPlugin
    )
except ImportError:
    class StartupPlugin(object):
        pass

    class ShutdownPlugin(object):
        pass

    class SettingsPlugin(object):
        pass

    class AssetPlugin(object):
        pass

    class TemplatePlugin(object):
        pass

    class EventHandlerPlugin(object):
        pass

    class SimpleApiPlugin(object):
        pass
import os
import time
import threading
try:
    from flask import make_response, request, jsonify
except ImportError:
    request = None

    def make_response(*args, **kwargs):
        raise RuntimeError("Flask is required for response generation")

    def jsonify(*args, **kwargs):
        raise RuntimeError("Flask is required for JSON responses")
import csv
from .phase1_pure import (
    compute_elapsed_seconds,
    accumulate_tool_seconds,
    accumulate_nozzle_seconds,
    extract_tool_id_from_command,
)
from .phase1_settings import (
    ensure_phase2_settings,
    dedupe_profiles,
    reset_tool_state,
    build_status_payload,
    normalize_tool_id,
    validate_unique_nozzle_assignments,
    validate_assign_nozzle_allowed,
    validate_retire_nozzle_allowed,
    generate_nozzle_id,
    RETIRE_ASSIGNED_NOZZLE_MESSAGE,
)
from .runtime_state import (
    RUNTIME_STATE_FILENAME,
    apply_runtime_state_to_nozzles,
    build_runtime_state,
    has_legacy_runtime_state,
    load_runtime_state_file,
    save_runtime_state_file,
    should_snapshot_runtime_state,
    strip_runtime_state_from_settings,
)

__plugin_name__ = "Nozzle Life Tracker"
__plugin_version__ = "0.3.4"
__plugin_pythoncompat__ = ">=3.7,<3.12"
__plugin_octoprint_version__ = ">=1.9,<2"

DEFAULT_PROFILE_ID = "default_0_4_brass"
DEFAULT_PROFILE_NAME = "0.4 Brass"
DEFAULT_PROFILE_INTERVAL_HOURS = 100.0
DEFAULT_TOOL_ID = "T0"
PHASE1_TICK_SECONDS = 5
PHASE1_PERSIST_SECONDS = 60
PHASE1_PERSIST_INTERVAL_SECONDS = PHASE1_PERSIST_SECONDS
PHASE1_PERSIST_CHECK_INTERVAL_SECONDS = PHASE1_TICK_SECONDS

class NozzleLifeTrackerPlugin(StartupPlugin,
                              ShutdownPlugin,
                              SettingsPlugin,
                              AssetPlugin,
                              TemplatePlugin,
                              EventHandlerPlugin,
                              SimpleApiPlugin):

    def __init__(self):
        self._current_nozzle = None
        self._print_start_time = None
        self._lock = threading.Lock()
        self._nozzles = {}
        self._print_log = []
        self._nozzle_profiles = {}
        self._tool_state = {}
        self._tool_map = {}
        self._replacement_log = []
        self._phase2_error_flags = {}
        self._is_printing = False
        self._last_tick_ts = None
        self._active_tool_id = DEFAULT_TOOL_ID
        self._active_tool_source = "fallback"
        self._phase1_runtime_dirty = False
        self._last_phase1_persist_ts = 0
        self._persist_worker = None
        self._persist_worker_stop = threading.Event()

    ##~~ StartupPlugin

    def on_after_startup(self):
        self._logger.info("NozzleLifeTracker plugin started.")
        self._load_nozzles()
        self._ensure_phase1_settings(save=True)
        self._start_phase1_persist_worker()

    def on_shutdown(self):
        worker = getattr(self, "_persist_worker", None)
        stop_event = getattr(self, "_persist_worker_stop", None)

        try:
            if stop_event is not None:
                stop_event.set()
            if worker is not None and worker.is_alive():
                worker.join(timeout=3)
        except Exception:
            self._logger.exception("Error stopping Phase 1 persist worker")

        try:
            with self._lock:
                self._ensure_phase1_settings(save=False)
                was_printing = self._is_printing
                if was_printing:
                    self._phase1_tick_locked(now_ts=time.time(), persist_if_due=False)
                runtime_saved = self._save_phase1_settings(tool_state_only=True)
                if runtime_saved:
                    if was_printing:
                        self._logger.info("Flushed active-print runtime state during shutdown")
                    else:
                        self._logger.debug("Flushed runtime state during shutdown")
                else:
                    self._logger.warning("Runtime-state flush during shutdown did not complete")
        except Exception:
            self._logger.exception("Error flushing runtime state during shutdown")

    ##~~ Assets

    def get_assets(self):
        return {
            "js": ["js/nozzlelifetracker.js"],
            "css": ["css/nozzlelifetracker.css"],
            "less": ["less/nozzlelifetracker.less"],
        }

    ##~~ SettingsPlugin

    def get_settings_defaults(self):
        return {
            "nozzles": {},
            "default_nozzle_id": None,
            "prompt_before_print": False,
            "display_mode": "circle",  # Options: circle, bar, both
            "legacy_runtime_enabled": False,
            "print_log": [],
            "nozzle_profiles": {
                DEFAULT_PROFILE_ID: {
                    "id": DEFAULT_PROFILE_ID,
                    "name": DEFAULT_PROFILE_NAME,
                    "interval_hours": DEFAULT_PROFILE_INTERVAL_HOURS,
                    "notes": ""
                }
            },
            "tool_state": {
                "T0": {
                    "tool_id": "T0",
                    "profile_id": DEFAULT_PROFILE_ID,
                    "accumulated_seconds": 0
                }
            },
            "tool_map": {
                "T0": {
                    "active_nozzle_id": "nozzle_T0_legacy"
                }
            },
            "replacement_log": []
        }

    def on_settings_save(self, data):
        SettingsPlugin.on_settings_save(self, data)
        self._load_nozzles()
        self._ensure_phase1_settings(save=False)

    def get_template_configs(self):
        # Explicit template mapping; forces OctoPrint to inject both panes
        return [
            dict(type="settings",
                 name="Nozzle Life Tracker",
                 template="settings/nozzlelifetracker_settings.jinja2",
                 custom_bindings=True),
            dict(type="sidebar",
                 name="Nozzle Life Tracker",
                 template="sidebar/nozzlelifetracker_sidebar.jinja2",
                 custom_bindings=True),
        ]


    ##~~ EventHandlerPlugin

    def on_event(self, event, payload):
        with self._lock:
            if event == "PrintStarted":
                self._phase1_handle_print_start_or_resume_locked()
                self._print_start_time = time.time()

            elif event == "PrintResumed":
                # Resume timing after a paused print
                self._phase1_handle_print_start_or_resume_locked()
                self._print_start_time = time.time()

            elif event == "PrintPaused":
                # Persist elapsed runtime up to the pause point
                self._phase1_handle_print_pause_or_stop_locked(force_persist=True)
                if self._settings.get(["legacy_runtime_enabled"]):
                    self._accumulate_runtime(payload)
                self._print_start_time = None

            elif event in ["PrintDone", "PrintCancelled", "PrintFailed"]:
                self._phase1_handle_print_pause_or_stop_locked(force_persist=True)
                if self._settings.get(["legacy_runtime_enabled"]):
                    self._accumulate_runtime(payload)
                self._print_start_time = None

    ##~~ SimpleApiPlugin (for frontend interaction)
    def is_api_protected(self):
        return True

    def on_api_get(self, request):
        command = request.values.get("command")
        if command in (None, "status"):
            return jsonify(self.get_api_status())
        if command == "export_log_csv":
            output = make_response(self._generate_csv())
            output.headers["Content-Disposition"] = "attachment; filename=nozzle_log.csv"
            output.headers["Content-type"] = "text/csv"
            return output
        return make_response("Unknown command", 400)

    def get_api_commands(self):
        return {
            "status": [],
            "set_tool_profile": ["tool_id", "profile_id"],
            "reset_tool": ["tool_id"],
            "assign_nozzle": ["tool_id", "nozzle_id"],
            "create_nozzle": ["name", "profile_id"],
            "reset_nozzle": ["nozzle_id"],
            "select_nozzle": ["nozzle_id"],
            "get_status": [],
            "get_log": [],
            "retire_nozzle": ["nozzle_id"],
            "add_nozzle": ["size", "material"],
            "export_log_csv": []
        }

    def on_api_command(self, command, data):
        data = data or {}
        if command == "status":
            return jsonify(self.get_api_status())

        elif command == "set_tool_profile":
            tool_id = normalize_tool_id(data.get("tool_id"))
            profile_id = data.get("profile_id")
            if not tool_id:
                self._logger.debug("Phase1 API set_tool_profile invalid tool_id: %r", data.get("tool_id"))
                return jsonify({"error": "Invalid tool_id"}), 400
            if not profile_id:
                self._logger.debug("Phase1 API set_tool_profile missing profile_id")
                return jsonify({"error": "Missing profile_id"}), 400

            with self._lock:
                self._ensure_phase1_settings(save=False)
                if profile_id not in self._nozzle_profiles:
                    self._logger.debug("Phase1 API set_tool_profile unknown profile_id: %r", profile_id)
                    return jsonify({"error": "Unknown profile_id"}), 400

            try:
                self.set_tool_profile(tool_id, profile_id)
            except ValueError as exc:
                self._logger.debug("Phase1 API set_tool_profile error: %s", exc)
                return jsonify({"error": str(exc)}), 400

            return jsonify(self.get_api_status())

        elif command == "reset_tool":
            tool_id = normalize_tool_id(data.get("tool_id"))
            if not tool_id:
                self._logger.debug("Phase1 API reset_tool invalid tool_id: %r", data.get("tool_id"))
                return jsonify({"error": "Invalid tool_id"}), 400

            try:
                self.reset_tool(tool_id)
            except ValueError as exc:
                self._logger.debug("Phase1 API reset_tool error: %s", exc)
                return jsonify({"error": str(exc)}), 400

            return jsonify(self.get_api_status())

        if command == "assign_nozzle":
            tool_id = normalize_tool_id(data.get("tool_id"))
            nozzle_id = str(data.get("nozzle_id") or "").strip()
            if not tool_id:
                return jsonify({"error": "Invalid tool_id"}), 400
            if not nozzle_id:
                return jsonify({"error": "Invalid nozzle_id"}), 400
            try:
                self.assign_nozzle(tool_id, nozzle_id)
            except ValueError as exc:
                self._logger.debug("Phase2 API assign_nozzle error: %s", exc)
                return jsonify({"error": str(exc)}), 400
            return jsonify(self.get_api_status())

        elif command == "create_nozzle":
            name = str(data.get("name") or "").strip()
            profile_id = str(data.get("profile_id") or "").strip()
            if not name:
                return jsonify({"error": "Missing name"}), 400
            if not profile_id:
                return jsonify({"error": "Missing profile_id"}), 400
            try:
                nozzle = self.create_nozzle(
                    name=name,
                    profile_id=profile_id,
                    notes=data.get("notes"),
                    life_seconds=data.get("life_seconds"),
                    material=data.get("material"),
                    size_mm=data.get("size_mm"),
                    metadata=data.get("metadata"),
                )
            except ValueError as exc:
                self._logger.debug("Phase2 API create_nozzle error: %s", exc)
                return jsonify({"error": str(exc)}), 400
            return jsonify({"success": True, "nozzle": nozzle})

        elif command == "reset_nozzle":
            nozzle_id = str(data.get("nozzle_id") or "").strip()
            if not nozzle_id:
                return jsonify({"error": "Invalid nozzle_id"}), 400
            try:
                self.reset_nozzle(nozzle_id)
            except ValueError as exc:
                self._logger.debug("Phase2 API reset_nozzle error: %s", exc)
                return jsonify({"error": str(exc)}), 400
            return jsonify(self.get_api_status())

        elif command == "select_nozzle":
            # Legacy alias for assigning nozzle to T0.
            nozzle_id = str(data.get("nozzle_id") or "").strip()
            if not nozzle_id:
                return {"success": False, "error": "Invalid or retired nozzle."}
            try:
                self.assign_nozzle("T0", nozzle_id)
            except ValueError:
                return {"success": False, "error": "Invalid or retired nozzle."}
            self._current_nozzle = nozzle_id
            self._settings.set(["default_nozzle_id"], nozzle_id)
            self._settings.save()
            return {"success": True}

        elif command == "get_status":
            active_tool = self._active_tool_id or DEFAULT_TOOL_ID
            active_mapping = self._tool_map.get(active_tool) or {}
            active_nozzle_id = active_mapping.get("active_nozzle_id")
            active_nozzle = self._nozzles.get(active_nozzle_id) if active_nozzle_id else {}
            return {
                "current_tool": active_tool,
                "current_nozzle": active_nozzle_id,
                "runtime": (active_nozzle or {}).get("accumulated_seconds", 0),
                "expected": (active_nozzle or {}).get("life_seconds", 0),
                "nozzle_name": (active_nozzle or {}).get("name", active_nozzle_id),
                "prompt_enabled": self._settings.get(["prompt_before_print"]),
                "display_mode": self._settings.get(["display_mode"])
            }

        elif command == "get_log":
            return {"log": self._print_log}

        elif command == "retire_nozzle":
            nozzle_id = data.get("nozzle_id")
            try:
                self.retire_nozzle(nozzle_id)
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            return {"success": True}

        elif command == "add_nozzle":
            # Legacy alias: map old add_nozzle semantics into Phase 2 create_nozzle.
            size = data.get("size")
            material = data.get("material") or "brass"
            default_name = "{} {} #{}".format(size or "0.4", material, len(self._nozzles) + 1)
            try:
                nozzle = self.create_nozzle(
                    name=default_name,
                    profile_id=DEFAULT_PROFILE_ID,
                    material=material,
                    size_mm=size if size is not None else 0.4,
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            return {"success": True, "nozzle_id": nozzle["id"], "name": nozzle["name"]}

        elif command == "export_log_csv":
            output = make_response(self._generate_csv())
            output.headers["Content-Disposition"] = "attachment; filename=nozzle_log.csv"
            output.headers["Content-type"] = "text/csv"
            return output

        self._logger.debug("Unknown API command: %r", command)
        return jsonify({"error": "Unknown command"}), 400

    def _generate_csv(self):
        import io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["timestamp", "nozzle_id", "nozzle_name", "file", "duration"])
        writer.writeheader()
        for entry in self._print_log:
            writer.writerow(entry)
        return output.getvalue()

    def get_api_status(self):
        with self._lock:
            return build_status_payload(
                self._nozzle_profiles,
                self._tool_state,
                nozzles=self._nozzles,
                tool_map=self._tool_map,
                errors=self._phase2_error_flags,
                active_tool_id=self._active_tool_id,
                tool_source=self._active_tool_source,
                now_ts=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            )

    ##~~ Helper Methods

    def _load_nozzles(self):
        legacy_nozzles = self._settings.get(["nozzles"]) or {}
        legacy_tool_state = self._settings.get(["tool_state"]) or {}
        legacy_replacement_log = self._settings.get(["replacement_log"]) or []
        self._nozzles = legacy_nozzles
        self._current_nozzle = self._settings.get(["default_nozzle_id"])
        self._print_log = self._settings.get(["print_log"]) or []
        self._nozzle_profiles = self._settings.get(["nozzle_profiles"]) or {}
        self._tool_map = self._settings.get(["tool_map"]) or {}
        self._tool_state = {}
        self._replacement_log = []
        self._phase2_error_flags = {}
        if self._active_tool_id is None:
            self._active_tool_id = DEFAULT_TOOL_ID
        if not getattr(self, "_active_tool_source", None):
            self._active_tool_source = "fallback"
        self._load_runtime_state(
            legacy_tool_state=legacy_tool_state,
            legacy_replacement_log=legacy_replacement_log,
            legacy_nozzles=legacy_nozzles,
        )

    def _runtime_state_path(self):
        return os.path.join(self.get_plugin_data_folder(), RUNTIME_STATE_FILENAME)

    def _runtime_state_payload(self):
        return build_runtime_state(self._tool_state, self._replacement_log, self._nozzles)

    def _load_runtime_state(self, legacy_tool_state, legacy_replacement_log, legacy_nozzles):
        runtime_state_path = self._runtime_state_path()
        runtime_state, status = load_runtime_state_file(runtime_state_path)

        if status == "loaded":
            self._logger.debug("Loaded runtime state from %s", runtime_state_path)
        elif status == "malformed":
            self._logger.warning("Runtime state file is malformed at %s; using defaults", runtime_state_path)
        elif has_legacy_runtime_state(legacy_tool_state, legacy_replacement_log, legacy_nozzles):
            runtime_state = build_runtime_state(legacy_tool_state, legacy_replacement_log, legacy_nozzles)
            self._logger.info("Migrating legacy runtime state from settings to %s", runtime_state_path)
            self._apply_runtime_state(runtime_state)
            if self._save_runtime_state():
                self._save_settings_state()
            return
        else:
            self._logger.debug("Runtime state file not found at %s; using defaults", runtime_state_path)

        self._apply_runtime_state(runtime_state)

    def _apply_runtime_state(self, runtime_state):
        normalized_runtime = build_runtime_state(
            runtime_state.get("tool_state"),
            runtime_state.get("replacement_log"),
            apply_runtime_state_to_nozzles(self._nozzles, runtime_state),
        )
        self._tool_state = normalized_runtime["tool_state"]
        self._replacement_log = normalized_runtime["replacement_log"]
        self._nozzles = apply_runtime_state_to_nozzles(self._nozzles, normalized_runtime)

    def _save_runtime_state(self):
        runtime_state_path = self._runtime_state_path()
        try:
            save_runtime_state_file(runtime_state_path, self._runtime_state_payload())
        except (OSError, ValueError, TypeError):
            self._logger.exception("Failed saving runtime state to %s", runtime_state_path)
            return False
        self._logger.debug("Saved runtime state to %s", runtime_state_path)
        return True

    def _save_settings_state(self):
        sanitized_tool_state, sanitized_replacement_log, sanitized_nozzles = strip_runtime_state_from_settings(
            self._tool_state,
            self._replacement_log,
            self._nozzles,
        )
        self._settings.set(["nozzle_profiles"], self._nozzle_profiles)
        self._settings.set(["tool_state"], sanitized_tool_state)
        self._settings.set(["nozzles"], sanitized_nozzles)
        self._settings.set(["tool_map"], self._tool_map)
        self._settings.set(["replacement_log"], sanitized_replacement_log)
        self._settings.save()
        self._logger.debug("Saved stable plugin settings after runtime-state update")

    def get_profiles(self):
        self._ensure_phase1_settings(save=False)
        return self._nozzle_profiles

    def get_tool_state(self):
        self._ensure_phase1_settings(save=False)
        return self._tool_state

    def assign_nozzle(self, tool_id, nozzle_id):
        with self._lock:
            self._ensure_phase1_settings(save=False)
            tool_id = normalize_tool_id(tool_id)
            nozzle_id = str(nozzle_id or "").strip()
            allowed, message = validate_assign_nozzle_allowed(tool_id, nozzle_id, self._nozzles, self._tool_map)
            if not allowed:
                raise ValueError(message or "Invalid nozzle assignment")

            proposed = dict(self._tool_map or {})
            proposed[tool_id] = {"active_nozzle_id": nozzle_id}
            conflicts = validate_unique_nozzle_assignments(proposed)
            if conflicts:
                raise ValueError("nozzle_id already assigned to another tool")

            self._tool_map = proposed
            self._tool_state.setdefault(tool_id, self._default_tool_state_entry(tool_id=tool_id))
            self._tool_state[tool_id]["profile_id"] = self._nozzles[nozzle_id].get("profile_id", DEFAULT_PROFILE_ID)
            self._phase2_error_flags = {}
            self._save_phase1_settings(tool_state_only=False)
            return self._tool_map[tool_id]

    def create_nozzle(self, name, profile_id, notes=None, life_seconds=None, material=None, size_mm=None, metadata=None):
        with self._lock:
            self._ensure_phase1_settings(save=False)
            if profile_id not in self._nozzle_profiles:
                raise ValueError("profile_id not found")

            nozzle_id = generate_nozzle_id(name, self._nozzles.keys())
            nozzle = {
                "id": nozzle_id,
                "name": str(name),
                "profile_id": profile_id,
                "material": str(material or "brass"),
                "size_mm": float(size_mm) if size_mm is not None else 0.4,
                "accumulated_seconds": 0,
                "retired": False,
                "metadata": {},
            }
            if nozzle["size_mm"] <= 0:
                nozzle["size_mm"] = 0.4
            if notes is not None:
                nozzle["notes"] = str(notes)
            if life_seconds is not None:
                try:
                    parsed_life = int(float(life_seconds))
                except (TypeError, ValueError):
                    raise ValueError("life_seconds must be a positive integer")
                if parsed_life <= 0:
                    raise ValueError("life_seconds must be a positive integer")
                nozzle["life_seconds"] = parsed_life
            if isinstance(metadata, dict):
                nozzle["metadata"] = {
                    str(key): str(value)
                    for key, value in metadata.items()
                    if key is not None and value is not None
                }

            self._nozzles[nozzle_id] = nozzle
            self._phase2_error_flags = {}
            self._save_phase1_settings(tool_state_only=False)
            return nozzle

    def reset_nozzle(self, nozzle_id):
        with self._lock:
            self._ensure_phase1_settings(save=False)
            nozzle_id = str(nozzle_id or "").strip()
            if nozzle_id not in self._nozzles:
                raise ValueError("nozzle_id not found")
            self._nozzles[nozzle_id]["accumulated_seconds"] = 0
            for tool_id, mapping in (self._tool_map or {}).items():
                if str((mapping or {}).get("active_nozzle_id") or "") == nozzle_id and tool_id in self._tool_state:
                    self._tool_state[tool_id]["accumulated_seconds"] = 0
            self._save_phase1_settings(tool_state_only=True)
            return self._nozzles[nozzle_id]

    def retire_nozzle(self, nozzle_id):
        with self._lock:
            self._ensure_phase1_settings(save=False)
            nozzle_id = str(nozzle_id or "").strip()
            if nozzle_id not in self._nozzles:
                raise ValueError("nozzle_id not found")
            allowed, message = validate_retire_nozzle_allowed(nozzle_id, self._tool_map)
            if not allowed:
                raise ValueError(message or RETIRE_ASSIGNED_NOZZLE_MESSAGE)
            self._nozzles[nozzle_id]["retired"] = True
            self._save_phase1_settings(tool_state_only=False)
            return self._nozzles[nozzle_id]

    def set_tool_profile(self, tool_id, profile_id):
        if not tool_id:
            raise ValueError("tool_id is required")

        with self._lock:
            self._ensure_phase1_settings(save=False)
            tool_id = str(tool_id).upper()

            if profile_id not in self._nozzle_profiles:
                raise ValueError("profile_id not found")

            state = self._normalize_tool_state_entry(
                tool_id,
                self._tool_state.get(tool_id),
                default_profile_id=profile_id
            )
            state["profile_id"] = profile_id
            self._tool_state[tool_id] = state
            mapping = self._tool_map.get(tool_id) or {}
            nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
            if nozzle_id in self._nozzles:
                self._nozzles[nozzle_id]["profile_id"] = profile_id
            self._save_phase1_settings(tool_state_only=False)
            return state

    def reset_tool(self, tool_id):
        if not tool_id:
            raise ValueError("tool_id is required")

        with self._lock:
            self._ensure_phase1_settings(save=False)
            tool_id = str(tool_id).upper()
            self._tool_state, self._replacement_log = reset_tool_state(
                self._tool_state,
                self._replacement_log,
                tool_id=tool_id,
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                default_profile_id=DEFAULT_PROFILE_ID,
            )
            state = self._tool_state[tool_id]
            mapping = self._tool_map.get(tool_id) or {}
            nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
            if nozzle_id in self._nozzles:
                self._nozzles[nozzle_id]["accumulated_seconds"] = 0
            self._save_phase1_settings(tool_state_only=True)
            return state

    def hook_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        tool_id = extract_tool_id_from_command(cmd)
        if not tool_id:
            return

        with self._lock:
            self._phase1_handle_tool_change_locked(tool_id)

    def _default_profile_dict(self):
        return {
            "id": DEFAULT_PROFILE_ID,
            "name": DEFAULT_PROFILE_NAME,
            "interval_hours": DEFAULT_PROFILE_INTERVAL_HOURS,
            "notes": ""
        }

    def _default_tool_state_entry(self, tool_id="T0", profile_id=DEFAULT_PROFILE_ID):
        return {
            "tool_id": str(tool_id).upper(),
            "profile_id": profile_id,
            "accumulated_seconds": 0
        }

    def _normalize_profile_entry(self, profile_id, profile):
        profile = profile or {}
        normalized_id = str(profile.get("id") or profile_id)
        interval = profile.get("interval_hours", DEFAULT_PROFILE_INTERVAL_HOURS)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = DEFAULT_PROFILE_INTERVAL_HOURS

        return {
            "id": normalized_id,
            "name": str(profile.get("name") or normalized_id),
            "interval_hours": interval,
            "notes": str(profile.get("notes") or "")
        }

    def _normalize_tool_state_entry(self, tool_id, state, default_profile_id=None):
        state = state or {}
        normalized_tool_id = str(state.get("tool_id") or tool_id).upper()
        profile_id = state.get("profile_id") or default_profile_id or DEFAULT_PROFILE_ID
        accumulated_seconds = state.get("accumulated_seconds", 0)
        try:
            accumulated_seconds = int(float(accumulated_seconds))
        except (TypeError, ValueError):
            accumulated_seconds = 0
        if accumulated_seconds < 0:
            accumulated_seconds = 0

        return {
            "tool_id": normalized_tool_id,
            "profile_id": profile_id,
            "accumulated_seconds": accumulated_seconds
        }

    def _ensure_phase1_settings(self, save=False):
        (
            normalized_profiles,
            normalized_tool_state,
            normalized_replacement_log,
            normalized_nozzles,
            normalized_tool_map,
            phase2_errors,
        ) = ensure_phase2_settings(
            self._settings.get(["nozzle_profiles"]),
            self._tool_state,
            self._replacement_log,
            self._nozzles,
            self._tool_map,
            default_profile_id=DEFAULT_PROFILE_ID,
            default_profile_name=DEFAULT_PROFILE_NAME,
            default_interval_hours=DEFAULT_PROFILE_INTERVAL_HOURS,
            active_tool_id=self._active_tool_id,
        )
        changed = False

        if self._nozzle_profiles != normalized_profiles:
            changed = True
        if self._tool_state != normalized_tool_state:
            changed = True
        if self._replacement_log != normalized_replacement_log:
            changed = True
        if self._nozzles != normalized_nozzles:
            changed = True
        if self._tool_map != normalized_tool_map:
            changed = True
        if self._phase2_error_flags != phase2_errors:
            changed = True

        self._nozzle_profiles = normalized_profiles
        self._tool_state = normalized_tool_state
        self._replacement_log = normalized_replacement_log
        self._nozzles = normalized_nozzles
        self._tool_map = normalized_tool_map
        self._phase2_error_flags = phase2_errors
        deduped_profiles, deduped_tool_state, dedupe_changed = dedupe_profiles(
            self._nozzle_profiles,
            self._tool_state,
            canonical_default_id=DEFAULT_PROFILE_ID,
        )
        if dedupe_changed:
            self._nozzle_profiles = deduped_profiles
            self._tool_state = deduped_tool_state
            changed = True

        if changed:
            if save:
                self._save_settings_state()
                self._save_runtime_state()

    def _phase1_handle_print_start_or_resume_locked(self):
        now_ts = time.time()
        if self._is_printing:
            self._phase1_tick_locked(now_ts=now_ts, persist_if_due=True)
        if not self._active_tool_id:
            self._active_tool_id = DEFAULT_TOOL_ID
        self._ensure_tool_state_entry_locked(self._active_tool_id)
        if not self._is_printing:
            self._last_phase1_persist_ts = now_ts
            self._logger.debug(
                "Active print tracking started for %s; runtime snapshots enabled every %ss",
                self._active_tool_id,
                PHASE1_PERSIST_INTERVAL_SECONDS,
            )
        self._is_printing = True
        self._last_tick_ts = now_ts

    def _phase1_handle_print_pause_or_stop_locked(self, force_persist=False):
        self._phase1_tick_locked(now_ts=time.time(), persist_if_due=False)
        self._is_printing = False
        self._last_tick_ts = None
        if force_persist:
            self._maybe_persist_phase1_tool_state_locked(force=True)

    def _phase1_handle_tool_change_locked(self, next_tool_id):
        next_tool_id = str(next_tool_id).upper()
        self._active_tool_source = "printer"
        now_ts = time.time()
        if self._is_printing:
            self._phase1_tick_locked(now_ts=now_ts, persist_if_due=False)
            self._active_tool_id = next_tool_id
            self._ensure_tool_state_entry_locked(self._active_tool_id)
            self._last_tick_ts = now_ts
            self._maybe_persist_phase1_tool_state_locked(force=False)
        else:
            self._active_tool_id = next_tool_id
            self._ensure_tool_state_entry_locked(self._active_tool_id)

    def _phase1_tick_locked(self, now_ts=None, persist_if_due=True):
        if not self._is_printing or not self._active_tool_id:
            return 0

        if now_ts is None:
            now_ts = time.time()

        delta_seconds = compute_elapsed_seconds(self._last_tick_ts, now_ts)
        self._last_tick_ts = now_ts
        if delta_seconds <= 0:
            return 0

        self._ensure_tool_state_entry_locked(self._active_tool_id)
        mapping = self._tool_map.get(self._active_tool_id) or {}
        assigned_nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if not assigned_nozzle_id or assigned_nozzle_id not in self._nozzles:
            self._phase2_error_flags["missing_tool_assignment"] = {
                str(self._active_tool_id): True
            }
            return delta_seconds

        updated_nozzles, nozzle_changed = accumulate_nozzle_seconds(
            self._nozzles,
            assigned_nozzle_id,
            delta_seconds,
            default_profile_id=self._tool_state.get(self._active_tool_id, {}).get("profile_id", DEFAULT_PROFILE_ID),
        )
        updated_tool_state, tool_changed = accumulate_tool_seconds(
            self._tool_state,
            self._active_tool_id,
            delta_seconds
        )
        if nozzle_changed or tool_changed:
            self._nozzles = updated_nozzles
            self._tool_state = updated_tool_state
            if assigned_nozzle_id in self._nozzles:
                self._tool_state[self._active_tool_id]["profile_id"] = self._nozzles[assigned_nozzle_id].get(
                    "profile_id",
                    DEFAULT_PROFILE_ID,
                )
            self._phase1_runtime_dirty = True
            self._phase2_error_flags = {}
            if persist_if_due:
                self._maybe_persist_phase1_tool_state_locked(force=False)
        return delta_seconds

    def _ensure_tool_state_entry_locked(self, tool_id):
        tool_id = str(tool_id).upper()
        state = self._normalize_tool_state_entry(tool_id, self._tool_state.get(tool_id))
        if state["profile_id"] not in self._nozzle_profiles:
            state["profile_id"] = DEFAULT_PROFILE_ID
        self._tool_state[tool_id] = state
        mapping = self._tool_map.get(tool_id) or {}
        nozzle_id = str(mapping.get("active_nozzle_id") or "").strip()
        if not nozzle_id or nozzle_id not in self._nozzles:
            legacy_nozzle_id = "nozzle_{}_legacy".format(tool_id)
            if legacy_nozzle_id not in self._nozzles:
                self._nozzles[legacy_nozzle_id] = {
                    "id": legacy_nozzle_id,
                    "name": "Legacy {}".format(tool_id),
                    "profile_id": state["profile_id"],
                    "material": "brass",
                    "size_mm": 0.4,
                    "accumulated_seconds": int(state.get("accumulated_seconds", 0) or 0),
                    "retired": False,
                    "metadata": {},
                }
            self._tool_map[tool_id] = {"active_nozzle_id": legacy_nozzle_id}
        return state

    def _save_phase1_settings(self, tool_state_only=False):
        runtime_saved = self._save_runtime_state()
        if not tool_state_only and not runtime_saved:
            self._logger.warning("Skipping stable settings save because runtime-state persistence failed")
        if not tool_state_only and runtime_saved:
            self._save_settings_state()
        if runtime_saved:
            self._phase1_runtime_dirty = False
            self._last_phase1_persist_ts = time.time()
        return runtime_saved

    def _maybe_persist_phase1_tool_state_locked(self, force=False):
        now_ts = time.time()
        should_snapshot = should_snapshot_runtime_state(
            is_printing=self._is_printing,
            is_dirty=self._phase1_runtime_dirty,
            last_snapshot_ts=self._last_phase1_persist_ts,
            now_ts=now_ts,
            interval_seconds=PHASE1_PERSIST_INTERVAL_SECONDS,
            force=force,
        )
        if not should_snapshot:
            return False

        runtime_saved = self._save_phase1_settings(tool_state_only=True)
        if runtime_saved and force:
            self._logger.debug("Saved runtime state at print-state transition")
        elif runtime_saved:
            self._logger.debug(
                "Saved active-print runtime snapshot for %s at %ss boundary",
                self._active_tool_id,
                PHASE1_PERSIST_INTERVAL_SECONDS,
            )
        return runtime_saved

    def _start_phase1_persist_worker(self):
        if self._persist_worker and self._persist_worker.is_alive():
            return

        self._persist_worker_stop.clear()
        self._persist_worker = threading.Thread(
            target=self._phase1_persist_worker_loop,
            name="NozzleLifePhase1Persist",
            daemon=True
        )
        self._persist_worker.start()

    def _phase1_persist_worker_loop(self):
        while not self._persist_worker_stop.wait(PHASE1_PERSIST_CHECK_INTERVAL_SECONDS):
            with self._lock:
                if not self._is_printing:
                    continue
                self._phase1_tick_locked(now_ts=time.time(), persist_if_due=True)


def __plugin_load__():
    global __plugin_implementation__
    global __plugin_hooks__
    __plugin_implementation__ = NozzleLifeTrackerPlugin()
    __plugin_hooks__ = {
        "octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.hook_gcode_queuing
    }

