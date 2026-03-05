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
        self.showRetired = ko.observable(false);

        self.createNozzleName = ko.observable("");
        self.createNozzleProfileId = ko.observable("");
        self.createNozzleMaterial = ko.observable("brass");
        self.createNozzleSizeMm = ko.observable("0.4");
        self.createNozzleNotes = ko.observable("");
        self.createNozzleLifeHours = ko.observable("");
        self.createNozzleMetadata = ko.observable("");

        self.lastGeneratedAt = ko.observable("");
        self.errorText = ko.observable("");

        self.hasTools = ko.pureComputed(function () {
            return self.tools().length > 0;
        });

        self.hasNozzles = ko.pureComputed(function () {
            return self.nozzles().length > 0;
        });

        self.filteredNozzles = ko.pureComputed(function () {
            return self.nozzles().filter(function (nozzle) {
                return self.showRetired() || !nozzle.retired;
            });
        });

        self.parseMetadata = function (rawText) {
            var result = {};
            var text = (rawText || "").trim();
            if (!text) {
                return result;
            }
            text.split(/\r?\n/).forEach(function (line) {
                var trimmed = (line || "").trim();
                if (!trimmed) {
                    return;
                }
                var idx = trimmed.indexOf("=");
                if (idx <= 0) {
                    return;
                }
                var key = trimmed.substring(0, idx).trim();
                var value = trimmed.substring(idx + 1).trim();
                if (key) {
                    result[key] = value;
                }
            });
            return result;
        };

        self.nozzleLabel = function (nozzle) {
            if (!nozzle) {
                return "";
            }
            return nozzle.retired ? (nozzle.name + " (retired)") : nozzle.name;
        };

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
                    if (!self.createNozzleProfileId() && profiles.length > 0) {
                        self.createNozzleProfileId(profiles[0].id);
                    }

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
                    self.errorText("Failed to load status.");
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
            var selected = self.nozzles().find(function (n) {
                return n.id === nozzleId;
            });
            if (selected && selected.retired) {
                self.errorText("Cannot assign a retired nozzle.");
                return $.Deferred().reject().promise();
            }
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "assign_nozzle", {
                tool_id: tool.tool_id,
                nozzle_id: nozzleId,
            })
                .done(function () {
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] assign_nozzle failed", xhr);
                    var message = (xhr && xhr.responseJSON && xhr.responseJSON.error) || "Failed to assign nozzle.";
                    self.errorText(message);
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

        self.resetNozzle = function (nozzle) {
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "reset_nozzle", {
                nozzle_id: nozzle.id,
            })
                .done(function () {
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] reset_nozzle failed", xhr);
                    var message = (xhr && xhr.responseJSON && xhr.responseJSON.error) || "Failed to reset nozzle.";
                    self.errorText(message);
                });
        };

        self.retireNozzle = function (nozzle) {
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "retire_nozzle", {
                nozzle_id: nozzle.id,
            })
                .done(function (response) {
                    if (response && response.success === false) {
                        self.errorText(response.error || "Failed to retire nozzle.");
                        return;
                    }
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] retire_nozzle failed", xhr);
                    var message = (xhr && xhr.responseJSON && xhr.responseJSON.error) || "Failed to retire nozzle.";
                    self.errorText(message);
                });
        };

        self.createNozzle = function () {
            var name = (self.createNozzleName() || "").trim();
            var profileId = (self.createNozzleProfileId() || "").trim();
            if (!name || !profileId) {
                self.errorText("Name and profile are required.");
                return $.Deferred().reject().promise();
            }

            var payload = {
                name: name,
                profile_id: profileId,
                material: (self.createNozzleMaterial() || "brass").trim() || "brass",
                size_mm: self.createNozzleSizeMm() || "0.4",
                notes: self.createNozzleNotes(),
                metadata: self.parseMetadata(self.createNozzleMetadata()),
            };

            var lifeHours = (self.createNozzleLifeHours() || "").trim();
            if (lifeHours) {
                var parsed = parseFloat(lifeHours);
                if (!isNaN(parsed) && parsed > 0) {
                    payload.life_seconds = Math.round(parsed * 3600.0);
                }
            }

            return OctoPrint.simpleApiCommand("nozzlelifetracker", "create_nozzle", payload)
                .done(function () {
                    self.createNozzleName("");
                    self.createNozzleMaterial("brass");
                    self.createNozzleSizeMm("0.4");
                    self.createNozzleNotes("");
                    self.createNozzleLifeHours("");
                    self.createNozzleMetadata("");
                    self.fetchStatus();
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] create_nozzle failed", xhr);
                    var message = (xhr && xhr.responseJSON && xhr.responseJSON.error) || "Failed to create nozzle.";
                    self.errorText(message);
                });
        };

        self.nozzleOptionsForTool = function (tool) {
            return self.nozzles().filter(function (nozzle) {
                if (!self.showRetired() && nozzle.retired && nozzle.id !== tool.active_nozzle_id) {
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
