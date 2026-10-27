# Private release preparation

Prepared for owner review on 27 October 2026. Project-owned code is licensed under MIT, copyright 2026 Peyman Yousefi. Repository visibility remains private.

## Source boundary

- Separate repository with a new initial history; no original operational Git history is copied.
- Production database, account records, uploaded files, original recording/map packages, environment files, keys and deployment access notes are excluded.
- The roster is fictional. The optional demo command creates no credentials and sends no email.
- Real screenshots were captured from that isolated fictional local demo. Screenshot EXIF metadata is absent.
- Original competition logos and the external hero photograph are replaced with project-owned neutral artwork. Bundled dependency licenses remain intact.
- Original project development-tool labels and workstation/server-access paths are excluded. The creator credit is Peyman Yousefi.

## Checks

- Local Python suite: 354 passed; two PostgreSQL-only row-lock concurrency tests skipped on SQLite.
- New fictional setup checks: two passed, including no seeded accounts or outgoing mail, refusal to overwrite scores, and refusal to populate a real competition.
- JavaScript folder upload, replay callback, spreadsheet paste/Undo/time checks: ten passed.
- Django system check: no issues. Migration consistency check: no changes detected.
- Fresh isolated bootstrap: fictional roster only, no scores or accounts.
- Gitleaks 8.30.1 scanned the staged release export with redacted reporting: no leaks found.
- Additional review checks source paths, production access markers, personal-address strings, binary metadata and excluded file types. Gmail addresses in provider tests are synthetic test values; test and CI passwords/keys are explicitly non-production fixtures.
- PDF pages and documentation screenshots were visually inspected.

The GitHub workflow runs the suite against PostgreSQL, including the concurrency tests, and audits dependencies. Its result is visible in the repository's Actions tab. Docker is not available on the preparation Mac, so the Compose launch was not executed there. HTTPS, DNS, SMTP, external storage and an operator's backup/restore procedure must be verified on the operator's infrastructure.

These are release-preparation checks, not a guarantee of complete security. No live competition data, website settings or outgoing emails were changed during preparation.

## Before public publication

1. Review the source, screenshots, MIT license and third-party notices.
2. Review the GitHub workflow result and any reported dependency advisories.
3. Review the linked public YouTube walkthrough, chapters and English captions.
4. Approve changing repository visibility to public separately. No visibility change is automatic.
