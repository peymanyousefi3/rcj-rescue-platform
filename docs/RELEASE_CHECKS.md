# Public release checks

Public release authorized by Peyman Yousefi on 27 October 2026. Project-owned code is licensed under MIT, copyright 2026 Peyman Yousefi.

## Source boundary

- Separate repository with a new initial history; no original operational Git history is copied.
- Production database, account records, uploaded files, original recording/map packages, environment files, keys and deployment access notes are excluded.
- The roster is fictional. The optional demo command creates no credentials and sends no email.
- Admin and team screenshots were captured from the isolated fictional local demo. Replay and field images come from actual demonstration footage. Screenshot EXIF metadata is absent.
- Original competition logos and the external hero photograph are replaced with project-owned neutral artwork. Bundled dependency licenses remain intact.
- Original project development-tool labels and workstation/server-access paths are excluded. The creator credit is Peyman Yousefi.

## Checks

- Local Python suite: 354 passed; two PostgreSQL-only row-lock concurrency tests skipped on SQLite.
- New fictional setup checks: two passed, including no seeded accounts or outgoing mail, refusal to overwrite scores, and refusal to populate a real competition.
- JavaScript folder upload, replay callback, spreadsheet paste/Undo/time checks: ten passed.
- Django system check: no issues. Migration consistency check: no changes detected.
- Fresh isolated bootstrap: fictional roster only, no scores or accounts.
- Gitleaks 8.30.1 scanned the release files and all fetched branch and pull-request history with redacted reporting: no leaks found.
- Additional review checks source paths, production access markers, personal-address strings, binary metadata and excluded file types. Gmail addresses in provider tests are synthetic test values; test and CI passwords/keys are explicitly non-production fixtures.
- PDF pages and documentation screenshots were visually inspected.

The GitHub workflow passed all 358 Python tests against PostgreSQL, including concurrency checks, all ten JavaScript checks, production configuration checks and the dependency audit. Results remain visible in the repository's Actions tab. Docker is not available on the preparation Mac, so the Compose launch was not executed there. HTTPS, DNS, SMTP, external storage and an operator's backup/restore procedure must be verified on the operator's infrastructure.

These are release-preparation checks, not a guarantee of complete security. No live competition data, website settings or outgoing emails were changed during preparation.

## Publication and contribution controls

- The owner authorized publication on 27 October 2026.
- Only `peymanyousefi3` has repository write/admin access at release. No deployment keys, collaborator invitations, webhooks, repository secrets, variables or stored Actions artifacts were present in the release check.
- `.github/CODEOWNERS` assigns every file to `peymanyousefi3`.
- `main` requires pull requests, a code-owner review, passing checks and resolved conversations; new commits invalidate stale approvals. Force pushes and branch deletion are blocked. The owner retains a personal pull-request bypass for his own work.
- README images and the public YouTube demonstration are checked without GitHub authentication after publication.

Test passwords, keys and email addresses in fixtures and CI are synthetic examples. They are not competition credentials. The source-history and content scans supplement the tests; they are not a guarantee of complete security.
