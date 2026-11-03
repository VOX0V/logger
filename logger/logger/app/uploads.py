"""Garde-fous sur les fichiers Excel envoyés : un .xlsx est une archive ZIP, donc une bombe de décompression est possible."""
import io
import re
import zipfile

MAX_UNCOMPRESSED = 200 * 1024 * 1024      # taille totale décompressée
MAX_ENTRIES = 2000
MAX_RATIO = 200                            # décompressé / compressé


def check_xlsx(source):
    """`source` : bytes ou chemin. Lève ValueError si l'archive est invalide ou suspecte."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    except (zipfile.BadZipFile, OSError):
        raise ValueError("The Excel file is unreadable or corrupted.")
    with archive:
        infos = archive.infolist()
        total = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos) or 1
        if len(infos) > MAX_ENTRIES or total > MAX_UNCOMPRESSED or (total > 20 * 1024 * 1024 and total / packed > MAX_RATIO):
            raise ValueError("Excel file rejected: excessive uncompressed content.")


_NUMBER = re.compile(r"^[+-]?\d+([.,]\d+)?$")


def neutralize_formula(value):
    """Injection de formules (CSV/Excel) : une cellule texte commençant par = + - @ serait exécutée à l'ouverture."""
    if isinstance(value, str) and value:
        first = value[0]
        if first in "=@\t\r" or (first in "+-" and not _NUMBER.match(value.strip())):
            return "'" + value
    return value
