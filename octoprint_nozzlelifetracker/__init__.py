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

__plugin_name__ = "Nozzle Life Tracker"
__plugin_version__ = "0.2.6"
__plugin_pythoncompat__ = ">=3.7,<3.12"
__plugin_octoprint_version__ = ">=1.9,<2"

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

    ##~~ StartupPlugin

    def on_after_startup(self):
        self._logger.info("NozzleLifeTracker plugin started.")
        self._load_nozzles()

    ##~~ SettingsPlugin

    def get_settings_defaults(self):
        return {
            "nozzles": {},
            "default_nozzle_id": None,
            "prompt_before_print": False,
            "display_mode": "circle",  # Options: circle, bar, both
            "print_log": []
        }

    def on_settings_save(self, data):
        SettingsPlugin.on_settings_save(self, data)
        self._load_nozzles()

    def get_template_configs(self):
        # Explicit template mapping; forces OctoPrint to inject both panes
        return [
            dict(type="settings",
                 name="Nozzle Life",
                 template="nozzlelifetracker_settings",
                 custom_bindings=True),
            dict(type="sidebar",
                 name="Nozzle Life",
                 template="nozzlelifetracker_sidebar",
                 custom_bindings=True),
        ]


    ##~~ EventHandlerPlugin

    def on_event(self, event, payload):
        with self._lock:
            if event == "PrintStarted":
                self._print_start_time = time.time()

            elif event in ["PrintDone", "PrintCancelled", "PrintFailed"]:
                if self._print_start_time and self._current_nozzle:
                    elapsed = (time.time() - self._print_start_time) / 3600.0
                    nozzle_id = self._current_nozzle
                    if nozzle_id in self._nozzles:
                        self._nozzles[nozzle_id]['runtime'] += elapsed

                    log_entry = {
                        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                        "nozzle_id": nozzle_id,
                        "duration": elapsed,
                        "file": payload.get('name', 'Unknown'),
                        "nozzle_name": self._nozzles[nozzle_id].get("name", nozzle_id)
                    }
                    self._print_log.append(log_entry)
                    self._settings.set(["nozzles"], self._nozzles)
                    self._settings.set(["print_log"], self._print_log)
                    self._settings.save()

                self._print_start_time = None

    ##~~ SimpleApiPlugin (for frontend interaction)
    def is_api_protected(self):
        return True

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


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = NozzleLifeTrackerPlugin()
