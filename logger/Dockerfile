FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=wsgi
WORKDIR /app

# Compte système sans privilèges (uid 10001) : l'application ne tourne jamais en root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY defaults ./defaults
COPY import_profiles ./import_profiles
COPY wsgi.py manage.py VERSION ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /app/appdata /app/users \
 && chown -R app:app /app/appdata /app/users

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# L'entrypoint corrige la propriété des volumes existants (créés en root par les versions 0.1.x),
# puis abandonne les privilèges avant de lancer la commande.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
