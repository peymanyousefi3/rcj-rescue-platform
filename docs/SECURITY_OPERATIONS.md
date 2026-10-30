# Security and operational readiness

Developed and maintained by **Peyman Yousefi**. This guide applies to the open-source platform. It does not change the operating ASR event or certify a particular hosting provider.

## Public versus private

Published replay HTML, scripts, coordinates, animation/result JSON, scene, textures and meshes are public playback assets. Released maps, scores, schedules and public announcements may also be public. A JSON suffix alone does not make a file confidential.

**Private by default:** team controller source code, team submission JSON, TDPs and other team-uploaded documents, private videos, quarantine files, complaints and attachments. Team and authorized administrator access is enforced on the server. A separate explicitly published organizer copy has its selected audience.

Recording uploads must contain only the recording export. The validator rejects unrelated controller/document/credential files rather than silently publishing them. Existing manifests are filtered at serving time without deleting stored originals. Old local/S3 storage paths remain readable; new manifests retain the storage provider's actual object IDs so Drive uploads work through the same authorized routes.

## Before accepting real participant data

- Use HTTPS and a fresh private configuration. Never commit `.env`, keys, backups or real submissions.
- Use the restricted `arena_app` database role for app/worker and a separate one-off migration role. Do not give the app the database bootstrap password.
- Enroll production staff in MFA. The production default requires it. Keep recovery codes privately; local demonstration setup explicitly disables enforcement.
- Confirm recipient removal, anonymous denial, cross-team denial, quarantine deadlines and ranking-release controls on a disposable staging event.
- Validate ingress with a spoofed `X-ASR-Client-IP` header. Caddy overwrites it and supplies a private shared proxy token; arbitrary direct headers are ignored. Changing HTTPS trust alone does not enable client-IP trust.
- If a CDN/WAF sits in front of Caddy, configure its documented trusted proxy ranges and verified client-IP handling. Restrict origin access to that edge. Do not trust arbitrary `X-Forwarded-For` values.
- Configure a dedicated mail sender with TLS and SPF/DKIM/DMARC. Invitations/resets never use announcement observer CC/BCC. Keep staging SMTP paused or use a local capture service.
- For Drive, use a dedicated private service-principal folder; no Anyone/link permissions. For S3, keep the bucket private, block public access, restrict the principal to its prefix and use HTTPS. Do not turn private objects into a static public directory.
- Inspect actual registrar/hosting/SSH accounts, firewall, OS patches, external storage ACLs and encryption. A source repository cannot prove those controls.

## Resource budgets

The defaults accommodate large competition files: 1 GiB per file, 2 GiB per batch, 5,000 files, 20 GiB retained ordinary assets per team, 512 MiB extracted replay data, 64 MiB per parsed validation document, 16 million image pixels and a 512 MiB free-disk reserve. Set the `UPLOAD_*`, `RECORDING_MAX_EXTRACTED_BYTES` and `VALIDATION_MAX_BYTES` variables to suit the event. Keep the proxy and application batch budgets aligned. Private submissions still accept arbitrary file types and multiple files.

Limits use actual streamed bytes, not only browser-supplied size metadata. Team storage includes retained history; removing a visible file is not a promise that stored history has been purged. Contact the operator before increasing quotas. Multipart temporary files use a private disk directory, not a large RAM filesystem. Backups exclude in-progress temporary uploads.

The supplied Compose services have CPU, memory, process and log budgets. The application runs without root, with a read-only root filesystem and dropped capabilities. Size the host for all services together (an 8 GiB starting allocation is reasonable for these example limits, then measure). Container limits are containment, not a capacity guarantee. A database pool is bounded per process; account for all Gunicorn workers, background workers, migration connections and replicas when setting server connection limits.

## Health, monitoring and abuse

- `/health/` checks database connectivity; `/ready/` also checks private-storage reserve. Responses expose no detailed dependency or participant information and are not cached.
- Caddy probes readiness. Worker health uses a private heartbeat plus scanner connectivity; a mail provider outage does not remove public browsing from service.
- Run `python manage.py check --deploy --fail-level WARNING` and `python manage.py check_readiness --json` using the **runtime** role. The latter is a read-only database check and lists external evidence still required.
- Alert on non-200 readiness, stale worker health, old pending malware scans, mail backlog/retry age, HTTP 5xx/429 rates, CPU/memory, free disk, database connections, backup age and certificate/domain expiry. Configure an actual alert destination and test receipt.
- Application quotas group related routes, so changing resource IDs does not reset a quota. Host/edge connection limiting and upstream DDoS protection remain necessary for volumetric attacks. Do not load-test a live competition without a separate authorized plan.
- The mail queue has admission backpressure and bounded retries. SMTP is at-least-once; stable Message-IDs reduce duplicate delivery but cannot guarantee exactly-once receipt.

## Recovery and rollback

On a Linux or macOS operator host, install Docker Compose and the official [age](https://age-encryption.org/) CLI on the operator machine. Generate an age identity on a secure machine; keep the private identity off the production host and keep a separately protected recovery copy. Put only the public recipient on the backup host.

During a scheduled maintenance window:

```sh
python3 scripts/recovery.py backup --project YOUR_PROJECT --env /private/path/event.env \
  --recipient age1YOUR_PUBLIC_RECIPIENT --output /private/backups/event-YYYYMMDD.age \
  --confirm-maintenance --temp-dir /private/encrypted-temporary-storage
```

A per-project lock prevents overlapping recovery operations. This stops only previously running app/worker services, captures a database dump and private volume together, includes the private configuration inside the encrypted archive, and restarts those services in a `finally` block. Ensure there are no other writers or simultaneous migrations. Plaintext staging needs an owner-only directory on an encrypted filesystem. Protect the output directory and copy the **encrypted** archive off-server to an immutable/versioned location. Scheduling, off-host transfer and alert delivery must be configured and proven by the operator.

Practice recovery on a separate host or a new isolated project. Check out the exact source commit recorded in the backup first:

```sh
python3 scripts/recovery.py restore --project rcj-restore-practice \
  --backup /private/backups/event-YYYYMMDD.age --identity /private/offline/recovery.agekey \
  --destination /private/recovery/new-practice --temp-dir /private/encrypted-temporary-storage
```

Restore refuses any existing destination or project containers, volumes or networks. It checks archive members, integrity and source version, and restores into new volumes. It does **not** start the application or mail worker. For a rehearsal, block outbound SMTP and review hostnames, storage destinations and credentials before starting anything. Local-volume backups do not copy external Drive/S3 object contents: back those up separately with provider versioning/retention and prove recovery using the same object IDs. The included CI drill uses a new local-volume project and synthetic data only.

Record recovery-time and acceptable-data-loss targets before the event. Keep several known-good encrypted backups; test a full restoration and record duration, restored file hashes and record counts. Do not assume an image rollback reverses a schema migration. Roll back code only when the schema is compatible; otherwise restore a coordinated backup to a **new** environment and verify it before switching traffic. Never delete the event's volumes during an upgrade.

## Privacy, retention and incident procedure

The organizer must document data purposes, authorized roles, hosting jurisdiction, child/guardian requirements, retention periods and a private contact channel. The repository supplies technical controls, not a jurisdiction-specific legal policy. Avoid unnecessary phone numbers, identification or personal information in public announcements.

Keep ordinary team submissions private unless a separate copy is deliberately published. Set retention for submissions, account/contact records, sent mail, audit logs and encrypted backups before collecting them. Append-only audit records need a controlled archival/retention procedure; do not disable the audit trigger to make a routine deletion easier. A request for correction/deletion must cover storage, mail copies and backup retention as well as the visible record. Do not purge competition history during a security upgrade.

If compromise is suspected: restrict ingress, preserve a protected evidence copy, revoke affected credentials/sessions, inspect publication/audit changes and provider access logs, assess affected records and applicable notification duties, restore to a clean isolated environment if needed, then verify the original issue is fixed. Do not publish credentials or participant data in an issue. Use the repository's private vulnerability report channel. Assign incident ownership and provider escalation contacts before the event.

## Verification records

Record date, source commit, environment, owner, test, expected result, observed result and evidence for every check. CI tests synthetic application permissions, PostgreSQL concurrency, dependency hashes, security scanning, the container runtime and encrypted local-volume recovery. Operational evidence still required includes upstream DDoS mitigation, real DNS/TLS/mail delivery, cloud storage permissions/backups, host hardening, a measured event-scale load profile, recovery timing and a complete browser/accessibility matrix. A checklist entry remains unverified until its actual evidence exists.
