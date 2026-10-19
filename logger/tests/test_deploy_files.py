"""Garde-fous sur les fichiers de déploiement : une régression ici rouvrirait des failles corrigées."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(rel):
    return (ROOT / rel).read_text()


def test_dockerfile_runs_unprivileged_with_pinned_requirements():
    docker, entry = read("logger/Dockerfile"), read("logger/docker-entrypoint.sh")
    assert "useradd" in docker and "10001" in docker and "HEALTHCHECK" in docker and "manage.py" in docker
    assert "setpriv" in entry and "--no-new-privs" in entry
    assert not re.search(r"^(pytest|pip-audit)", read("logger/requirements.txt"), re.M | re.I), "pas d'outils de test en production"
    for line in read("logger/requirements.txt").splitlines():
        if line.strip() and not line.startswith("#"):
            assert "==" in line, f"dépendance non épinglée : {line}"


def test_compose_binds_localhost_and_drops_capabilities():
    compose = read("docker-compose.yml")
    assert "127.0.0.1" in compose and "cap_drop" in compose and "no-new-privileges" in compose
    assert '"8000:8000"' not in compose


def test_env_example_has_no_default_credentials():
    env = read(".env.example")
    assert not re.search(r"^ADMIN_PASSWORD=.+", env, re.M)
    assert not re.search(r"^SECRET_KEY=.+", env, re.M)
    assert not [l for l in env.splitlines() if l and not l.startswith("#") and "change-me" in l]


def test_ci_never_publishes_from_pull_requests_and_runs_tests():
    ci = read(".github/workflows/ci.yml")
    assert "push: ${{ github.event_name == 'push' }}" in ci and "needs: test" in ci
    assert "pytest" in ci and "pip-audit" in ci
    assert re.search(r"docker/login-action@v3\n\s+if: github.event_name == 'push'", ci)


def test_no_dead_or_shadowed_modules_remain():
    app = ROOT / "logger" / "app"
    assert not (app / "admin.py").exists() and not (app / "converter.py").exists()


def test_no_default_secret_fallbacks_in_source():
    """Aucune lecture d'environnement ne doit retomber sur un secret de démonstration."""
    pattern = re.compile(r"(environ\.get|getenv)\([^)]*(change-me|dev-change|admin\"\s*\))", re.I)
    for path in (ROOT / "logger" / "app").rglob("*.py"):
        for line in path.read_text().splitlines():
            assert not pattern.search(line) or "ADMIN_USERNAME" in line, f"{path.name} : {line.strip()}"
