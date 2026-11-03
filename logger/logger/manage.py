"""Administration en ligne de commande (récupération sans contourner les contrôles de sécurité).

    python manage.py init-admin [--username admin]   premier administrateur (mot de passe aléatoire affiché UNE fois)
    python manage.py reset-password <utilisateur>    nouveau mot de passe aléatoire (affiché UNE fois, à changer à la connexion)
    python manage.py list-users                      comptes, rôles et état

Les mots de passe générés sont écrits sur la sortie standard du terminal uniquement, jamais dans les journaux.
"""
import argparse
import sys

from app import create_app
from app import passwords


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-admin"); init.add_argument("--username", default="admin")
    reset = sub.add_parser("reset-password"); reset.add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args(argv)

    app = create_app(require_admin=False)
    with app.app_context():
        from app.accounts import (count_accounts, create_account, get_account_by_username, list_accounts, set_password)
        from app.seclog import log_event
        if args.command == "init-admin":
            if count_accounts() > 0:
                print("Déjà initialisé : des comptes existent. Utilise reset-password pour récupérer un accès.", file=sys.stderr)
                return 1
            password = passwords.generate_password()
            create_account(args.username, password, role="admin", must_change=True)
            log_event("admin_bootstrap", username=args.username, reason="créé via manage.py init-admin")
            print(f"Administrateur « {args.username} » créé.\nMot de passe initial (affiché une seule fois) : {password}\n"
                  "Il devra être changé à la première connexion.")
        elif args.command == "reset-password":
            account = get_account_by_username(args.username)
            if not account:
                print("Compte introuvable.", file=sys.stderr)
                return 1
            password = passwords.generate_password()
            set_password(account["id"], password, must_change=True)       # révoque aussi toutes ses sessions
            log_event("password_reset_cli", target=account["username"], reason="sessions révoquées")
            print(f"Nouveau mot de passe pour « {account['username']} » (affiché une seule fois) : {password}\n"
                  "Il devra être changé à la prochaine connexion ; toutes ses sessions ont été révoquées.")
        else:
            for a in list_accounts():
                print(f"{a['username']:<32} {a['role']:<6} {'actif' if a['active'] else 'DÉSACTIVÉ'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
