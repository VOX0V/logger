# Changelog

## 0.3.41 — Pattern filter, yesterday, CLEAR only, logbook in dark mode

- **Import filters**: new `only_matching` (keeps only the rows whose whole value matches a pattern, a regular expression, not case sensitive; for example `only_matching: '\d{4}'` on a flight number keeps the 4-digit numbers). `not_after` now accepts `yesterday` as well as `today`. A whole number read as 1234.0 in an Excel file is now read as 1234 by the filters.
- **Emptying a database** (raw data, work data, locations, aircraft types, entities): typing CLEAR is enough, the password is no longer asked again.
- **Global profile “times” shipped with the application**: the flight time is no longer copied into every multi engine column (`time_me_*`); these take only their raw value, so the conversion profile of the company fills them from the role. The single engine columns are unchanged.
- **Dark mode**: the logbook page was unreadable (dark text on dark cells); the logbook table is now shown in a softened dark version of its own colours. Printing is not affected.
- `VERSION` is now 0.3.41.

## 0.3.40 — Work DB columns computed in any direction, dark mode

- **Work DB conversion**: a rule can now use `w_<column>` of any other work column, placed before or after it in the Work DB settings (for example year, month and day from the date, or an average speed from a flight time placed later). A column used by a rule is computed first, whatever its place. When two columns depend on each other, the rule that closes the loop is left out for that row and the next rules are tried. The “can only use a column placed before it” error no longer exists; a `w_` name that is not a column of the Work DB settings is still refused.
- **Dark mode**: a button at the top right of every page switches between the light and a soft dark theme; the choice is kept in the browser. Colours written directly inside some pages (charts, map) may stay light.
- `VERSION` is now 0.3.40.

## 0.3.39 — Filter “only_containing”

- **New filter** `only_containing` in the `filters` list of an import profile: keeps only the rows whose value in the column contains one of the texts (not case sensitive), for example `only_containing: [816505]` on `crew_list`. A number is read as a text.
- `VERSION` is now 0.3.39.

## 0.3.38 — Row filters in import profiles, YAML editor for import profiles

- **Filters** (optional `filters` list in `<id>_import.yml`): each filter names a header of the file (`column`) and one rule: `only` (keep only the rows whose value is in the list, not case sensitive), `exclude` (leave out the rows whose value contains one of the texts) or `not_after: today` (leave out the rows whose date is later than today). A row must pass every filter. Rows left out are not added to the raw database. If a filter column is not in the file, or a date cannot be read, the import stops with a message.
- **Import profile page** (`/profiles/import/<id>/edit` and `/new`): now a YAML text editor, like the global and conversion profiles. The identifier is typed only when creating. Renaming an import profile from its editor is no longer possible.
- **Sheet** removed from import profiles: an Excel file is read from the sheet named “raw”, otherwise from the active sheet. A profile that still contains `sheet:` is refused.
- `VERSION` is now 0.3.38.

## 0.3.37 — Entities are the single source of the columns

- **Entities**: a field (unique technical name) and a label (text shown). The Excel file is now: position, label, group, name, field, data type, visible, editable, nullable, delete (the old headers “entity” and “display name” are still read; the last four columns are ignored). Renaming a label shows everywhere at once. Renaming a field is followed by the databases, the roles and all the YAML files; a field still used by a database or a role cannot be deleted.
- **One mechanism for the four databases** (Raw, Work, Location, Aircraft): their columns can only be entities, chosen on one page (`Data > … DB settings`: present, visible, editable, nullable), the same for all accounts. The type and the label come from the entity. First use: Raw and Work get every entity, Location and Aircraft get their key columns. Clearing the data no longer deletes the structure.
- **Roles** (`defaults/roles.yml`, page Data > Roles): the names the program knows (year, leg_time, ifr…) are bound to one field each; the code reads the work data through them, so it no longer depends on field names. Location and Aircraft key columns are roles too (`location.icao_code`…).
- The shipped global profiles, `logbook_layout.yml` and `breakdown.yml` now cite fields. The per-account `<user>_data.yml` and `<user>_logbook.yml`, `work_structure.yml`, `default-userdb.yml`, the free-form Work DB settings page and the Locations / Aircraft structure pages are removed. Work data and raw data tables must be rebuilt (clear the data, convert again).
- `VERSION` is now 0.3.37.

## 0.3.36 — Global profiles as YAML files, cleanup

- **Global profiles** (Data > Conversion profiles): each global profile is a YAML file `<id>_global.yml`. **Create** opens the YAML text editor, **Import** accepts a `.yml` file only (the identifier comes from the file name; refused if it already exists or is invalid), and each file has **Edit**, **Export** and **Delete**. The rule-by-rule screens of 0.3.35 are removed. A deleted profile stays deleted (marker `.globals_ready`).
- **Cleanup**: removed the old Converter page (`/converter`, rule selection, rule editor), the aircraft form (`/converter/aircrafts/new`, `/edit`, `/delete`), their templates and tests, and the functions that became unused (`get_rule`, `rule_id_from_name`, `build_rule`, `rule_missing_columns`, `save_selection`, `save_logbook_layout`, `backup_sqlite`) with their imports. Kept because tests use them: `rounding_to_text`, `rounding_from_text`, `load_selection`, `save_aircraft`.
- `VERSION` is now 0.3.36.

## 0.3.35 — Global profiles, Work DB settings

- **Global profiles**: `work_db.yml` is gone. Its rules are split into six global profiles, one file each in `appdata/workdb/<id>_global.yml` (shipped in `defaults/global`): General (skip_rows and the list of expressions), Dates, Aircraft, Crew, Routes, Times. The first time, an edited `work_db.yml` of the account folder is split the same way and kept as `work_db.yml.old`. A column that appears in several profiles gets the rules of all of them, in that order.
- **Conversion profiles** page: the global profiles are listed under the profiles of the companies; each one opens a page with **Add rule**, **Edit rule**, **Export rule**, **Delete rule** and **Export profile**. Saving a rule keeps the comment header of the file, not the comments written between the rules. The "Global rules (work_db.yml)" and "Data" buttons and the editor entry `workdb` are removed.
- **Renamed**: "Work db structure" is now **Work DB settings**, "Raw db structure" is **Raw DB settings**.
- **Raw DB settings** now has the look of the Work DB settings page (grid with ✓ / ✗ cells, filter).
- `VERSION` is now 0.3.35.
- **Cleanup**: removed the templates `import_done.html`, `import_form.html`, `locations.html`, the functions and constants that nothing called (`CATEGORY_ORDER`, `column_labels`, `system_columns`, `_links`, `_reposition`, `list_users`, `check_entities`, `save_settings`, `save_pilot_name`, `active_rules`, `find_aircraft`, `list_aircrafts`, `get_aircraft`, `delete_aircraft`) and the unused imports. Kept on purpose: the old Converter page and the aircraft form, which the tests still use.

## 0.3.34 — Data page reorganised

- **Data page** (hub/data): sections reorganised: User data (Import data with Import profiles; Raw data; Convert data; Work data), Logbook, Breakdown, Databases (Entities, Raw DB, Work DB) and App Data (Locations, Aircrafts).
- **Convert Data**: the former "Actualise data" button is renamed and shown in green.
- **Clear entities**: new button (administrators) that deletes all the entities, after typing CLEAR. The entities list is now filled from the former file only once (first use), so after clearing it stays empty.
- The "Edit import rules" and "Edit conversion rules" buttons (old system) are removed from the page.
- `VERSION` is now 0.3.34.

## 0.3.33 — Import and conversion profiles, work db structure

- **Import profiles** (Data > Import profiles, administrators): create, edit, rename, delete and export the profiles. The editor is a grid: header of the file, then the entity chosen in the entity list. The first time, the shipped profiles are copied to `appdata/importer`; from then on only the profiles of that folder are used, so all of them can be edited or deleted. Renaming a profile renames its conversion file too.
- **Import**: every imported row now gets the name of its import profile in `misc_import_profile` (when that entity exists; the column is created if needed). `crew_operator` is no longer filled by the import.
- **Work db structure** (Data > Work db structure, administrators, the same for all accounts): the columns of the work data, their order (drag and drop), their type (a list for each column), visible / editable / nullable. The first time it is filled from the edited `work_db.yml` (old format) or from `defaults/work_structure.yml`.
- **Conversion rules**: `work_db.yml` now only holds the global rules: `skip_rows`, then one key per work column (its name) with its list of rules (the old form `<number>_<name>` with `type` / `rules` is still read; the number and type are no longer used). Each import profile can have its own file `<id>_convert.yml` (Data > Conversion profiles: new, edit, rename, delete, export): its rules are tried before the global ones and its `skip_rows` are added to them. A column can use `w_<column>` only for a column placed before it in the structure.
- `VERSION` is now 0.3.33.

## 0.3.32 — Clearing the work data

- **Clear work data** now deletes the columns of the work data as well as its rows, like clearing the raw data. The columns are created again from `work_db.yml` at the next refresh or login.

## 0.3.31 — Structure of the aircraft and location databases

- **Aircraft** and **Locations** (administrators): a *Structure* button opens a page where the order of the columns is changed by drag and drop and where columns are added. An added column is an entity of the entity list (group `aircraft` or `location`, without the entities that describe a flight); the key columns that the application reads cannot be removed. Removing an added column deletes its data.
- The added columns appear in the grid, in the add panel, in the edit form and in the Excel export; they are read by `aircraft(type, field)` and `location(code, field)` with the entity name without its group (`timezone` for `location_timezone`). The Excel import still fills the key columns only.

## 0.3.30 — Locations, import fixes, raw data in text

- **Airports renamed Locations**: the database (`location.db`, created from `defaults/locations.xlsx`), the Data > Locations page and the `/locations` URLs, the work data function `location(code, field)` (`airport()` still works), the audit table (`known_location`) and the world map. `airport.db` is no longer used and can be deleted.
- **Entities import (Excel)**: the header row is found by itself (a title block or empty rows above it are fine) and, after an import, the import profiles that no longer work (unknown entity) are listed.
- **Raw data**: the columns created by the imports and by Raw db structure are always text; the work data converts to the right type.
- **Work data functions**: `date_of(x)` and month names in dates (“Sep 11 2026”, “11 September 2026”), `time_24h(x)` (“5:10AM” -> 05:10), `strip_chars(text, chars)` (“# 0767” -> 0767).
- **Entity model**: the shipped entity list is now your model (crew_pilot_name, crew_copilot_name, crew_operator, time_flight_hhmm, ...); the shipped import profiles and work_db.yml use these names, as do the employer fill of the import and the merge.

## 0.3.29 — Entities page, raw and work db structure

- **Entities** (Data > Entities, administrators): the list now lives in `appdata/db/entities.db` instead of `entities.yml` (first use: filled from the former `entities.yml`). Columns position, group, name, entity, data type, display name. Cells are editable, rows can be added and deleted, and a row dragged by its handle takes the number of the place where it is dropped while the following ones move down. Excel import (replaces the whole list) and export. The import profiles and the work data definition read this list.
- **Raw db structure** and **Work db structure** (Data hub): tick which entities are present in your raw / work database and which columns are visible, editable and nullable. Unticking a present entity removes its column and its data (confirmation). Columns that are not entities are listed after them and can be removed the same way. Column order follows the entity list.
- **Removed**: *Edit entities* (YAML editor) in the Data hub and in the Configuration (YAML) list.

## 0.3.28 — Entities in the work db, integers in the logbook, airports without coordinates

- **entities.yml**: the administrator's version (display names `arrival time utc`, `cross country …`).
- **Import**: the display name and the order of the raw db columns follow `entities.yml` at every import (the type of an existing column does not change).
- **work_db.yml** (default file) reads the raw columns by their entity names. A raw column that no import has created is empty, with no “Unknown name” warning.
- **Logbook**: new column option `decimals` in `logbook_layout.yml` (0 to 3, 1 by default); `decimals: 0` on IFR approaches and landings (page, totals, PDF).
- **Airports**: latitude and longitude may stay empty (both or none); existing tables are rebuilt at start-up. Such airports are kept for the audit, without day/night, distance or map line.
- **Edit import rules** opens the list of the import profiles.
- **Reports and Excel export** read the work db column names (`departure_code`, `arrival_code`, `pilot`).

## 0.3.27 — Entities: new import into the raw database

- **entities.yml** (`importer/`): the list of the entities (name `group_name`, group, type, display name), from `entities.xlsx`. Editable by administrators (Data > Import data > Edit entities). `larrival_light` is spelled `arrival_light`.
- **Import profiles**: one line per column, `header: entity`. A header with no line is not imported. The three shipped profiles are converted; profiles in the old `groups` format are refused with an explanation.
- **Raw database**: no pre-created column any more (the `employer` column is gone: the import fills `crew_company` with the profile name when it is empty). The import creates the columns it needs, with name, type and order taken from the entities.
- **Clear data** deletes the rows, the columns and resets the numbering.
- **Raw data — structure** is no longer an editable YAML file: the structure comes from the imports.
- `merge.py` uses the entity names. The work data conversion (`work_db.yml`, conversion rules), the audit, the graphs, the logbook and the reports still read the old raw names: they are to be aligned.

## 0.3.26 — Settings pages removed, Logbook and Breakdown sections in the Data hub

- **Removed**: the Settings card of the account page and its pages (Logbook settings, Breakdown settings, Raw data columns, Converter settings) with their routes and forms. Only a **Configuration (YAML)** button stays on the account page; it lists all the YAML files.
- **Data hub**: new *Logbook* (**Configure logbook** → `logbook_layout.yml`) and *Breakdown* (**Configure breakdown** → `breakdown.yml`) sections between *User data* and *App data*.
- **YAML editor**: `/config` lists the files; `/config?file=…` shows only the chosen file. New administrator entry **Converter — settings** (`settings.yml`: night margins, Transport Canada rounding), with validation.
- **World map**: local flights (same departure and arrival) no longer set the colour scale; the line colour follows a logarithmic scale of the route frequency.
- **Default YAML files** follow the new work db (`date`, `aircraft_type`, `pic`, `ifr_approach`): `work_db.yml`, `logbook_layout.yml`, `audit/`, `graph/10_hours.yml`.
- Tests of the removed settings pages are removed.

## 0.3.25 — Edit mode on Breakdown, simpler Data hub, one YAML file per editor

- **Breakdown**: the types are shown as plain text; **Edit breakdown** turns them into lists, **Save** / **Cancel** end the edit.
- **Data hub**: new *Import data* row above *Raw data* (**Import**, **Edit import rules** for administrators). The *Converter* row has **Edit conversion rules** (opens `work_db.yml`); the old *Settings* and *YML WORK DB* buttons are gone.
- **YAML editor**: the list of files is removed; the page only shows the file opened by the button.
- **Work data grid**: no more computed year / month / day columns drawn from `date`; the grid shows the work db columns as they are (date, year, month, day).
- `yamledit.py`: `check_options` moved before `ADMIN_FILES` (start-up crash fixed).

## 0.3.24 — Graph tab, editable aircraft lists, grids without appearance settings

- **Graph tab** (next to World map): charts defined in YAML (`graph/*.yml`, merged in file name order; copies edited in the web interface in `appdata/graph/`). Each chart: `type` (bar / line / area), `group_by` (year, month, year_month or any column), `measure` (one or several, expressions on the work data such as `num(flight_time)`), `cumulative` (progression), `stack_by`, `stacked`, `horizontal`, `where`, `limit`. Shipped charts: cumulative career hours per month, hours per month / year / calendar month, day and night, single and multi-engine, per aircraft type, per airport. Chart.js is shipped in `static/vendor/chartjs` (no CDN). Administrators edit the files from the Graph page.
- **Aircraft table**: the choice lists (category, engines, engine type, crew and the new **landing gear**) are now in `aircraft_options.yml`, edited by the administrators (Aircraft page > Edit lists): add, rename or remove values (new ones shipped: `glider`, engines `none`, landing gear wheels / floats / skis / amphibious). A value still used by an aircraft type cannot be removed. The `CHECK` constraints of the database are removed (the table is rebuilt once on startup) and `landing_gear` is available in `work_db.yml`: `aircraft(type, "landing_gear")`. Excel import / export of the aircraft table has the new column.
- **Grids** (raw, work, airports, aircraft): no appearance setting any more. The `<user>_data_view.yml` and `<user>_logbook_view.yml` files (width, alignment, frozen column, label) and their editor entries are removed; columns are as narrow as their content (`fitData`, measured again for each page) and titled with the column display name. The logbook page, its PDF and `logbook_layout.yml` are unchanged.

## 0.3.23 — One import file per employer, audit rules in YAML, grid filters and sorting fixed

- **Import**: back to one file per employer, `importer/<id>_import.yml` (`default`, `creebec`, `jazz`), each with its own columns (`header` of the airline file -> RAW `column`) and its own `ignored` list; no shared rule. A header can be a list (Creebec accepts `pic` and `pic_name`). `import.yml` is removed. Each file has its own button entry in the YAML editor (Data > YML IMPORT, then pick the file); edited copies are kept in `appdata/importer/`.
- **Audit**: the checks are now YAML files in `audit/` (`00_common`, `10_dates`, `20_times`, `30_aircraft`, `40_airports`, `50_crew`, `60_remarks`), merged in file name order, using the expression language of `work_db.yml` plus a few functions (`valid_date`, `future_date`, `num`, `matches`, `length`, `has_stray_spaces`, `exercise_issues`, `known_airport`, `known_aircraft`). Rules over several rows are `group_rules` (`one_to_many`, `spellings`). Administrators edit each file from the Audit page (copies in `appdata/audit/`, a new file there is added). A broken rule or an unknown column name is reported on the Audit page as “Audit rule problem” instead of being silently ignored. The MTOW check stays in the code. The Dockerfile copies `audit/`.
- **Grids (Tabulator)**: filters and sorting never reached the server (Tabulator 6.3 sends `sort` and `filter`, the page read `sorters` and `filters`). Fixed. Sorting is now alphabetical ignoring case, numeric-looking values in numeric order, blanks last.

## 0.3.22 — World map on a globe, no API key

- CARTO now requires an API key on its raster tiles (the map showed "API KEY REQUIRED"). The World map now uses **MapLibre GL** (shipped in `static/vendor/maplibre`, CSP build) with the keyless **OpenFreeMap** dark vector style, drawn on a **globe** (button *Flat map* / *Globe* in the panel). Leaflet is removed.
- Content security policy: `connect-src` and `img-src` allow `https://tiles.openfreemap.org` (style, tiles, fonts); images also allow `blob:`. Without internet access the routes and airports are still drawn on a plain globe, without airport codes.

## 0.3.21 — World map

- New **World map** tab: every airport of the work data and the legs flown between them, drawn as great circles on a dark map (Leaflet, shipped in `static/vendor/leaflet`). Line colour and thickness follow how often a route was flown (blue = once, orange = most flown); airport dots grow with the number of movements; hover for details, airport codes appear when zoomed in; year filter and totals (airports, routes, legs, nautical miles).
- It reads `departure_code`, `arrival_code` and the four latitude / longitude columns of the work data (`year` and the airport names are used when present).
- The map tiles come from CARTO / OpenStreetMap: the content security policy now allows images from `*.basemaps.cartocdn.com`. Without internet access the routes and airports are still drawn, on a plain background.

## 0.3.20 — Import YAML editor, logbook mapped to the work data

- **Data page**: new administrator button **YML IMPORT** (Raw data row) opens the web YAML editor on `importer/import.yml` (check without saving, save, backup and *Restore*). The edited copy is kept in `appdata/importer/import.yml` and wins over the shipped file. The file is checked on save (profiles, duplicate columns, unknown profile names, data types).
- The profile drop-down of the Data page import panel no longer offers “Default (current rules)”: a profile is required and `default` is listed like the others.
- **Logbook**: `defaults/logbook_layout.yml` now points to the work data columns of `work_db.yml` (`type`, `pilot`, `departure_code`, `arrival_code`, `single_engine_solo_*`, `ifr_app`).
- `work_db.yml`: new raw names, date fallback on `dep_time_utc`, registration formatted with the new `registration_format()` function.

## 0.3.19 — Single import file (importer/import.yml), no default import

- **One import file**: `logger/importer/import.yml` replaces the `*_import.yml` files and `import_profiles/`. Structure: groups -> RAW column -> header of the airline file per profile (`default`, `creebec`, `jazz`), plus the headers deliberately `ignored`. Air Canada is dropped.
- **No more default import rules**: the `import_rules` of the columns (settings, `userdb.yml`, default files) and the Excel logbook import are removed. The Import page requires a profile (`default` = file whose headers are the RAW column names). Missing RAW columns are created from the profile.
- The default RAW schema (`defaults/default-userdb.yml`) now holds only the system columns; the unused root copies `default-userdb.yml` / `default-configuration.yml` are removed.
- **Tests disabled, not deleted**: `tests/conftest.py` skips every test until the new structure is working.

## 0.3.18 — Work data defined by a YAML file

- New file **`logger/defaults/work_db.yml`**: the work data table is now created from it. Each key `<position>_<name>` (`1_year`, `2_month`, `3_day`) is a column, with its `type` and a list of `rules`; for each row the first rule whose `when` is true (no `when` = always) and whose `value` is not empty gives the value. This version starts again from three columns: **year**, **month**, **day** (copied from the raw `year` / `month` / `day`, else extracted from `departure_local`). The other columns will be added one at a time.
- **Expressions** in `when` / `value` are read by a small whitelisted interpreter (no `eval`): raw column names, `pilot_name`, numbers, text, `and` / `or` / `not`, `== != < <= > >=`, `+ - * /` and the functions `is_blank`, `year_of`, `month_of`, `day_of`, `is_zero_time`, `has_word`. Example: `arrival != departure and leg_time > 0.5`.
- **`skip_rows`** (same file): rows to leave out of the work data. The two former hard-coded behaviours (0:00 block time; deadhead or not in the crew list) are now two rules of the file.
- The work data columns are no longer written in the code: the account configuration (`<user>_logbook.yml`) is regenerated from `work_db.yml` at login and at each *Actualise data*; columns that are not in the file are removed from the work data table.
- **Data page**: new administrator button **YML WORK DB** (Work data row, temporary name) opens the web YAML editor on this file (check without saving, save, backup and *Restore*). The edited copy is kept in `appdata/workdb/work_db.yml` and wins over the file shipped with the app.
- The work data grid, its export and the logbook page work with real `year` / `month` / `day` columns when the table has no `date` column any more.
- The conversion profiles (`converter/*_convert.yml`) and the converter rule catalog are no longer used by *Actualise data*; they stay in place until each column has been moved to `work_db.yml`. The `employer` column is no longer added to the work data (still in the raw data).
- `engine.profile_rules` is kept as an unused import because the test fixtures save and restore it.
- Pages that read other work data columns (breakdown, reports, audit, PDF export, the rest of the logbook layout) show empty values for the columns that do not exist yet. Existing tests about the former conversion are not adapted; no new test.

## 0.3.17 — New Aircraft and Airports tables

- **Aircraft** table: `display` (name shown in the logbook), `designator` (unique key found in the raw data), `maker`, `model`, `category`, `engines`, `engine type`, `crew`, `MTOW (lb)` and `MTOW (kg)`. Several designators can share one display name (DH1 and DH3 give DHC8, CR2 and CR9 give CRJ, BCS1 and BCS3 give A220) while keeping their own rows. The conversion writes the display name in the logbook; breakdown, reports and the manual entry list the display names. The `type` column is gone.
- Both MTOW values are official data entered by hand (an empty one is calculated from the other); the audit reports an aircraft whose two values differ by more than 1 %.
- **Airports** table: `display` (shown in the logbook, the ICAO code when empty), `ICAO`, `IATA`, `company code` (identifier of a third-party company, e.g. MHS), `name`, `country`, `latitude`, `longitude`. A code is looked up by IATA, then ICAO, then company code. `timezone`, `elevation` and `notes` are gone (the day/night calculation only needs the UTC time and the position).
- The default data come from the two Excel files supplied by the user; exports use the same headers, so an export can be imported back. A reference table that still has the previous layout is rebuilt from the default files.
- The audit accepts any code of the Airports table (ICAO, IATA, company code, display) and any designator or display name of the Aircraft table.
- Existing tests adapted to the new column names; no new test.

## 0.3.16 — Editable tables, audit on the global tables, no more groups

- **Audit**: the aircraft types are checked against the global **Aircraft** table (the hard-coded list is gone), like the airports were already checked against the **Airports** table.
- **Raw data, Work data, Airports and Aircraft** are all the same kind of Tabulator page: edit a cell, **Add row** (small form), tick rows then **Delete selected**. Shared script `static/grid.js`; new routes `/data/add`, `/data/delete`, `/logbook-db/add`, `/logbook-db/delete`, and `/converter/{airports,aircrafts}/{rows,cell,add,delete}`.
- The **group** of the columns (raw and work databases) and of the converter rules is removed: nothing used it. Only the technical columns keep a flag (`system: true`; files that still say `group: system` keep working). Other `group` keys in existing YAML files are ignored.
- The buttons of the Data page have the same size and are aligned in columns.
- English labels for the aircraft categories, engines and engine types.
- One existing test adapted (a column no longer has a group); no new test.

## 0.3.15 — Employer column, profile detection, Jazz conversion

- New **employer** column in the raw data and the work data (added to existing accounts at login). On import an empty employer is filled with the name of the import profile (Air Canada, Air Creebec, Jazz Aviation) or `undefined` when no profile is used; it can be edited afterwards. Every conversion profile copies it to the work data, so it can be used to filter flights later. Rows already imported keep an empty employer (re-import them to fill it).
- Importing from the Data page takes **one file at a time**, and the **import profile is suggested as soon as the file is chosen**, from its column headers (pre-selected, still changeable; "Profile not recognized." when nothing matches). New route `POST /import/detect`.
- **Jazz Aviation** profiles are no longer placeholders: the conversion is rebuilt from the rules that used to be the default conversion (UTC milliseconds, day/night split with ephem, crew list, ICAO codes) and the import profile lists the standard Jazz headers. The Default profile is still a plain copy; Air Canada and Air Creebec are unchanged apart from the employer copy.
- No new test.

## 0.3.14 — One Data page

- `/hub/data` now does everything in place: **Raw data**, **Work data**, **Airports** and **Aircraft** are labels followed by their own buttons (Import data / Edit data / Export data / Clear data; Work data has *Actualise data* instead of Import). The separate Import button is gone; importing is done with a panel on the Data page and the result comes back to it.
- *Edit data* opens the Tabulator view; the Raw data grid is now editable cell by cell (new route `POST /data/cell`, same as the Work data grid). *Export data* gives an Excel file.
- *Clear data* needs the word `CLEAR` typed (asked in the browser and checked again by the server). New routes: `/logbook-db/clear`, `/converter/airports/clear`, `/converter/aircrafts/clear`.
- **Converter** is a label with a *Settings* button (administrators): the conversion files (`<profile>_convert.yml`) are edited in the YAML editor. Saves go to `appdata/converter/` (writable, survives upgrades) and win over the file shipped with the app.
- English in the touched code: audit targets (`raw-data:all-rows`, ...), export file names (`<user>_raw_data`, `<user>_work_data`, `airports.xlsx`), messages.
- Existing tests adapted (Data page labels, typed confirmation); no new test.

## 0.3.13 — English interface

- All user-visible texts are now in English: pages, buttons, messages, errors, audit labels, converter rule labels and groups, dates in words (June 5, 2013), month names of the monthly report, default YAML comments. Code comments, documents and start-up (operator) messages are not translated yet.
- The bundled converter rules have English names and groups. A catalog migration (`1.8.0`) translates the labels of an existing catalog when they still equal the former French defaults (`defaults/converter_rules_legacy_fr.yml`).
- Template filter `fr_date` renamed `long_date`; severity labels `ERREUR` / `ANOMALIE` became `ERROR` / `ANOMALY`; quotation marks are typographic English ones.
- Existing tests updated to the English texts.

## 0.3.12 — Tests adapted to conversion by profile

- Existing tests that ticked converter rules now set the rules of the `default` profile through a test helper (`use_rules` in `tests/test_app.py`, restored after each test by an autouse fixture in `tests/conftest.py`); the default-format import test uses the `aircanada` profile. No product change.

## 0.3.11 — Every row has an import profile

- Column `import_profile` of the raw database is now mandatory: the default import writes `default` (existing empty values become `default`).
- Conversion is decided row by row from `import_profile`: `converter/<profile>_convert.yml`, or `converter/default_convert.yml` (plain copy) for `default` and for profiles without a conversion file. The ticked converter rules are no longer used by the conversion.
- New profiles `aircanada` (the app's historical import rules and default-ticked converter rules as starting point) and `jazz` (placeholders: basic columns, plain copy), each with `importer/<id>_import.yml` and `converter/<id>_convert.yml`.

## 0.3.10 — Default conversion profile copies everything

- `converter/default_convert.yml` now copies, cell for cell and without any change, every column of B that has an A column of the same name (date from year / month / day and `aircraft_type` from `type` aside). Still used only when no converter rule is ticked.

## 0.3.9 — Day/night from the sun for Air Creebec

- Air Creebec day/night time no longer depends on `ldg_day` / `ldg_night`: it uses the sun position (ephem) at the arrival airport, taking `date` + `arr_time` as UTC (`dep_time` is used to pass midnight).
- The `day_night` transform accepts an optional date column (and an optional UTC departure time column) when the UTC arrival is a time of day only.
- Fix: the default conversion profile is used only when no converter rule is ticked.

## 0.3.8 — Conversion profiles

- **Conversion profiles**: new `logger/converter/` folder, one `<company>_convert.yml` file per airline matching its import profile (`creebec_convert.yml` first), using the same rule format as the converter catalog.
- Raw database A gets an `import_profile` column filled at import (empty = default rules). During conversion, rows with a conversion profile use its rules instead of the ticked rules.
- New transforms: `date_dmy`, `last_first_name`, `time_by_landing` (optional Transport Canada rounding), `skip_blank`.
- Air Creebec times use the Transport Canada rounding table.
- `converter/default_convert.yml`: plain copy of the basic columns of A into B used for rows without a conversion profile only when no converter rule is ticked (ticked rules always win).

## 0.3.7 — Import profiles

- **Import profiles**: new `logger/importer/` folder (shared by all accounts) with one `<company>_import.yml` file per airline (`creebec_import.yml` first). A profile maps the headers of the airline file to database columns; values are imported untouched (raw data).
- **Import page**: new "Import profile" drop-down. "Default" keeps the current import rules (`import_rules` in `userdb.yml`); a profile replaces them entirely for that import.
- **Missing columns** needed by a profile are added automatically to the user's database (names taken from the file headers).

## 0.3.4 — Audit affiné et ajout d'un vol à la main

- **Audit — lignes vides** : une ligne dont la remarque est uniquement « vide » ou « empty » est ignorée par tous les tests (elle sert à créer des espaces dans le logbook). Une telle ligne sans date valide est signalée (« Ligne vide sans date »), car elle pourrait se retrouver n'importe où.
- **Audit — aérodromes** : un code qui n'a ni 3 ni 4 caractères (nom de lieu, etc.) n'est plus testé. Un code à 3 caractères est une anomalie (code OACI attendu, ex. KBNA) ; un code à 4 caractères doit exister dans la table Aéroports, sinon anomalie « Aérodrome inconnu ».
- **Audit — simulateur** : pour le type SIM, plus de « Heures sans catégorie ». Anomalie s'il n'y a ni temps FTD ni instruction, et anomalie s'il y a du temps ailleurs que FTD ou instruction.
- **Ajouter un vol** : nouveau bouton dans l'en-tête, à côté du nom. Le formulaire reprend les colonnes du logbook (date, type, immatriculation, PIC, copilote, départ, arrivée, remarques, heures mono/multi/instruments/cross-country/instruction, atterrissages). Le vol est ajouté aux données brutes (import_source = « Saisie manuelle »), sans fusion avec une ligne existante ; il apparaît dans le Logbook après « Actualiser ».

## 0.3.3 — Exports regroupés dans Export, nouveau rapport mensuel

- **Export > PDF** (nouvelle page) : Logbook d'une année précise (menu des années), Logbook complet, et Breakdown. Les boutons PDF ont disparu de la page Logbook et de la page Breakdown.
- **Export** regroupe maintenant tout ce que le logiciel génère : PDF, Reports, export vers le logbook Excel, Raw data et Work data (Excel, CSV), sauvegarde de Work data, sauvegarde du dossier utilisateur, et pour les administrateurs les exports Excel des Types d'appareils et des Aéroports. Les boutons d'export ont été retirés des pages Données brutes, Données converties, Types d'appareils et Aéroports.
- **Reports** : au lieu de générer tous les rapports du CRJ, on choisit le **mois, l'année et le type d'appareil** (ou « Tous les types ») et on génère le rapport mensuel de ces vols. Colonnes : DATE, FLIGHT/REMARK, ORG, DEST, TIME, LDG, D/N, PIC, COPI ; lignes TOTAL (mois), Total de l'année et Total to date, calculés pour le type choisi seulement. S'il n'y a aucun vol, un message s'affiche. Les anciennes routes (liste de tous les rapports CRJ, ZIP) sont supprimées.

## 0.3.2 — Navigation simplifiée

- **En-tête** : Logbook · Breakdown · Data · Export · Audit (Audit reste un bouton à part pour l'instant).
- **Data** (nouvelle page d'accueil) : Import, Raw data, Convertisseur, Work data, et pour les administrateurs Types d'appareils et Aéroports.
- **Export** (nouvelle page d'accueil) : Reports, export vers le logbook Excel, sauvegarde du dossier utilisateur.
- **Mon compte** : tous les réglages au même endroit (logbook, Breakdown, colonnes des données brutes, convertisseur pour les administrateurs, éditeur YAML). Les boutons de réglages ont été retirés des autres pages. Les réglages du convertisseur ont maintenant leur propre page (administrateurs).

## 0.3.1 — Flight time breakdown (RAC 401.08), version anglaise

- **Nouvelle page** « Breakdown » (bouton dans l'en-tête, à côté de Logbook) et son PDF **US Legal paysage sur une seule page**, d'après la feuille « Report EN » du logbook Excel : heures par type d'appareil (monomoteur, multimoteur, instruments, cross-country, instruction), ligne TOTAL, sous-totaux par section, totaux avion / hélicoptère / turbine-jet, bloc de certification (date du jour, signature vide), suivi des qualifications. Les zones photo et signature restent vides (téléversement à venir).
- **Types du tableau** : chaque ligne a un menu déroulant alimenté par la page « Types d'appareils » ; les lignes partent vides, le choix est enregistré dans `breakdown.yml`. Les totaux ne comptent que les types choisis ; un avertissement liste les heures du logbook absentes du tableau. Un type ne peut être choisi qu'une fois.
- **Mise en page** : même système que le logbook, en u (1 u = 0,01 po). Nouveau fichier `<compte>_breakdown.yml` (modèle `defaults/breakdown.yml`) : taille de page, marges, hauteurs, largeur de chaque colonne, couleurs ; page « Réglages du Breakdown » et éditeur YAML (fichier « Breakdown — mise en page »). Les largeurs doivent totaliser `page_width_u - 2 x margin_u`. Les couleurs des lignes sont celles du logbook.
- **Mon compte** : numéro de licence, numéro de téléphone et carte « Suivi des qualifications » (date d'expiration, jours restants). L'e-mail du compte est repris dans le rapport.
- Les vols à date future sont ignorés. Types sans catégorie : à compléter dans « Types d'appareils » pour les totaux avion / hélicoptère.
- Version française du rapport : à venir.

## 0.3.0 — largeurs et hauteurs uniques pour la page web et le PDF

- **Version visible** : le numéro de version s'affiche à côté de « Logger » pour tout utilisateur connecté (plus seulement les administrateurs).
- **Largeurs** : un seul jeu de largeurs, en unités u (1 u = 0,01 po), une valeur `width` par colonne, identique sur la page web et sur le PDF. Réglable colonne par colonne dans le YAML et dans « Réglages du logbook ».
- **Épaisseur des lignes** : un seul réglage `row_height_u` pour toutes les lignes (web et PDF). Les hauteurs d'en-têtes séparées disparaissent.
- **Page web** : plus de gouttières ; les deux colonnes `spacer` (5 u chacune par défaut) séparent les tableaux gauche et droit.
- **PDF** : gouttières manuelles `pdf.gutter_left_u` et `pdf.gutter_right_u` ; chaque feuille doit totaliser `page_width_u`.
- **Format du fichier de mise en page modifié** (non compatible avec les fichiers 0.2.x) : supprimés `gap_widths`, `row_height`, `header_heights`, `physical_columns`, `styles.width_scale`, `pdf.left_columns_u`, `pdf.right_columns_u`, `pdf.row_height_u`. Recréer le dossier de données, ou supprimer l'ancien fichier `<compte>_layout.yml`.

## 0.2.2 — correctifs d'intégrité (audit du 21 octobre 2026)

- **Données** : renommer le nom affiché d'une colonne ne change plus son nom technique, et un import ne supprime plus jamais de colonne
  (seule la suppression explicite d'une colonne le fait, après une copie `*.pre-drop-<date>.bak` de la base).
- **Comptes** : le démarrage est refusé, avec la liste des noms, si deux comptes ne diffèrent que par la casse ; l'index d'unicité n'est plus ignoré en silence.
- **Fusion de vols** : deux vols de numéro, d'immatriculation ou d'aéroport différents ne sont plus jamais fusionnés (résultat indépendant de l'ordre du fichier).
- **Export Excel** : une ligne de la feuille d'un autre appareil n'empêche plus d'exporter le vol de la base.
- **Interface** : une mise en page avec moins de trois couleurs de blocs ne fait plus tomber la page Logbook ; un YAML très imbriqué donne un message au lieu d'une erreur 500.
- **Fichiers de configuration** : écriture atomique (fichier temporaire puis remplacement).
- Tests : `tests/test_audit_regressions.py`.

## 0.2.1 — correctif de livraison (CI verte)

- Tests : la suite `tests/test_app.py` du projet est adaptée au durcissement (clé et mot de passe de test conformes, jeton CSRF automatique,
  déconnexion en POST, 403 pour un non-admin) **et mise à jour pour la refonte du convertisseur** qui l'avait laissée périmée depuis le
  15 octobre : règles `registration_format` / `departure_icao` / `arrival_icao` (codes ICAO, ex. `CYUL`), filtre moteur lu sur le **type**
  d'appareil (colonne « type ») au lieu de l'immatriculation, page « Avions » = types d'appareils, version affichée lue dynamiquement.
- Interface : la confirmation de « Actualiser » passe par `data-confirm` (plus de `confirm()` inline, requis par la CSP).
- Correctif : l'éditeur YAML conserve ses messages d'erreur précis (la validation de sécurité du layout passe après les contrôles d'origine).
- CI : l'audit des dépendances est un job séparé qui ne bloque plus la publication de l'image ; délais maximaux ajoutés.

## 0.2.0 — version de sécurité

**Changements qui demandent une action** (voir « Mise à jour depuis 0.1.x » dans le README) : valeurs `change-me` refusées au démarrage,
reconnexion de tous les utilisateurs, déconnexion en POST, port lié à 127.0.0.1 par défaut, conteneur non-root.

Corrigé : clé de session et compte admin par défaut ; absence de CSRF ; cookies sans `Secure`/`SameSite` ; aucune limitation de connexion ;
aucune politique de mot de passe ; sessions non révocables et sans expiration ; énumération de comptes par le temps de réponse ;
en-têtes de sécurité absents et script chargé depuis un CDN sans intégrité ; données d'un compte supprimé héritées par un compte du même nom ;
téléversements sans limite (bombe ZIP, XML) et YAML à alias ; injection CSS via le layout et injection de formules CSV/Excel ;
messages d'erreur internes affichés ; CI publiant l'image `latest` depuis les pull requests ; code mort (`admin.py`, `converter.py`).

Ajouté : comptes désactivables, changement de mot de passe obligatoire pour les comptes créés par un admin, réauthentification pour les
actions sensibles, journal de sécurité (`/security`), `manage.py` (init-admin, reset-password, list-users), suite de 100+ tests, audit des dépendances en CI.
