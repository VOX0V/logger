"""Politique de mots de passe et hachage.

- Hachage : Argon2id avec paramètres explicites (profil RFC 9106 “mémoire réduite”).
- Les anciens hachages Werkzeug (pbkdf2/scrypt) restent vérifiables ; ils sont remplacés par un
  hachage Argon2id après la première connexion réussie (voir accounts.verify_password).
- Aucune règle de composition arbitraire : longueur minimale, phrases de passe et collage autorisés.
"""
import re
import secrets

from argon2 import PasswordHasher, Type
from argon2 import exceptions as argon2_errors
from werkzeug.security import check_password_hash

MIN_LENGTH = 15
MAX_LENGTH = 256

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID)
_dummy_hash = None

# Mots de passe notoirement faibles qui passeraient quand même la longueur minimale.
_COMMON = {
    "passwordpassword", "password1234567", "password12345678", "1234567890123456", "12345678901234567890",
    "qwertyuiopasdfgh", "qwertyuiopasdfghjkl", "azertyuiopqsdfgh", "azertyuiopqsdfghjklm",
    "abcdefghijklmnop", "administrator1234", "administratorpassword", "changemechangeme",
    "changemetoalongrandomvalue", "devchangeme", "motdepassemotdepasse", "iloveyouiloveyou",
    "letmeinletmeinletmein", "welcomewelcomewelcome", "0123456789abcdef",
}
_WEAK_PREFIXES = ("password", "motdepasse", "azerty", "qwerty", "admin", "changeme", "letmein",
                  "welcome", "bonjour", "soleil", "football", "iloveyou")


def _alnum(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def policy_errors(password, username=None):
    """Liste des raisons pour lesquelles le mot de passe est refusé (vide = accepté)."""
    errors = []
    if not isinstance(password, str) or password == "":
        return ["Password required."]
    if len(password) < MIN_LENGTH:
        errors.append(f"The password must contain at least {MIN_LENGTH} characters (a passphrase works very well).")
    if len(password) > MAX_LENGTH:
        errors.append(f"The password must not exceed {MAX_LENGTH} characters.")
    if errors:
        return errors
    flat = _alnum(password)
    if len(set(password)) < 6:
        errors.append("This password is too repetitive.")
    if flat in _COMMON or any(flat.startswith(p) and len(flat) <= len(p) + 8 for p in _WEAK_PREFIXES):
        errors.append("This password is too common or predictable.")
    if username and len(username) >= 3 and _alnum(username) and _alnum(username) in flat:
        errors.append("The password must not contain the username.")
    return errors


def check_policy(password, username=None):
    errors = policy_errors(password, username)
    if errors:
        raise ValueError(" ".join(errors))


def hash_password(password):
    return _HASHER.hash(password)


def verify(stored_hash, password):
    """Vrai si le mot de passe correspond (Argon2id ou ancien hachage Werkzeug)."""
    if not stored_hash or not isinstance(password, str) or len(password) > MAX_LENGTH:
        burn(password if isinstance(password, str) else "")
        return False
    try:
        if stored_hash.startswith("$argon2"):
            return _HASHER.verify(stored_hash, password)
        return check_password_hash(stored_hash, password)
    except (argon2_errors.VerifyMismatchError, argon2_errors.VerificationError,
            argon2_errors.InvalidHashError, ValueError):
        return False


def needs_rehash(stored_hash):
    if not stored_hash or not stored_hash.startswith("$argon2id$"):
        return True
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except argon2_errors.InvalidHashError:
        return True


def burn(password=""):
    """Dépense le même temps qu'une vérification réelle (compte inexistant) pour ne pas révéler son existence."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _HASHER.hash(secrets.token_urlsafe(24))
    try:
        _HASHER.verify(_dummy_hash, (password or "")[:MAX_LENGTH])
    except argon2_errors.Argon2Error:
        pass


def generate_password():
    """Mot de passe aléatoire fort (24 caractères) pour l'initialisation et la récupération par la CLI."""
    return secrets.token_urlsafe(18)
