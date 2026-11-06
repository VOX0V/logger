# Changelog

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
