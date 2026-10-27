# Setup

## Docker (recommended)

Install Docker Engine with Compose, or Docker Desktop. Clone this repository, then:

```sh
python3 scripts/configure_local.py
docker compose up -d --build
docker compose exec app python manage.py migrate
docker compose exec app python manage.py bootstrap_event
docker compose exec app python manage.py createsuperuser
```

Visit http://127.0.0.1:8000/. Use your own newly created administrator account at `/control/`. No shared password is supplied. The configuration helper creates fresh secrets in an ignored, owner-readable `.env`; it refuses to overwrite an existing file.

To populate a fresh demonstration installation after creating your administrator:

```sh
docker compose exec app python manage.py seed_demo
```

This opt-in command adds fictional teams, scores, a SuperTeam challenge and a deadline. It refuses a non-demo competition or an installation with existing scores. It creates no accounts and sends no email. Never run demo seeding against a real competition.

The worker scans uploads and processes queued mail. ClamAV needs time to download its signatures on first startup; do not expose unscanned files. Email delivery requires explicit SMTP configuration. Do not enter production mail credentials when exploring the demo.

## Python development

Use Python 3.12 and a virtual environment:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.runtime.lock
mkdir -p var
export DJANGO_DEBUG=1
export DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
.venv/bin/python manage.py migrate
.venv/bin/python manage.py bootstrap_event
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

This mode uses SQLite when DATABASE_URL is unset. It does not automatically load `.env`. Export any required settings yourself. For scanning and background jobs, use Docker or provide a private ClamAV daemon and run `python manage.py run_workers` in a separate process. Do not use the development server for production.

## Initial competition configuration

1. Sign in and open Competition settings. Set the event name, location, timezone, dates and scoring policy.
2. Configure Team accounts and existing-team SuperTeam pairings.
3. Add rounds, arrange the team lineup, and place round blocks in the schedule.
4. Create participant upload requests and deadlines; configure organizer documents and announcements.
5. Configure SMTP and storage only when ready. Test using an address you control.
6. Enter scores or import a match recording. Review results before releasing rankings.

The bundled snapshot is fictional and contains no scores or login accounts. The original competition database and submissions are not part of the project.

## Tests

```sh
.venv/bin/pip install -r requirements.in
.venv/bin/python -m pytest
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py collectstatic --noinput
```

Use DEBUG and a fresh secret for local management commands. Upload and privacy tests use temporary data. Admin and team screenshots use the fictional demo. Replay and field images are frames from actual demonstration footage. No private account credentials are shown.
