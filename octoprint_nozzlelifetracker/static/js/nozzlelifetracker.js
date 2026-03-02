$(function () {
    function NozzleLifeTrackerViewModel(parameters) {
        var self = this;
        self.loginStateViewModel = parameters[0];
        self.settingsViewModel = parameters[1];

        self.profiles = ko.observableArray([]);
        self.tools = ko.observableArray([]);
        self.lastGeneratedAt = ko.observable("");
        self.errorText = ko.observable("");

        self.hasTools = ko.pureComputed(function () {
            return self.tools().length > 0;
        });

        self.fetchStatus = function () {
            return OctoPrint.simpleApiCommand("nozzlelifetracker", "status", {})
                .done(function (response) {
                    var profiles = (response && response.profiles) || [];
                    var tools = (response && response.tools) || [];
                    var meta = (response && response.meta) || {};

                    self.profiles(profiles);
                    self.tools(
                        tools.map(function (tool) {
                            return {
                                tool_id: tool.tool_id,
                                profile_id: tool.profile_id,
                                profile_name: tool.profile_name,
                                interval_hours: tool.interval_hours,
                                accumulated_seconds: tool.accumulated_seconds,
                                accumulated_hours: tool.accumulated_hours,
                                percent_to_interval: tool.percent_to_interval,
                                is_overdue: tool.is_overdue,
                                selected_profile_id: ko.observable(tool.profile_id),
                            };
                        })
                    );
                    self.lastGeneratedAt(meta.generated_at || "");
                    self.errorText("");
                })
                .fail(function (xhr) {
                    console.log("[NozzleLifeTracker] status fetch failed", xhr);
                    self.errorText("Failed to load Phase 1 status.");
                });
        };

        self.setToolProfile = function (tool, event) {
            var profileId = tool.selected_profile_id();
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










