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
import time
import threading
import uuid
try:
    from flask import make_response, request
except ImportError:
    request = None

    def make_response(*args, **kwargs):
        raise RuntimeError("Flask is required for response generation")
import csv
from .phase1_pure import (
    compute_elapsed_seconds,
    accumulate_tool_seconds,
    extract_tool_id_from_command,
)
from .phase1_settings import (
    ensure_phase1_settings,
    reset_tool_state,
)

##~~ __plugin_name__ = "Nozzle Life Tracker"
##~~ __plugin_version__ = "0.2.7"
__plugin_pythoncompat__ = ">=3.7,<3.12"
__plugin_octoprint_version__ = ">=1.9,<2"

DEFAULT_PROFILE_ID = "default_0_4_brass"
DEFAULT_PROFILE_NAME = "0.4 Brass"
DEFAULT_PROFILE_INTERVAL_HOURS = 100.0
DEFAULT_TOOL_ID = "T0"
PHASE1_PERSIST_INTERVAL_SECONDS = 300
PHASE1_PERSIST_CHECK_INTERVAL_SECONDS = 30

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
        self._replacement_log = []
        self._is_printing = False
        self._last_tick_ts = None
        self._active_tool_id = DEFAULT_TOOL_ID
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
        if worker is None or stop_event is None:
            return

        try:
            stop_event.set()
            if worker.is_alive():
                worker.join(timeout=3)
        except Exception:
            self._logger.exception("Error stopping Phase 1 persist worker")

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
                 name="Nozzle Life",
                 template="settings/nozzlelifetracker_settings",
                 custom_bindings=False),
            dict(type="sidebar",
                 name="Nozzle Life",
                 template="sidebar/nozzlelifetracker_sidebar",
                 custom_bindings=False),
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

    def _accumulate_runtime(self, payload):
        if not self._print_start_time or not self._current_nozzle:
            return

        nozzle_id = self._current_nozzle
        if nozzle_id not in self._nozzles:
            return

        safe_payload = payload or {}
        elapsed = (time.time() - self._print_start_time) / 3600.0

        self._nozzles[nozzle_id].setdefault("runtime", 0.0)
        self._nozzles[nozzle_id]["runtime"] += elapsed

        log_entry = {
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "nozzle_id": nozzle_id,
            "duration": elapsed,
            "file": safe_payload.get("name", "Unknown"),
            "nozzle_name": self._nozzles[nozzle_id].get("name", nozzle_id)
        }
        self._print_log.append(log_entry)
        self._settings.set(["nozzles"], self._nozzles)
        self._settings.set(["print_log"], self._print_log)
        self._settings.save()

    ##~~ SimpleApiPlugin (for frontend interaction)
    def is_api_protected(self):
        return True

    def on_api_get(self, request):
        if request.values.get("command") == "export_log_csv":
            output = make_response(self._generate_csv())
            output.headers["Content-Disposition"] = "attachment; filename=nozzle_log.csv"
            output.headers["Content-type"] = "text/csv"
            return output
        return make_response("Unknown command", 400)

    def get_api_commands(self):
        return {
            "select_nozzle": ["nozzle_id"],
            "get_status": [],
            "get_log": [],
            "retire_nozzle": ["nozzle_id"],
            "add_nozzle": ["size", "material"],
            "export_log_csv": []
        }

    def on_api_command(self, command, data):
        if command == "select_nozzle":
            nozzle_id = data.get("nozzle_id")
            if nozzle_id in self._nozzles and not self._nozzles[nozzle_id].get("retired"):
                self._current_nozzle = nozzle_id
                self._settings.set(["default_nozzle_id"], nozzle_id)
                self._settings.save()
                return {"success": True}
            return {"success": False, "error": "Invalid or retired nozzle."}

        elif command == "get_status":
            return {
                "current_nozzle": self._current_nozzle,
                "runtime": self._nozzles.get(self._current_nozzle, {}).get("runtime", 0),
                "expected": self._nozzles.get(self._current_nozzle, {}).get("expected_life", 0),
                "nozzle_name": self._nozzles.get(self._current_nozzle, {}).get("name", self._current_nozzle),
                "prompt_enabled": self._settings.get(["prompt_before_print"]),
                "display_mode": self._settings.get(["display_mode"])
            }

        elif command == "get_log":
            return {"log": self._print_log}

        elif command == "retire_nozzle":
            nozzle_id = data.get("nozzle_id")
            if nozzle_id in self._nozzles:
                self._nozzles[nozzle_id]["retired"] = True
                self._settings.set(["nozzles"], self._nozzles)
                self._settings.save()
                return {"success": True}
            return {"success": False, "error": "Nozzle not found."}

        elif command == "add_nozzle":
            size = data.get("size")
            material = data.get("material")
            nozzle_id = str(uuid.uuid4())
            same_type = [n for n in self._nozzles.values() if n["size"] == size and n["material"] == material]
            count = len(same_type) + 1
            default_name = f"{size} {material} #{count}"

            self._nozzles[nozzle_id] = {
                "size": size,
                "material": material,
                "expected_life": 0,
                "runtime": 0,
                "retired": False,
                "name": default_name
            }
            self._settings.set(["nozzles"], self._nozzles)
            self._settings.save()
            return {"success": True, "nozzle_id": nozzle_id, "name": default_name}

        elif command == "export_log_csv":
            output = make_response(self._generate_csv())
            output.headers["Content-Disposition"] = "attachment; filename=nozzle_log.csv"
            output.headers["Content-type"] = "text/csv"
            return output

    def _generate_csv(self):
        import io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["timestamp", "nozzle_id", "nozzle_name", "file", "duration"])
        writer.writeheader()
        for entry in self._print_log:
            writer.writerow(entry)
        return output.getvalue()

    ##~~ Helper Methods

    def _load_nozzles(self):
        self._nozzles = self._settings.get(["nozzles"]) or {}
        self._current_nozzle = self._settings.get(["default_nozzle_id"])
        self._print_log = self._settings.get(["print_log"]) or []
        self._nozzle_profiles = self._settings.get(["nozzle_profiles"]) or {}
        self._tool_state = self._settings.get(["tool_state"]) or {}
        self._replacement_log = self._settings.get(["replacement_log"]) or []
        if self._active_tool_id is None:
            self._active_tool_id = DEFAULT_TOOL_ID

    def get_profiles(self):
        self._ensure_phase1_settings(save=False)
        return self._nozzle_profiles

    def get_tool_state(self):
        self._ensure_phase1_settings(save=False)
        return self._tool_state

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
            self._save_phase1_settings(tool_state_only=True)
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
            self._save_phase1_settings(tool_state_only=False)
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
        normalized_profiles, normalized_tool_state, normalized_replacement_log = ensure_phase1_settings(
            self._settings.get(["nozzle_profiles"]),
            self._settings.get(["tool_state"]),
            self._settings.get(["replacement_log"]),
            default_profile_id=DEFAULT_PROFILE_ID,
            default_profile_name=DEFAULT_PROFILE_NAME,
            default_interval_hours=DEFAULT_PROFILE_INTERVAL_HOURS,
        )
        changed = False

        if self._nozzle_profiles != normalized_profiles:
            changed = True
        if self._tool_state != normalized_tool_state:
            changed = True
        if self._replacement_log != normalized_replacement_log:
            changed = True

        self._nozzle_profiles = normalized_profiles
        self._tool_state = normalized_tool_state
        self._replacement_log = normalized_replacement_log

        if changed:
            self._settings.set(["nozzle_profiles"], self._nozzle_profiles)
            self._settings.set(["tool_state"], self._tool_state)
            self._settings.set(["replacement_log"], self._replacement_log)
            if save:
                self._settings.save()

    def _phase1_handle_print_start_or_resume_locked(self):
        now_ts = time.time()
        if self._is_printing:
            self._phase1_tick_locked(now_ts=now_ts, persist_if_due=True)
        if not self._active_tool_id:
            self._active_tool_id = DEFAULT_TOOL_ID
        self._ensure_tool_state_entry_locked(self._active_tool_id)
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
        updated_tool_state, changed = accumulate_tool_seconds(
            self._tool_state,
            self._active_tool_id,
            delta_seconds
        )
        if changed:
            self._tool_state = updated_tool_state
            self._phase1_runtime_dirty = True
            if persist_if_due:
                self._maybe_persist_phase1_tool_state_locked(force=False)
        return delta_seconds

    def _ensure_tool_state_entry_locked(self, tool_id):
        tool_id = str(tool_id).upper()
        state = self._normalize_tool_state_entry(tool_id, self._tool_state.get(tool_id))
        if state["profile_id"] not in self._nozzle_profiles:
            state["profile_id"] = DEFAULT_PROFILE_ID
        self._tool_state[tool_id] = state
        return state

    def _save_phase1_settings(self, tool_state_only=False):
        self._settings.set(["tool_state"], self._tool_state)
        if not tool_state_only:
            self._settings.set(["replacement_log"], self._replacement_log)
        self._settings.save()
        self._phase1_runtime_dirty = False
        self._last_phase1_persist_ts = time.time()

    def _maybe_persist_phase1_tool_state_locked(self, force=False):
        if not self._phase1_runtime_dirty:
            return False

        now_ts = time.time()
        due = force or (now_ts - self._last_phase1_persist_ts) >= PHASE1_PERSIST_INTERVAL_SECONDS
        if not due:
            return False

        self._save_phase1_settings(tool_state_only=True)
        return True

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
