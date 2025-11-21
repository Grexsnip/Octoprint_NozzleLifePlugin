# Nozzle Life Tracker – Product Requirements (PRD)

## 1\. Overview

Nozzle Life Tracker is a plugin for OctoPrint that records how long each printer nozzle has been used. Its aim is to give users visibility into nozzle usage, enabling proactive maintenance and better print quality.

## 2\. Problem Statement

Printer nozzles degrade over time — especially under abrasive materials — but most users rely on calendar‑time or guesswork to replace them. This leads to inconsistent results, print failures, or excess cost.  
We want to provide a tool that answers: “How many hours has this nozzle run — and should I swap it now?”

## 3\. Goals \& Non‑Goals

### Goals

* Track cumulative print time per nozzle.
* Provide a clear UI showing the active nozzle, its usage, status, and life remaining.
* Maintain an inventory of nozzles (active, spare, retired) with historical stats.
* Allow lifecycle operations: register new nozzles, switch active, retire old ones.
* Offer configurable thresholds for warning and critical usage.
* Persist data reliably across restarts, power loss, and OctoPrint upgrades.
* Provide export (CSV/JSON) of nozzle usage data.

### Non‑Goals (v1)

* Automatically detect physical nozzle swaps.
* Deep integration with slicer software or materials database.
* Large fleet/multi‑printer dashboard support.
* Complex wear models beyond simple hour counting or multipliers.

## 4\. Users \& Use Cases

### Primary User

Intermediate to advanced 3D printer owner/operator using OctoPrint.

### Key Use Cases

1. View current nozzle health.
2. Change nozzle.
3. Review inventory/history.
4. Configure thresholds.
5. Export data.

   ## 5. Functional Requirements  
   ### 5.1 Usage Tracking  
   - Track cumulative print time using OctoPrint events: job started/resumed → timer begins; paused/completed/failed/cancelled → timer ends.  
   - Track only “printing time”, not idle or warming time.  
   - For each nozzle entry, store:  
    - `id` (internal UUID)  
    - `name` (e.g., “0.4 Brass #1”)  
    - `diameter\_mm`  
    - `material` (e.g., Brass, Hardened Steel, Ruby)  
    - `status` (Active / Spare / Retired)  
    - `installed\_date`  
    - `retired\_date` (optional)  
    - `total\_print\_time\_seconds`  
    - `jobs\_printed`  
    - `last\_used\_date`  
    - `notes` (free text)  
    - `expected\_life\_hours` (optional, per nozzle override)  
   - If a print is interrupted or OctoPrint restarts mid-job, elapsed time up to that point must be captured and persisted.

   ### 5.2 Lifecycle Management  
   - UI to create/register new nozzle entries (name, diameter, material).  
   - Mark a nozzle as “Active” (only one active nozzle at a time in v1).  
   - Change active nozzle: user selects old (or confirms current) and selects the new one from inventory or creates it. Tracking stops on old, starts on new.  
   - Retire a nozzle: mark status as Retired, optionally add note; retired nozzles no longer accumulate time.

   ### 5.3 User Interface  
   #### Overview Panel  
   - Tab or sidebar panel titled “Nozzle Life”.  
   - Display current active nozzle with: name, diameter, material, total hours (formatted), jobs printed, last used date.  
   - Health indicator colour coded (green/yellow/red) based on thresholds.  
   - Usage bar: e.g., “12.4 h / 20 h (62 %)”.  
   - Quick action buttons: “Change nozzle”, “Edit nozzle”, “Retire nozzle”.

   #### Inventory / History View  
   - Table of all nozzles with columns: Name, Diameter, Material, Status, Total hours, Jobs, Installed date, Retired date.  
   - Filters: Status (All / Active / Spare / Retired), Diameter, Material.  
   - Clicking row opens detail view: full fields + notes + optionally timeline of usage.

   ### 5.4 Notifications \& Warnings  
   - Settings for global thresholds: Warning = X hours, Critical = Y hours.  
   - Optional per‐material or per‐nozzle overrides.  
   - When a nozzle crosses thresholds:  
     - Show badge/icon in overview panel.  
     - Optional modal/prompt when starting a print if nozzle is at or over critical threshold.  
   - Respect OctoPrint’s notification architecture where feasible.

   ### 5.5 Settings \& Configuration  
   - Plugin settings page with:  
     - Global warning \& critical hour values.  
     - Per‐material expected life multipliers (e.g., CF‐nylon might wear a brass nozzle faster).  
     - Checkbox: include/exclude failed or cancelled jobs from time counting (default: include).  
   - Import/Export:  
     - Export full nozzle database to JSON and CSV.  
     - Import from plugin‐generated JSON (validate format) to restore data.

   ### 5.6 Data Persistence  
   - Store nozzle data in OctoPrint plugin data directory.  
   - Must recover gracefully from OctoPrint restarts, system reboots, etc.  
   - Implementation may use:  
     - Write on job completion/failure/cancel event.  
     - Periodic snapshot during long prints (optional).  
     - On nozzle lifecycle change.  
   - Data integrity: avoid corruption when power loss occurs.

   ## 6. Non-Functional Requirements  
   - \*\*Compatibility\*\*: Must support the current stable version of OctoPrint (specify minimum at implementation). Python 3 only.  
   - \*\*Performance\*\*: Lightweight; no polling loops, only event‐driven.  
   - \*\*Usability\*\*: UI should adhere to OctoPrint UI/UX patterns. Mobile‐responsive where possible.  
   - \*\*Maintainability\*\*:  
     - Clean separation: tracking logic, OctoPrint event hooks, UI/JS, settings.  
     - Code should be unit‐testable, especially tracking core.  
     - Clear documentation in README.

   ## 7. Data Model \& Event Flow  
   ### Data Model  
   class Nozzle:
   id: UUID
   name: str
   diameter\_mm: float
   material: str
   status: Enum(Active, Spare, Retired)
   installed\_date: datetime
   retired\_date: Optional\[datetime]
   total\_print\_time\_seconds: int
   jobs\_printed: int
   last\_used\_date: Optional\[date]
   notes: str
   expected\_life\_hours: Optional\[float]

   class NozzleStore:
   nozzles: List\[Nozzle]
   active\_nozzle\_id: UUID
   methods: load(), save(), get\_active(), switch\_active(), retire\_nozzle(), create\_nozzle()

   ### Event Flow  
   1. Plugin startup → load existing data; ensure active nozzle present (create default if none).  
   2. On `PrintStarted` or `PrintResumed`: start timer for active nozzle.  
   3. On `PrintPaused` / `PrintDone` / `PrintFailed` / `PrintCancelled`: stop timer, add elapsed seconds to `total\_print\_time\_seconds`, increment `jobs\_printed` (configurable whether failures count), update `last\_used\_date`, save data.  
   4. On “Change Nozzle”: user triggers switch → plugin stops timing old, records installed\_date on new, sets new as active.  
   5. On “Retire Nozzle”: update status, record retired\_date, no further time accumulation.  
   6. On Settings change: update thresholds, etc.

   ## 8. Release Plan \& Build Order  
   ### Milestone 0 – Skeleton Plugin  
   - Create plugin metadata (`plugin.yaml`, setup.py), basic tab with placeholder UI.  
   \*\*Done when:\*\* plugin installs, loads, and displays placeholder tab.

   ### Milestone 1 – Core Tracking Engine (Single Default Nozzle)  
   - Implement Nozzle/NozzleStore data model and JSON persistence.  
   - Auto-create default nozzle on first run.  
   - Hook into OctoPrint job events to track print time for active nozzle.  
   - UI at minimum: show active nozzle name + hours used.  
   \*\*Done when:\*\* after a few jobs, hours accumulate and persist across restarts.

   ### Milestone 2 – Nozzle Lifecycle Management  
   - UI \& logic to: create new nozzle, mark active, change active, retire nozzle.  
   - Ensure active switch works properly.  
   \*\*Done when:\*\* multiple nozzles exist, you can switch active, only active gathers time.

   ### Milestone 3 – Inventory \& Detail UI  
   - Build inventory table with filters.  
   - Build detail view for each nozzle.  
   \*\*Done when:\*\* user can browse, filter, inspect all nozzles.

   ### Milestone 4 – Thresholds \& Warnings  
   - Settings UI for thresholds.  
   - Compute health status (green/yellow/red).  
   - Warnings in UI when thresholds crossed.  
   \*\*Done when:\*\* thresholds change status colour and warning logic works.

   ### Milestone 5 – Import/Export \& Documentation  
   - Export to CSV/JSON.  
   - Import from JSON (safe restore).  
   - Write README, usage guide, screenshots.  
   \*\*Done when:\*\* data export/import functional and documentation complete.

   ## 9. Future / Stretch Ideas  
   - Material-based wear multipliers (e.g., CF-nylon = 3× wear).  
   - Analytics charts – e.g., “Hours per job by nozzle” over time.  
   - REST API endpoints so external dashboards/Home Assistant can query nozzle status.  
   - Multi-tool/IDEX support – track nozzles per toolhead.  
   - Integration with filament tracking plugins (to attribute nozzle wear by material used).

   ---

   ## Revision History  
   | Date       | Version | Description                          |
   |------------|---------|--------------------------------------|
   | YYYY-MM-DD | 0.1     | Initial draft of PRD                 |
