import sys

from app import SetupError, create_app

try:
    app = create_app()
except SetupError as exc:                      # configuration dangereuse ou incomplète : message clair, pas de trace
    sys.stderr.write(f"\n[DÉMARRAGE REFUSÉ] {exc}\n\n")
    sys.exit(3)
