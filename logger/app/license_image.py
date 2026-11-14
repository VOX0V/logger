"""Image of the pilot's license (JPG or PNG): kept in the user's folder, shown at the top left of the breakdown."""
from flask import url_for

from .db import user_file

MAX_BYTES = 5 * 1024 * 1024
KINDS = {"png": (b"\x89PNG\r\n\x1a\n", "image/png"), "jpg": (b"\xff\xd8\xff", "image/jpeg")}


def _kind(data):
    for ext, (signature, _mime) in KINDS.items():
        if data.startswith(signature):
            return ext
    return None


def find(username=None):
    """(path, mimetype) of the stored image, or None."""
    for ext, (_signature, mime) in KINDS.items():
        path = user_file(f"license.{ext}", username)
        if path.is_file():
            return path, mime
    return None


def delete(username=None):
    for ext in KINDS:
        user_file(f"license.{ext}", username).unlink(missing_ok=True)


def save(data, username=None):
    """Keeps the image under license.png or license.jpg in the user's folder (the type is read from the content)."""
    if not data:
        raise ValueError("Choose a JPG or PNG image.")
    if len(data) > MAX_BYTES:
        raise ValueError("The image is too large (5 MB at most).")
    ext = _kind(data)
    if ext is None:
        raise ValueError("The file must be a JPG or PNG image.")
    delete(username)
    path = user_file(f"license.{ext}", username)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def url(username=None):
    """Address of the image for the pages, or an empty text when there is none."""
    found = find(username)
    if not found:
        return ""
    return url_for("accounts.license_image_file", v=int(found[0].stat().st_mtime))
