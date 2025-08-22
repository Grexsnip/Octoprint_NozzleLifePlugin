$(function() {
    function NozzleLifeTrackerViewModel(parameters) {
        var self = this;
        console.log("[NLT] VM construct");
        self.loginStateViewModel = parameters[0];
        self.settingsViewModel   = parameters[1];

        // Sidebar observables
        self.nozzleName = ko.observable("Unknown");
        self.runtimeText = ko.observable("0h used");
        self.displayMode = ko.observable('runtime');
        self.statusColor = ko.observable("gray");
        self.progressPercent = ko.observable("0%");
        self.progressBarClass = ko.observable("progress-bar-success");
        // Option A: computed from nozzles (read-only; do not write to it)
        // We define nozzles first, then compute hasData from it.

        // Settings observables
        self.nozzles = ko.observableArray([]);
        self.hasData = ko.pureComputed(function () {
            var list = self.nozzles() || [];
            return list.length > 0;
        });
        self.currentNozzle  = ko.observable(null);
        self.displayModeSetting = ko.observable("circle");
        self.promptBeforePrint = ko.observable(false);

        // Update sidebar status
        self.updateStatus = function() {
            $.ajax({
                url: API_BASEURL + "plugin/nozzlelifetracker",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({ command: "get_status" }),
                contentType: "application/json"
            }).done(function(response) {
                const runtime = response.runtime || 0;
                const expected = response.expected || 1;
                const percentUsed = Math.min(100, (runtime / expected) * 100);

                self.nozzleName(response.nozzle_name);
                self.runtimeText(runtime.toFixed(2) + "h of " + expected.toFixed(2) + "h");
                self.displayMode(response.display_mode || "circle");

                if (percentUsed >= 100) {
                    self.statusColor("red");
                    self.progressBarClass("progress-bar-danger");
                } else if (percentUsed >= 90) {
                    self.statusColor("yellow");
                    self.progressBarClass("progress-bar-warning");
                } else {
                    self.statusColor("green");
                    self.progressBarClass("progress-bar-success");
                }

                self.progressPercent(percentUsed.toFixed(0) + "%");
            });
        };

        // Auto-refresh sidebar
        setInterval(self.updateStatus, 5 * 60 * 1000);
        self.updateStatus();

        // Settings logic
        /* self.loadSettings = function() {
            OctoPrint.settings.getPluginConfigData("nozzlelifetracker", function(data) {
                self.nozzles(Object.entries(data.nozzles || {}).map(([id, obj]) => {
                    obj.id = id;
                    return obj;
                }).sort((a, b) => a.retired - b.retired));  // Active first
                self.promptBeforePrint(data.prompt_before_print || false);
                self.displayModeSetting(data.display_mode || "circle");
            });
        }; */
        self.loadSettings = function() {
            // Read settings from the injected settingsViewModel
            var p = self.settingsViewModel.settings.plugins.nozzlelifetracker;
            var data = {
                nozzles: ko.unwrap(p.nozzles) || {},
                prompt_before_print: ko.unwrap(p.prompt_before_print),
                display_mode: ko.unwrap(p.display_mode) || "circle"
            };
            self.nozzles(
                Object.entries(data.nozzles).map(([id, obj]) => {
                    obj.id = id;
                    return obj;
                }).sort((a, b) => a.retired - b.retired) // active first
                );
            self.promptBeforePrint(!!data.prompt_before_print);
            self.displayModeSetting(data.display_mode);
        };

        self.setDefault = function(nozzle) {
            OctoPrint.settings.savePluginConfig("nozzlelifetracker", {
                default_nozzle_id: nozzle.id
            });
        };

        self.confirmRetire = function(nozzle) {
            if (confirm("Are you sure you want to retire this nozzle? This action cannot be undone.")) {
                OctoPrint.simpleApiCommand("nozzlelifetracker", "retire_nozzle", {
                    nozzle_id: nozzle.id
                }).done(self.loadSettings);
            }
        };

        self.onAllBound = function() {
            console.log("[NLT] onAllBound fired");
            
            // Try immediately (sidebar may already be there)
            bindTargetsOnce();// Bind exactly once, when the DOM and all VMs are ready
            
            // Bind when Settings dialog is shown (OctoPrint injects its DOM on open)
            $("#settings_dialog").on("shown.bs.modal", function () {
                bindTargetsOnce();
            });

            // As a belt-and-suspenders: observe for late-inserted nodes, then stop
            var mo = new MutationObserver(function () {
                bindTargetsOnce();
                var s = document.getElementById("settings_plugin_nozzlelifetracker_content");
                var b = document.getElementById("sidebar_plugin_nozzlelifetracker_content");
                if (s && ko.dataFor(s) && b && ko.dataFor(b)) {
                    mo.disconnect();
                }
            });
            mo.observe(document.body, { childList: true, subtree: true });

            // Also try once more after the current tick
            setTimeout(bindTargetsOnce, 0);
        };

        function bindTargetsOnce() {
            var nodes = [
                document.getElementById("settings_plugin_nozzlelifetracker_content"),
                document.getElementById("sidebar_plugin_nozzlelifetracker_content")
            ].filter(Boolean);

            var didBind = false;
            nodes.forEach(function (node) {
                if (node && !ko.dataFor(node)) {
                    ko.applyBindings(self, node);
                    didBind = true;
                }
            });
            if (didBind) {
                console.log("[NLT] manual bound (now)", {
                    settings: !!document.getElementById("settings_plugin_nozzlelifetracker_content"),
                    sidebar: !!document.getElementById("sidebar_plugin_nozzlelifetracker_content")
                });
            }
        };

        self.exportLog = function() {
            window.location.href = API_BASEURL + "plugin/nozzlelifetracker?command=export_log_csv";
        };

        self.onBeforeBinding = function() {
            console.log("[NLT] onBeforeBinding start");
            var s = self.settingsViewModel && self.settingsViewModel.settings;
            var p = s && s.plugins && s.plugins.nozzlelifetracker;
            if (!p) {
                console.warn("[NLT] settingsViewModel.plugins.nozzlelifetracker is missing");
                // keep safe defaults so KO binding still succeeds
                self.displayMode("runtime");
                self.nozzles([]);
                self.currentNozzle(null);
                console.log("[NLT] onBeforeBinding end (missing settings)");
                return;
            }

            var nozzleMap = ko.unwrap(p.nozzles) ||{};
            var arr = Object.entries(nozzleMap).map(function([id,obj]) {
                obj.id = id;
                return obj;
            }).sort(function(a, b) { return a.retired - b.retired; });
            
            // Use safe fallbacks in case a key is undefined on first run
            self.displayMode(ko.unwrap(p.display_mode) || "runtime" );
            self.nozzles(arr);
            self.currentNozzle( ko.unwrap(p.current_nozzle) || null );
            console.log("[NLT] onBeforeBinding end", {
                displayMode: self.displayMode(),
                nozzles_len: self.nozzles().length,
                currentNozzle: self.currentNozzle()
            });
        };
    }

    if (window.__nlt_vm_pushed) {
        console.warn("[NozzleLifeTracker] ViewModel already registered, skipping second push.");
    } else {
        window.__nlt_vm_pushed = true;
    
        OCTOPRINT_VIEWMODELS.push({
            name: "nozzlelifetracker",
            construct: NozzleLifeTrackerViewModel,
            dependencies: ["loginStateViewModel", "settingsViewModel"],
            elements: []
        });
        console.log("[NLT] VM registered");
    }
});















