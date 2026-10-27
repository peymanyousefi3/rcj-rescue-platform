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
- Keep fresh, strong Django and PostgreSQL secrets.

The example hostname must be replaced with your own domain. Run:

```sh
docker compose -f compose.yaml -f deploy/compose.production.yaml up -d --build
docker compose exec app python manage.py migrate
docker compose exec app python manage.py bootstrap_event
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py check --deploy
```

`bootstrap_event` is for a new installation only. Do not seed demonstration data into production. The application port remains bound to the host loopback; Caddy reaches the app on the internal Compose network. Secure any other reverse proxy so untrusted clients cannot supply trusted forwarding headers.

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
