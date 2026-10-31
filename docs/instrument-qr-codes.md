# Instrument QR codes

Configure `PUBLIC_QR_BASE_URL` with the permanent origin serving this application
(e.g. `https://instruments.example.org`, without a trailing slash or path).
Production accepts HTTPS only. Development permits an explicitly configured HTTP
origin such as `http://127.0.0.1:8000`. Invalid values fail settings validation at
startup. An unset value leaves normal application operations available but QR
requests return HTTP 503; no printable code is produced. Set the production domain
before printing labels. Incoming Host, Forwarded and X-Forwarded-Host headers are
never used to generate URLs.

Run `uv run alembic upgrade head` before deploying. The migration assigns each
existing instrument a random UUID and enforces uniqueness, non-null values and
immutability. New instruments receive UUIDv4 identifiers. Internal integer primary
keys and existing API responses remain compatible. Create/update request schemas
never accept `public_id`.

Authenticated administrators and employees can download
`GET /api/v1/instruments/{id}/qr-code.svg`. Its Content-Location header identifies
the encoded URL: `{PUBLIC_QR_BASE_URL}/i/{public_id}`. The SVG contains only that
URL, with a white background, black modules and a four-module quiet zone. Save it
and print using a browser or label software, preserving aspect ratio and the quiet
zone. Avoid very small labels; verify a physical sample with the intended scanner
before a print run. No customer data, instrument notes, credentials or session
tokens are encoded. The public UUID is a durable identifier, not an access token.
The SVG download is private and must not be cached.

The stable `/i/{public_id}` route requires the same session and staff role as the
instrument API. After authorization it redirects to the current instrument record
API. Unknown identifiers return 404 after authorization. Without a session it
returns 401; customers cannot access it (403). This API repository currently has
no browser login or instrument-detail UI: users must already have an authenticated
browser session. A future application UI can replace the redirect destination
without reprinting labels; it must retain backend authorization. The configured
origin must route `/i/` to this application and support the intended session/login
integration.

Keep the hostname and route stable, including during hosting-provider changes.
If a domain must change, retain the old domain and securely route its `/i/` URLs;
otherwise existing labels must be replaced. Physical labels are visible to anyone
near the instrument, so treat the URL as public. Random identifiers reduce casual
enumeration but do not replace access control. Deleted instruments return 404;
archiving customers or repair records does not change instrument links. Database
administrators can bypass database triggers; immutability is an application and
ordinary-database-write guarantee, not tamper-proof storage.
