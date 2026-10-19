# Logger

Application Flask multi-utilisateurs : importer des données brutes (Excel/CSV) dans une base A par utilisateur, les convertir avec des règles vers une base B, puis produire un logbook imprimable.

## Organisation des données

```
logger/
  appdata/                      (partagé, à monter en volume)
    db/users.db                 comptes
    db/airport.db               aéroports (coordonnées GPS)
    db/aircrafts.db             avions (immatriculation, type, moteur)
    converter/rules.yml         catalogue des règles de conversion
    converter/settings.yml      marges de nuit et tableau d'arrondi Transport Canada
  users/<utilisateur>/          (par compte, à monter en volume)
    <u>_data.db / <u>_data.yml          base A et sa structure
    <u>_logbook.db / <u>_logbook.yml    base B et sa structure
    <u>_layout.yml                      mise en page du logbook
    <u>_converter.yml                   règles cochées par l'utilisateur
```

Le code reste dans l'image Docker ; les valeurs par défaut (`defaults/`) ne sont copiées vers `appdata/` qu'à la première utilisation, une mise à jour n'écrase donc jamais les réglages.

## Comptes

- Au premier démarrage, si aucun compte n'existe, un admin est créé depuis `ADMIN_USERNAME` / `ADMIN_PASSWORD` (15 caractères minimum, valeurs courantes refusées). Sans `ADMIN_PASSWORD`, l'application **refuse de démarrer** avec les instructions à suivre : `docker compose run --rm logger python manage.py init-admin` génère un mot de passe aléatoire affiché une seule fois.
- Seuls les admins créent les comptes et gèrent le catalogue de règles, les aéroports et les avions. Un compte créé par un admin doit changer son mot de passe à la première connexion.
- Mots de passe : 15 caractères minimum, 256 maximum, espaces et collage autorisés (une phrase de passe convient). Hachage Argon2id.
- Un compte supprimé n'efface pas ses données : son dossier est déplacé dans `users/.deleted/` (à purger manuellement), et un nouveau compte du même nom n'en hérite jamais.
- Compte perdu : `docker compose run --rm logger python manage.py reset-password <utilisateur>` (mot de passe aléatoire affiché une seule fois, toutes les sessions révoquées).

## Convertisseur

Onglet **Convertisseur** : catalogue de règles partagé. Chaque règle lit des colonnes de A, applique une transformation (copie, assemblage de date, temps de bloc en décimales, jour/nuit) et écrit dans B. Chaque utilisateur coche les règles qu'il veut appliquer, puis clique sur **Actualiser** dans logbook.db. Pour une même colonne de B, la première règle cochée qui donne une valeur l'emporte.

Nuit : de 30 min après le coucher du soleil à 30 min avant le lever (réglable), calculée avec `ephem` à l'aéroport d'arrivée.

## Déploiement

Copier `.env.example` vers `.env`, renseigner `ADMIN_PASSWORD` (ou utiliser `manage.py init-admin`), puis :

    docker compose up -d --build

Par défaut le port n'est publié que sur `127.0.0.1` : place un **reverse proxy HTTPS** devant l'application (le cookie de session est réservé à HTTPS).

Exemple Caddy (`TRUSTED_PROXIES=1` dans `.env`) :

    logger.exemple.com {
        reverse_proxy 127.0.0.1:8000
    }

Exemple nginx (`TRUSTED_PROXIES=1`) — `X-Forwarded-For` doit être *ajouté* par le proxy, jamais recopié depuis le client :

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        client_max_body_size 50m;
    }

Sans proxy et en HTTP sur un réseau local de confiance : `LOGGER_BIND=0.0.0.0` et `COOKIE_SECURE=0` (avertissement au démarrage). Ne jamais exposer ce mode sur Internet.

Si, derrière HTTPS, chaque formulaire répond « jeton de sécurité expiré » : le proxy ne transmet pas `X-Forwarded-Proto` / `X-Forwarded-Host`, ou `TRUSTED_PROXIES` ne vaut pas le nombre de proxies réels.

## Sécurité

Résumé des contrôles et risques résiduels : voir [SECURITY.md](SECURITY.md). Les tests (`cd logger && python -m pytest`) couvrent les contrôles ; la CI les exécute ainsi qu'un audit des dépendances (`pip-audit`).

## Mise à jour depuis 0.1.x

1. **Sauvegarde** : télécharge l'export de chaque utilisateur (Mon compte → Exporter) et copie les volumes `logger_appdata` et `logger_users`.
2. Édite `.env` : retire `ADMIN_PASSWORD=change-me` et `SECRET_KEY=change-me-to-a-long-random-value` (**ces valeurs sont désormais refusées**). Laisse `SECRET_KEY` vide ; `ADMIN_PASSWORD` peut rester vide puisque des comptes existent déjà.
3. `docker compose up -d --build`. Au premier démarrage : `users.db` est migré après une copie automatique `users.db.pre-migration-<date>.bak` (dans le volume `appdata`), les anciens hachages sont remplacés par Argon2id à la prochaine connexion de chaque utilisateur, et les volumes sont rendus à l'utilisateur non-root (uid 10001).
4. **Tous les utilisateurs devront se reconnecter** (anciennes sessions invalidées). Les mots de passe existants continuent de fonctionner ; la nouvelle politique ne s'applique qu'aux prochains changements.
5. Si l'ancien mot de passe admin était `change-me` ou `admin`, change-le tout de suite (Mon compte), puis considère qu'il a pu être compromis.
6. Retour arrière : restaurer les volumes sauvegardés et reconstruire l'ancienne image.
