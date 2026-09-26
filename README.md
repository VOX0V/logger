# User Database

Application Flask/Docker minimale dédiée uniquement à `user.db`.

Fonctions :
- création et modification de catégories dans Settings ;
- position configurable ;
- groupe ;
- colonne technique créée automatiquement ;
- règles d'import alternatives (OU), une par ligne ;
- import de plusieurs fichiers `.xlsx` / `.xlsm` avec un seul bouton ;
- toutes les feuilles Excel sont traitées ;
- affichage des données présentes dans `user.db`.

Lancer :

```bash
docker compose up --build
```
Puis ouvrir `http://localhost:8000`.


## Import user.db

- Les règles d'import d'une catégorie sont des alternatives (OU).
- Une donnée Excel sans colonne technique existante dans `user.db` est ignorée. L'import des autres données continue.
- Chaque ligne importée conserve le nom du fichier source.
- Réimporter un fichier remplace les lignes précédemment importées par ce même fichier. Les lignes provenant d'autres fichiers ne sont pas supprimées.
- La colonne interne `import_source` sert uniquement au suivi des imports et n'est pas une catégorie affichée.
