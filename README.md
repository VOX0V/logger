# Logger

Version 1.1.0. Application Flask minimale pour importer plusieurs fichiers Excel dans `user.db` selon une configuration YAML séparée.

## Architecture

- `user.db` contient uniquement les données importées dans la table `users`.
- `configuration.yml` contient les catégories, groupes et règles d'import.
- Le fichier de configuration est persistant dans `/app/instance/configuration.yml`.
- Les anciennes bases de travail, bases publiques, logbook et imports spécialisés ne font plus partie de cette version.

## Import

Les règles d'import sont des alternatives OR. Par exemple, `immat`, `reg` et `registration` peuvent tous alimenter `users.registration`. Une colonne Excel inconnue est ignorée.

Un nouvel import portant le même nom de fichier remplace les lignes provenant de ce fichier uniquement. Les données des autres fichiers restent présentes.

## Déploiement

Copier `.env.example` vers `.env`, puis définir les identifiants. En développement local :

    docker compose up -d --build

L'image GHCR peut ensuite être publiée par GitHub Actions.
