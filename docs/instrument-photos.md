# Instrument photo management

## Architecture and API

Instrument photographs are private objects; PostgreSQL stores metadata and upload
intents in `instrument_photo`, never image binaries. R2 uses
`instruments/{instrument_public_id}/{random_photo_uuid}.{verified_extension}`.
Original filenames are metadata only. Neither keys nor storage locations appear
in public schemas. Existing instrument APIs and integer IDs remain unchanged.
The `StorageService` interface supports replacement and dependency overrides;
`R2Storage` uses boto3 with explicit credentials, TLS, SigV4, region `auto`, path
addressing, bounded network timeouts/retries and checksums only when required.
Conditional writes (`If-None-Match: *`) prevent overwriting existing objects.

| Method | Path below `/api/v1/instruments/{instrument_id}` | Behavior |
|---|---|---|
| POST | `/photos` | Multipart `files`, returns a list of created metadata (201) |
| GET | `/photos` | Active metadata, offset/limit pagination, X-Total-Count |
| GET | `/photos/{photo_id}` | Active photo metadata |
| GET | `/photos/{photo_id}/content` | Authenticated inline image stream |
| GET | `/photos/{photo_id}/download` | Authenticated attachment stream |
| DELETE | `/photos/{photo_id}` | Administrator-only recoverable deletion request |
| POST | `/photos/{photo_id}/restore` | Administrator-only restore within the recovery period |
| GET | `/photos/{photo_id}/retention` | Administrator-only lifecycle/hold/approval inspection |
| POST / DELETE | `/photos/{photo_id}/retention-hold` | Administrator-only hold creation/release |
| POST | `/photos/{photo_id}/purge-approval` | Explicit administrator review before eligibility |

Administrators and employees may upload/list/read/download. Only administrators
may request deletion; customers have no access. Existing session, HTTPS, CSRF and
role checks apply before upload parsing. Wrong-instrument photo IDs return 404;
there are no public photo URLs or signed-URL redirects. Responses use private,
no-store cache headers and content responses use nosniff. Deleted photos disappear
from normal listing, metadata and content routes. DELETE returns the same metadata
on repeated requests, without duplicate audit events. Listing sorts by uploaded_at
then ID, defaults to 100 results, permits 1–200, and rejects negative offsets.

## Private R2 configuration

Leave all four settings absent or empty to run without storage. Listing/metadata
and soft deletion remain available, while upload/content/download return 503.
Partial configuration or invalid endpoints fail application settings validation
at startup. All endpoints must be explicit HTTPS origins, without paths,
credentials, query strings or fragments. Literal placeholder values are not valid
configuration and must be replaced or commented out.

| Environment variable | Purpose |
|---|---|
| `R2_ENDPOINT_URL` | Account S3 endpoint for the bucket's jurisdiction |
| `R2_ACCESS_KEY_ID` | Bucket-scoped S3 access key ID |
| `R2_SECRET_ACCESS_KEY` | Corresponding secret, stored only in secret configuration |
| `R2_BUCKET_NAME` | `atelier-api-dev` locally; `atelier-api-prod` in production |

In Cloudflare, verify the bucket's actual jurisdiction before selecting its
endpoint. Default: `https://ACCOUNT_ID.r2.cloudflarestorage.com`; EU:
`https://ACCOUNT_ID.eu.r2.cloudflarestorage.com`; US:
`https://ACCOUNT_ID.us.r2.cloudflarestorage.com`; FedRAMP:
`https://ACCOUNT_ID.fedramp.r2.cloudflarestorage.com`. Use the dashboard-provided
endpoint; a location hint alone is not an EU jurisdiction restriction. See the
[Cloudflare authentication documentation](https://developers.cloudflare.com/r2/api/tokens/)
and [data location documentation](https://developers.cloudflare.com/r2/reference/data-location/).

Use a dedicated **Object Read & Write** API token scoped only to the appropriate
bucket. Development and production must have separate credentials. The backend
needs object get/put/head/delete; no bucket administration is needed. Disable
public access (`r2.dev` and public custom domains). Do not grant direct browser
access or configure storage CORS: clients access the authenticated backend only.
Do not configure automatic lifecycle deletion of documentation objects before
retention decisions are approved. Never commit `.env` or enable SDK debug/wire
logging in production. Rotate credentials without changing the bucket or endpoint.

A hash of endpoint and bucket is stored as an internal storage namespace, so a
configuration change cannot silently read a different bucket or discard pending
cleanup records. Migrating objects to another bucket/endpoint requires a reviewed
data migration and verification before updating namespaces. Keep the matching
configuration available to reconcile older pending uploads. Never share the same
object namespace between independently restored/cloned databases: use a separate
bucket for restore drills to avoid removing another environment's objects.

## Upload limits and image processing

Use repeated multipart `files` fields, at most ten files per request. Each original
and sanitized encoding must be at most **10,000,000 bytes (10 MB)**. The multipart
request cap is **101,000,000 bytes**, including headers and boundaries. Limits are
checked while parsing even without Content-Length; oversized requests/files are
413. Part headers are capped at 8 KB; malformed multipart bodies return 422.
Unsupported formats return 415, invalid images/filenames or excessive pixels 422.
Missing resources are 404, missing sessions 401, insufficient roles/CSRF 403;
storage/database failures return sanitized 503 errors.

Supported formats are JPEG, PNG and WebP. The decoder verifies actual content,
not the submitted MIME or extension; a valid image with incorrect hints is accepted
with its verified MIME type and extension. Each image is limited to 20 megapixels,
Pillow decompression-bomb checks remain enabled, and animations are rejected.
Images are decoded, oriented and re-encoded from clean pixels, stripping EXIF/GPS,
comments and ICC metadata. Originals are not retained. JPEG/WebP recompression can
change pixels, so this is condition documentation rather than original forensic
file preservation; agree on suitability for contractual evidence before use.
Download names use the verified suffix, preventing a disguised executable suffix.

Uploads spool to bounded temporary files; temporary disk is not persistent storage.
Only two decoder operations run concurrently per process. Image work, synchronous
SQL and boto3 calls execute in worker threads; image responses stream in 64 KiB
chunks and close storage connections. Reserve RAM for decoded pixel buffers,
temporary disk for concurrent requests, and configure deployment concurrency and
edge request/time limits for the available instance capacity. Slow-client and
aggregate-volume protection also requires deployment-level limits. If a storage
read fails after response headers have been sent, the stream terminates; clients
must retry rather than accepting a partial image.

## Consistency, cleanup and retention

The application validates the entire batch before any R2 writes, then commits
pending metadata/key reservations. It locks these rows during object writes and
the final transaction that marks the entire batch ready and appends upload audit
events. Pending photos never appear in ordinary APIs. Multi-file failure triggers
idempotent compensating deletion of reserved objects. If cleanup or PostgreSQL is
unavailable, pending records remain for retry; they are not silently forgotten.
If a database commit succeeds but its acknowledgement is lost, reconciliation
retains ready photos; a client can receive 503 despite a committed batch, so check
the photo list before retrying to avoid duplicates. There is no cross-system
transaction or automatic request-idempotency guarantee.

Run the trusted operator command regularly with the correct environment:

```bash
uv run atelier-photos-cleanup
```

It retries at most 100 pending intents older than 24 hours, skipping locked active
uploads. Repeat/schedule the command for larger backlogs and monitor the warning
`Photo upload compensation requires retry`. The 24 hours is an operational stale
upload grace period, **not a legal retention period**. Deleting a missing object is
safe. A failed object deletion preserves its metadata for another attempt. After
a database restore, review pending intents and storage consistency before running
cleanup; restore PostgreSQL and object backups as one coordinated recovery.

DELETE only sets status/deletion-request timestamp and administrator reference,
and records the audit action atomically. It never calls R2 delete. Already
soft-deleted documentation is never purged by the cleanup command. Permanent deletion is available only through the disabled-by-default purge CLI,
subject to the recovery period, retention holds and explicit approval described
below. Objects and relationships remain intact while soft-deleted, including when
customers/repairs are archived. Instruments with photo
rows cannot be hard-deleted (409, restrictive FK). Account deletion sets metadata
actor FKs to null; audit events retain historical actor IDs after deactivation or
deletion. Audits include photo ID, instrument ID and acting user, not filenames,
image data, storage credentials or URLs.

The workshop must approve its actual retention policy before enabling permanent
purging. See [photo retention and purge operations](photo-retention.md) for the
lifecycle, administrator restoration/holds/approval, separate purge command,
concurrency guarantees, recovery and Render scheduling. The recovery period is
not a statutory retention period; explicit per-photo approval is required because
the application cannot infer contractual or legal retention needs.

## Local development, Swagger and Render deployment

1. `uv sync --locked --dev` and configure the database following the existing setup.
2. Copy the commented R2 settings from `.env.example` into an untracked `.env`,
   replace placeholders, and use only `atelier-api-dev` credentials locally. Leave
   all four absent/empty when storage is not needed.
3. `uv run alembic upgrade head`; then `uv run fastapi dev`.
4. Open `/docs` in development. Log in using the existing `/api/v1/auth/login`
   flow. Swagger supplies the existing Origin/CSRF header integration and cookie.
   Select POST `/instruments/{instrument_id}/photos`, add one or more real image
   files under `files`, execute, and verify 201 metadata and upload audit entries.
5. List the photos; open content/download through the same authenticated browser.
   Confirm the stored object exists only in the private development bucket and
   anonymous requests fail. Sign in as admin to verify recoverable DELETE and POST restoration.
6. On Render, set `ENVIRONMENT=production`, production database/origin/session
   settings and all four R2 variables as environment secrets/configuration. Use
   `atelier-api-prod` with its own bucket-scoped token and jurisdiction endpoint.
   Apply migrations through the existing deployment procedure before new code
   serves requests. API docs remain disabled in production by the existing policy.
7. Schedule the cleanup command with the same database/storage configuration.
   Review monitoring, instance memory/disk/concurrency and request limits; maintain
   and test both database and object-storage recovery. No persistent Render disk
   is required for images.

Real-bucket smoke verification is still required: upload JPEG/PNG/WebP and a batch,
confirm format and metadata stripping, stream/download with cookies, check private
bucket denial, verify administrator-only soft deletion retains the object, and
exercise cleanup on deliberately failed *development* uploads. Do not run failure
injection or cleanup against production data. Storage behavior is tested with fake storage and boto3 Stubber; real R2 verification
is a separate deployment step, especially before enabling permanent purging.

## Automated checks

```bash
uv run pytest tests/photos tests/integration/test_instrument_photos.py
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
uv build
```

Use the dedicated PostgreSQL `TEST_DATABASE_URL` for integration tests. Tests
explicitly override local R2 configuration, use fake storage/Stubber, and require
no Cloudflare credentials or external storage network access. CI additionally
checks Alembic model consistency and installation/imports of the built wheel.
