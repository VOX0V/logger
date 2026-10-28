# Changelog

## 0.3.8 — Conversion profiles

- **Conversion profiles**: new `logger/converter/` folder, one `<company>_convert.yml` file per airline matching its import profile (`creebec_convert.yml` first), using the same rule format as the converter catalog.
- Raw database A gets an `import_profile` column filled at import (empty = default rules). During conversion, rows with a conversion profile use its rules instead of the ticked rules.
- New transforms: `date_dmy`, `last_first_name`, `time_by_landing` (optional Transport Canada rounding), `skip_blank`.
- Air Creebec times use the Transport Canada rounding table.
- `converter/default_convert.yml`: plain copy of the basic columns of A into B for rows without a conversion profile, applied after the ticked rules (it only fills empty columns).

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
