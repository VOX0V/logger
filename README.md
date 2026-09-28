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

- Au premier démarrage, si aucun compte n'existe, un admin est créé depuis `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
- Seuls les admins créent les comptes et gèrent le catalogue de règles, les aéroports et les avions.

## Convertisseur

Onglet **Convertisseur** : catalogue de règles partagé. Chaque règle lit des colonnes de A, applique une transformation (copie, assemblage de date, temps de bloc en décimales, jour/nuit) et écrit dans B. Chaque utilisateur coche les règles qu'il veut appliquer, puis clique sur **Actualiser** dans logbook.db. Pour une même colonne de B, la première règle cochée qui donne une valeur l'emporte.

Nuit : de 30 min après le coucher du soleil à 30 min avant le lever (réglable), calculée avec `ephem` à l'aéroport d'arrivée.

## Déploiement

Copier `.env.example` vers `.env`, puis :

    docker compose up -d --build
