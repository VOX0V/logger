# Changelog

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
