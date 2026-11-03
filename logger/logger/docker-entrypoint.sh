#!/bin/sh
# Démarre en root uniquement le temps de réparer la propriété des volumes, puis exécute la commande en uid 10001.
set -eu
APP_UID=10001
DATA_DIRS="${LOGGER_DATA_DIRS:-/app/appdata /app/users}"

if [ "$(id -u)" = "0" ]; then
  for dir in $DATA_DIRS; do
    mkdir -p "$dir"
    if [ "$(stat -c %u "$dir")" != "$APP_UID" ]; then
      chown -R "$APP_UID:$APP_UID" "$dir"
    fi
  done
  exec setpriv --reuid="$APP_UID" --regid="$APP_UID" --clear-groups --no-new-privs -- "$@"
fi
exec "$@"
