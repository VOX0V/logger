# Sécurité — Logger 0.2.0

## Modèle de menace (résumé)

Application web multi-utilisateurs (Flask + SQLite, une base par utilisateur) hébergeant des carnets de vol : données personnelles
et professionnelles. Menaces visées : prise de contrôle de comptes (identifiants par défaut, force brute, session volée),
actions déclenchées à l'insu d'un utilisateur connecté (CSRF), élévation de privilèges, fuite entre utilisateurs, fichiers
téléversés malveillants, injection de contenu (CSS/formules), exposition réseau et chaîne d'approvisionnement.

## Contrôles en place

| Domaine | Contrôle |
|---|---|
| Démarrage | Refus de démarrer sans `SECRET_KEY` solide (ou génération aléatoire persistée en 0600) ni mot de passe admin conforme ; aucun identifiant par défaut |
| Mots de passe | Argon2id (paramètres explicites), 15–256 caractères, mots de passe courants refusés, ancien hachage migré à la connexion |
| Connexion | Limitation par couple compte+IP, par IP et par compte (fenêtre glissante 15 min), réponse identique pour compte inconnu / mauvais mot de passe / compte désactivé / blocage, temps de calcul équivalent |
| Sessions | Cookie `HttpOnly`, `SameSite=Lax`, `Secure` ; expiration inactive (60 min) et absolue (12 h) ; version de session : révocation immédiate au changement de mot de passe, de rôle, à la désactivation ou sur demande |
| CSRF | Jeton sur tous les formulaires et appels `fetch` (Flask-WTF) ; déconnexion en POST ; test automatique de toutes les routes POST |
| Autorisations | Chaque route porte `login_required` ou `admin_required` (vérifié par test) ; 403 pour les non-admins ; dernier admin actif protégé ; pas d'auto-élévation ni d'auto-désactivation ; réauthentification (10 min) pour comptes, suppressions et destruction de données |
| Données | Une base SQLite par utilisateur, chemins dérivés d'un nom validé ; comptes supprimés archivés dans `users/.deleted/`, jamais hérités |
| En-têtes | CSP avec nonce (aucun script inline ni externe), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store`, HSTS optionnel |
| Entrées | Limite de taille des requêtes, contrôle anti-bombe ZIP des .xlsx, `defusedxml`, YAML sans ancres/alias, valeurs CSS validées, neutralisation des formules CSV/Excel |
| Erreurs | Pages d'erreur génériques avec référence de requête ; détails dans les logs seulement |
| Audit | Journal `security_events` (UTC, événement, résultat, compte, IP, requête, cible), page admin `/security`, rétention 180 jours, aucune donnée secrète, caractères de contrôle neutralisés |
| Déploiement | Conteneur non-root, `cap_drop: ALL`, `no-new-privileges`, port lié à 127.0.0.1, healthcheck, dépendances épinglées, CI qui teste, audite les dépendances et ne publie jamais depuis une pull request |

## Limites connues et recommandations

- **MFA non implémenté.** Pour les administrateurs, c'est la prochaine amélioration (TOTP + codes de secours) ; en attendant, protéger l'accès par VPN ou par l'authentification du reverse proxy.
- **Limitation de connexion stockée dans SQLite** : valable pour une instance (plusieurs workers inclus). Plusieurs instances derrière un équilibreur demanderaient un stockage partagé.
- **`style-src 'unsafe-inline'`** subsiste (attributs `style=` dans les gabarits). Les scripts, eux, sont strictement limités (nonce + fichiers locaux).
- **CSP et conteneur non validés en navigateur / Docker réel** lors de cette livraison : en cas de blocage inattendu, `CSP_REPORT_ONLY=1` la passe en mode signalement.
- **Épinglage** : l'image de base (`python:3.12-slim`) et les actions GitHub sont référencées par étiquette, pas par empreinte ; les épingler (`@sha256:…`, `uses: …@<sha>`) est recommandé.
- **Verrouillage par compte** : un attaquant peut gêner temporairement un compte (40 échecs/15 min toutes sources). C'est un compromis assumé ; le journal l'affiche.
- **Sauvegardes** : les exports et `users.db.pre-migration-*.bak` contiennent des données sensibles : les stocker chiffrés et les purger.
- `users/.deleted/` n'est jamais purgé automatiquement.

## Signaler une vulnérabilité

Contacter les mainteneurs en privé (pas de ticket public) avec les étapes de reproduction.
