$(function () {
    function NozzleLifeTrackerViewModel(parameters) {
        var self = this;
        self.loginStateViewModel = parameters[0];
        self.settingsViewModel = parameters[1];

        self.profiles = ko.observableArray([]);
        self.tools = ko.observableArray([]);
        self.nozzles = ko.observableArray([]);
        self.toolMap = ko.observable({});
        self.activeToolId = ko.observable("");
        self.activeNozzle = ko.observable(null);
        self.lastGeneratedAt = ko.observable("");
        self.errorText = ko.observable("");

        self.hasTools = ko.pureComputed(function () {
            return self.tools().length > 0;
        });

        self.hasNozzles = ko.pureComputed(function () {
            return self.nozzles().length > 0;
        });

        self.fetchStatus = function () {
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "status", {})
                .done(function (response) {
                    var profiles = (response && response.profiles) || [];
                    var tools = (response && response.tools) || [];
                    var nozzles = (response && response.nozzles) || [];
                    var toolMap = (response && response.tool_map) || {};
                    var meta = (response && response.meta) || {};
                    var previousToolsById = {};
                    var errors = meta.error_flags || {};

                    self.tools().forEach(function (row) {
                        if (row && row.tool_id && row.selected_profile_id) {
                            previousToolsById[row.tool_id] = {
                                profile_id: row.selected_profile_id(),
                                nozzle_id: row.selected_nozzle_id ? row.selected_nozzle_id() : row.active_nozzle_id,
                            };
                        }
                    });

                    self.profiles(profiles);
                    self.nozzles(nozzles);
                    self.toolMap(toolMap);
                    self.activeToolId(meta.active_tool_id || "");
                    self.activeNozzle(meta.active_nozzle || null);
                    self.tools(
                        tools.map(function (tool) {
                            var previous = previousToolsById[tool.tool_id] || {};
                            var selectedProfileId = previous.profile_id || tool.profile_id;
                            var selectedNozzleId = previous.nozzle_id || tool.active_nozzle_id;
                            return {
                                tool_id: tool.tool_id,
                                profile_id: tool.profile_id,
                                profile_name: tool.profile_name,
                                interval_hours: tool.interval_hours,
                                accumulated_seconds: tool.accumulated_seconds,
                                accumulated_hours: tool.accumulated_hours,
                                percent_to_interval: tool.percent_to_interval,
                                is_overdue: tool.is_overdue,
                                active_nozzle_id: tool.active_nozzle_id,
                                runtime_source: tool.runtime_source,
                                selected_profile_id: ko.observable(selectedProfileId),
                                selected_nozzle_id: ko.observable(selectedNozzleId),
                            };
                        })
                    );
                    self.lastGeneratedAt(meta.generated_at || "");
                    if (Object.keys(errors).length > 0) {
                        self.errorText("Status warnings: " + Object.keys(errors).join(", "));
                    } else {
                        self.errorText("");
                    }
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] status fetch failed", xhr);
                    self.errorText("Failed to load Phase 2 status.");
                });
        };

        self.setToolProfile = function (tool, event) {
            var profileId = (tool && tool.selected_profile_id && tool.selected_profile_id()) ||
                (event && event.target && event.target.value) ||
                tool.profile_id;
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "set_tool_profile", {
                tool_id: tool.tool_id,
                profile_id: profileId,
            })
                .done(function () {
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] set_tool_profile failed", xhr);
                    self.errorText("Failed to change tool profile.");
                });
        };

        self.assignNozzle = function (tool, event) {
            var nozzleId = (tool && tool.selected_nozzle_id && tool.selected_nozzle_id()) ||
                (event && event.target && event.target.value) ||
                tool.active_nozzle_id;
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "assign_nozzle", {
                tool_id: tool.tool_id,
                nozzle_id: nozzleId,
            })
                .done(function () {
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] assign_nozzle failed", xhr);
                    self.errorText("Failed to assign nozzle.");
                });
        };

        self.resetTool = function (tool) {
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "reset_tool", {
                tool_id: tool.tool_id,
            })
                .done(function () {
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] reset_tool failed", xhr);
                    self.errorText("Failed to reset tool.");
                });
        };

        self.nozzleOptionsForTool = function (tool) {
            return self.nozzles().filter(function (nozzle) {
                if (nozzle.retired && nozzle.id !== tool.active_nozzle_id) {
                    return false;
                }
                return true;
            });
        };

        self.onStartupComplete = function () {
            self.fetchStatus();
            window.setInterval(function () {
                self.fetchStatus();
            }, 10000);
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: NozzleLifeTrackerViewModel,
        dependencies: ["loginStateViewModel", "settingsViewModel"],
        elements: ["#sidebar_plugin_nozzlelifetracker", "#settings_plugin_nozzlelifetracker"],
    });
});
