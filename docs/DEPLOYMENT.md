# Deployment

Use a separate host and database for each competition or staging environment. Back up the database and private storage together before upgrades. Never copy a live competition database into a public source repository.

## HTTPS with Docker and Caddy

Point a domain's DNS records to your server. Allow HTTPS and HTTP for certificate issuance, while keeping the database and scanner private. Start with `scripts/configure_local.py`, then edit the ignored `.env`:

- `DJANGO_DEBUG=0`
- `DJANGO_ALLOWED_HOSTS=your-domain.example`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.example`
- `PUBLIC_ORIGIN=https://your-domain.example`
- `PUBLIC_HOST=your-domain.example`
- `TRUST_PROXY_HTTPS=1`
- `TRUST_PROXY_CLIENT_IP=1` and a fresh `PROXY_SHARED_SECRET` (the configuration helper generates it).
- `REQUIRE_STAFF_OTP=1`; enroll staff and keep recovery codes privately.
- Separate `POSTGRES_PASSWORD` and `APP_DB_PASSWORD`; the app receives only the latter.
- Keep fresh, strong Django and PostgreSQL secrets.

The example hostname must be replaced with your own domain. Run:

```sh
docker compose build
docker compose up -d db clamav
docker compose run --rm migrate
docker compose -f compose.yaml -f deploy/compose.production.yaml up -d app worker caddy
docker compose exec app python manage.py bootstrap_event
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py check --deploy
```

`bootstrap_event` is for a new installation only. Do not seed demonstration data into production. The application port remains bound to the host loopback; Caddy reaches the app on the internal Compose network. Secure any other reverse proxy so untrusted clients cannot supply trusted forwarding headers.

## Concurrent events

One installation serves one competition. For two concurrent events, create two separately named Compose projects, each with its own hostname, configuration secrets, database and private-storage volumes. Do not point both installations at one database or reuse session-signing secrets. A separate application replica within one event may share that event's database and private storage; it is not a second event. Size the host against the combined measured load. The isolated CI profile exercises two events with 30 teams each, not a guarantee for an unmeasured production host.

## Services and secrets

- PostgreSQL stores application records; keep its volume and regular backups private.
- The shared private volume stores uploaded files; preserve it across app upgrades.
- ClamAV scans incoming files. Keep its signature database current.
- The worker processes scans and queued outgoing emails. Configure SMTP in the admin panel or supported environment settings. Keep announcement CC/BCC scoped to announcements.
- Optional private object storage and Google Drive require restricted credentials and a dedicated private destination. See `.env.example` and the storage settings in the admin panel.
- Workbook import is optional; the dashboard can own schedule and score data without an external sheet.

## Upgrade checks

Back up first. Review migrations, run tests, build the new image, migrate, restart app and worker, then verify login, recipient access, uploads, deadlines, playback, scoring and ranking-release controls. Keep a tested rollback and restore procedure. Never delete volumes as part of an ordinary deployment.

The included configuration is a starting point for your infrastructure, not an audit or a managed hosting service. Review mail branding, recording trust, retention, backups, access controls and operational monitoring before accepting real participant data.

## Upgrading an existing database volume

The new initialization script runs **only on a new PostgreSQL volume**. Never remove a populated volume to make initialization run again. Before adopting the new Compose configuration, create and verify a coordinated encrypted backup and rehearsal restore.

For an older installation, keep its actual bootstrap role name in `DB_ADMIN_USER` (for example `arena`) and preserve its existing `POSTGRES_PASSWORD`. Generate fresh URL-safe `APP_DB_PASSWORD` and `PROXY_SHARED_SECRET` values privately. While the old configuration is still stopped in a maintenance window, use the existing administrator connection to create the restricted runtime role and grants from `deploy/init-db.sh`; then grant that role SELECT/INSERT/UPDATE/DELETE on the existing tables and USAGE/SELECT on existing sequences. Check that the runtime role cannot create roles/databases, alter schema or bypass append-only audit protections. Do not copy the bootstrap password into app/worker environment variables.

Run migrations through the one-off `migrate` service, then start app/worker and the ingress. Verify with `check_readiness`, normal team access, cross-team denial, recipient revocation, deadlines and replay loading. The supplied configuration changes resource limits, MFA defaults, authenticated forwarding and database roles; do not replace an existing operational configuration blindly. [Security operations](SECURITY_OPERATIONS.md) documents remaining host/provider requirements and the non-destructive recovery procedure.
