"""Messages d'erreur sûrs : le texte des erreurs attendues est montré, jamais celui des erreurs internes."""
from flask import current_app, g, has_request_context

GENERIC = "Une erreur interne est survenue."


def safe_message(exc):
    """Erreurs de validation (ValueError, FileImportError...) : message tel quel. Autres : message générique + trace dans les logs."""
    if isinstance(exc, ValueError) or type(exc).__name__ in {"FileImportError", "Problem"}:
        return str(exc)
    current_app.logger.exception("Erreur inattendue")
    ref = g.get("request_id") if has_request_context() else None
    return GENERIC + (f" (référence {ref})" if ref else "")
