# NozzleLifeTracker Plugin - OctoPrint Plugin Scaffold

from octoprint.plugin import (
    StartupPlugin,
    SettingsPlugin,
    AssetPlugin,
    TemplatePlugin,
    EventHandlerPlugin,
    SimpleApiPlugin
)
import time
import threading
import uuid
from flask import make_response, request
import csv

##~~ __plugin_name__ = "Nozzle Life Tracker"
##~~ __plugin_version__ = "0.2.7"
__plugin_pythoncompat__ = ">=3.7,<3.12"
__plugin_octoprint_version__ = ">=1.9,<2"

DEFAULT_PROFILE_ID = "default_0_4_brass"
DEFAULT_PROFILE_NAME = "0.4 Brass"
DEFAULT_PROFILE_INTERVAL_HOURS = 100.0

class NozzleLifeTrackerPlugin(StartupPlugin,
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

    ##~~ StartupPlugin

    def on_after_startup(self):
        self._logger.info("NozzleLifeTracker plugin started.")
        self._load_nozzles()
        self._ensure_phase1_settings(save=True)

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
        self._ensure_phase1_settings(save=True)

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
                self._print_start_time = time.time()

            elif event == "PrintResumed":
                # Resume timing after a paused print
                self._print_start_time = time.time()

            elif event == "PrintPaused":
                # Persist elapsed runtime up to the pause point
                self._accumulate_runtime(payload)
                self._print_start_time = None

            elif event in ["PrintDone", "PrintCancelled", "PrintFailed"]:
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

    def get_profiles(self):
        self._ensure_phase1_settings(save=False)
        return self._nozzle_profiles

    def get_tool_state(self):
        self._ensure_phase1_settings(save=False)
        return self._tool_state

    def set_tool_profile(self, tool_id, profile_id):
        if not tool_id:
            raise ValueError("tool_id is required")

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
        self._settings.set(["tool_state"], self._tool_state)
        self._settings.save()
        return state

    def reset_tool(self, tool_id):
        if not tool_id:
            raise ValueError("tool_id is required")

        self._ensure_phase1_settings(save=False)
        tool_id = str(tool_id).upper()

        with self._lock:
            state = self._normalize_tool_state_entry(tool_id, self._tool_state.get(tool_id))
            log_entry = {
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "tool_id": tool_id,
                "profile_id": state.get("profile_id"),
                "accumulated_seconds_at_reset": state.get("accumulated_seconds", 0)
            }
            state["accumulated_seconds"] = 0
            self._tool_state[tool_id] = state
            self._replacement_log.append(log_entry)
            self._settings.set(["tool_state"], self._tool_state)
            self._settings.set(["replacement_log"], self._replacement_log)
            self._settings.save()
            return state

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
        changed = False

        raw_profiles = self._settings.get(["nozzle_profiles"])
        if not isinstance(raw_profiles, dict):
            raw_profiles = {}
            changed = True
        normalized_profiles = {}
        for profile_id, profile in raw_profiles.items():
            normalized = self._normalize_profile_entry(profile_id, profile)
            normalized_profiles[normalized["id"]] = normalized

        if DEFAULT_PROFILE_ID not in normalized_profiles:
            normalized_profiles[DEFAULT_PROFILE_ID] = self._default_profile_dict()
            changed = True

        raw_tool_state = self._settings.get(["tool_state"])
        if not isinstance(raw_tool_state, dict):
            raw_tool_state = {}
            changed = True
        normalized_tool_state = {}
        for tool_id, state in raw_tool_state.items():
            normalized = self._normalize_tool_state_entry(tool_id, state)
            if normalized["profile_id"] not in normalized_profiles:
                normalized["profile_id"] = DEFAULT_PROFILE_ID
                changed = True
            normalized_tool_state[normalized["tool_id"]] = normalized

        if "T0" not in normalized_tool_state:
            normalized_tool_state["T0"] = self._default_tool_state_entry("T0", DEFAULT_PROFILE_ID)
            changed = True

        raw_replacement_log = self._settings.get(["replacement_log"])
        if not isinstance(raw_replacement_log, list):
            raw_replacement_log = []
            changed = True

        normalized_replacement_log = []
        for entry in raw_replacement_log:
            if not isinstance(entry, dict):
                changed = True
                continue
            normalized_entry = {
                "timestamp": str(entry.get("timestamp") or ""),
                "tool_id": str(entry.get("tool_id") or "T0").upper(),
                "profile_id": str(entry.get("profile_id") or DEFAULT_PROFILE_ID),
                "accumulated_seconds_at_reset": 0
            }
            try:
                normalized_entry["accumulated_seconds_at_reset"] = int(
                    float(entry.get("accumulated_seconds_at_reset", 0))
                )
            except (TypeError, ValueError):
                changed = True
            normalized_replacement_log.append(normalized_entry)

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


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = NozzleLifeTrackerPlugin()
