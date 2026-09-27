# Logger

Version 1.4.0. Application Flask multi-utilisateurs pour importer des fichiers Excel/CSV dans une base par utilisateur, selon une configuration YAML propre à chaque compte.

## Architecture

- Chaque compte possède son propre espace : `storage/users/<username>/user_data.db` (import brut), `user_logbook.db` (logbook dérivé), `userdb.yml`, `logbookdb.yml`, `logbook.yml`.
- `storage/accounts.db` est une base globale unique qui liste les comptes (username, mot de passe haché, rôle `admin`/`user`).
- `userdb.yml` contient les catégories, groupes et règles d'import de `user_data.db`.
- `logbookdb.yml` contient la structure et les sources de `user_logbook.db`.
- `logbook.yml` contient la présentation du Logbook : colonnes, largeurs, hauteurs, pagination et totaux.
- Le dossier persistant complet est `/app/storage` (à monter en volume).

## Comptes

- Au premier démarrage, si aucun compte n'existe, un compte admin est créé automatiquement à partir de `ADMIN_USERNAME`/`ADMIN_PASSWORD`.
- Seul un admin peut créer/modifier/supprimer des comptes (menu "Comptes").
- Un `user` normal n'a accès qu'à ses propres données.

## Import

Les règles d'import sont des alternatives OR. Par exemple, `immat`, `reg` et `registration` peuvent tous alimenter `users.registration`. Une colonne Excel inconnue est ignorée.

Un nouvel import portant le même nom de fichier remplace les lignes provenant de ce fichier uniquement. Les données des autres fichiers restent présentes.

## Déploiement

Copier `.env.example` vers `.env`, puis définir les identifiants (utilisés uniquement pour créer le premier compte admin). En développement local :

    docker compose up -d --build

L'image GHCR peut ensuite être publiée par GitHub Actions.
