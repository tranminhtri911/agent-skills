# Attack catalog: where it happens, how to prevent it, how to test it

Static rule ids in brackets come from `ds.py check-code`; they are signals, not proof.

## XSS (reflected, stored, DOM)
- **Where:** templates/components rendering user data; `innerHTML`, `dangerouslySetInnerHTML`, `v-html`, `{!! !!}`, `Html.Raw`, `document.write`; `res.send` with request data; URLs in `href/src`.
- **Prevent:** framework auto-escaping; context-aware output encoding; sanitize required HTML (DOMPurify/bleach); Content-Security-Policy (no `unsafe-inline`); `HttpOnly` cookies; validate URL schemes (`http/https` only).
- **Test:** store `<img src=x onerror=alert(1)>` and `"><svg onload=alert(1)>` as synthetic data; assert it renders as text (DOM assertion) and no script executes.
- **Signals:** [JS-UNSAFE-HTML] [SFC-UNSAFE-HTML] [JS-DOCUMENT-WRITE] [JS-REFLECTED-XSS] [PHP-REFLECTED-XSS] [PHP-BLADE-RAW] [CS-HTML-RAW] [PY-XSS-MARK-SAFE] [PY-XSS-AUTOESCAPE-OFF]

## SQL injection / NoSQL injection
- **Where:** raw queries built with f-strings/concatenation/template literals; `whereRaw`, `$queryRawUnsafe`, `DB::raw`; dynamic `ORDER BY`; Mongo filters taken from `req.body` (`{"$gt": ""}`).
- **Prevent:** bound parameters everywhere; allowlists for identifiers; ORM query builders; typed/cast filters; reject keys starting with `$`; least-privilege DB user.
- **Test:** inputs `' OR '1'='1`, `1; DROP TABLE x--`, `{"$ne": null}` against the local app; assert normal "not found"/validation errors and unchanged data.
- **Signals:** [PY-SQL-STRING-BUILD] [JS-SQL-STRING-BUILD] [PHP-SQL-STRING-BUILD] [JAVA-SQL-STRING-BUILD] [GO-SQL-STRING-BUILD] [RUBY-SQL-INTERPOLATION] [JS-PRISMA-UNSAFE-RAW] [JS-NOSQL-INJECTION]

## Command / template / expression injection
- **Prevent:** argv lists without a shell; never `eval`/`exec`/`new Function`; never render user input as a template (SSTI); safe YAML/XML loaders.
- **Signals:** [PY-SHELL-TRUE] [PY-EVAL-EXEC] [JS-EVAL] [PHP-SHELL] [PY-SSTI] [PY-UNSAFE-YAML]

## Path traversal ("dot-dot-slash" `../`) and file upload
- **Where:** download/preview endpoints, file names from users, archive extraction (zip slip), includes (`include $_GET['page']`).
- **Prevent:** server-generated storage names; resolve the path and check it stays inside the base dir (`realpath`/`resolve()` + prefix check); reject `..`, absolute paths, symlinks; validate content type by sniffing; size and decompression limits; store uploads outside the web root; scan if required.
- **Test:** `../../etc/passwd`, `..%2f..%2f`, `%2e%2e/`, absolute paths, a zip containing `../evil`; expect 400/404 and no file outside the base dir touched.
- **Signals:** [PY-PATH-TRAVERSAL] [JS-PATH-TRAVERSAL] [PHP-FILE-INCLUSION] [PHP-PATH-TRAVERSAL] [JVM-PATH-TRAVERSAL] [PY-ARCHIVE-SLIP]

## SSRF
- **Where:** webhooks registration, URL previews, image fetchers, PDF renderers, import-from-URL.
- **Prevent:** allowlist of hosts/schemes; resolve DNS and block private, loopback, link-local and metadata ranges (169.254.169.254, fd00::/8); re-check after redirects or disable redirects; timeouts and size limits.
- **Test:** `http://127.0.0.1:…`, `http://169.254.169.254/latest/meta-data`, a host resolving to 10.x, a redirect to an internal URL → all rejected (use a local fake server, never real metadata endpoints).
- **Signals:** [PY-SSRF] [JS-SSRF] [PHP-SSRF]

## Open redirect
- **Prevent:** only relative paths or allowlisted hosts for `next`/`returnUrl`.
- **Signals:** [PY-OPEN-REDIRECT] [JS-OPEN-REDIRECT] [PHP-OPEN-REDIRECT] [JVM-OPEN-REDIRECT]

## CSRF
- **Prevent:** framework CSRF tokens for cookie sessions; `SameSite=Lax/Strict`; state changes never via GET; check `Origin` on sensitive endpoints.
- **Signals:** [PY-CSRF-EXEMPT]

## Broken authorization (IDOR / BOLA / BFLA)
- **Prevent:** every query scoped by tenant/owner from the authenticated principal; policy checks per action; 404 for objects of other tenants; admin functions behind role checks on the server.
- **Test:** user A requests user B's object id, list endpoints with another tenant's filter, regular user calls admin endpoint → 403/404 and no data leak (including counts).

## Mass assignment
- **Prevent:** explicit DTO/serializer fields; protected fields (role, price, owner, tenant, status) never bound from input.
- **Signals:** [PY-MASS-ASSIGNMENT] [JS-MASS-ASSIGNMENT] [PHP-MASS-ASSIGNMENT] [JS-PROTOTYPE-POLLUTION]

## Deserialization / XXE
- **Prevent:** JSON with schema validation; no `pickle`/`unserialize`/`BinaryFormatter` on untrusted data; XML parsers with DTD/external entities disabled (defusedxml).
- **Signals:** [PY-UNSAFE-DESERIALIZE] [PHP-UNSERIALIZE] [PY-XXE] [JAVA-XXE]

## Authentication, sessions, JWT, cookies, CORS
- **Prevent:** verified signatures with an explicit algorithm list; check `exp`, `aud`, `iss`; short-lived access tokens + revocable refresh tokens; rotate session on login; generic login errors (no account enumeration); constant-time comparisons; `HttpOnly/Secure/SameSite` cookies; CORS allowlist without `*` + credentials.
- **Signals:** [PY-JWT-NO-VERIFY] [PY-JWT-NO-ALGORITHMS] [JS-JWT-DECODE] [JS-JWT-NONE] [PY-COOKIE-FLAGS] [JS-COOKIE-FLAGS] [PY-CORS-WILDCARD-CREDENTIALS] [JS-CORS-CREDENTIALS] [PY-WEAK-PASSWORD-HASH] [JS-WEAK-PASSWORD-HASH] [PHP-WEAK-PASSWORD-HASH] [PY-INSECURE-RANDOM] [JS-TOKEN-IN-STORAGE]

## DoS and abuse (rate limits, resource limits)
- **Where:** login/OTP/password reset/register (brute force, SMS cost), search/export, uploads, GraphQL depth, pagination without max, regexes on user input, zip/XML bombs, expensive endpoints without caching.
- **Prevent:** rate limits per account + per IP + per tenant (token bucket / sliding window, shared store such as Redis), 429 with `Retry-After`; request body/field/array size limits; max page size; query timeouts; bounded queues; regexes without nested quantifiers (or a linear-time engine) and input length limits; concurrency limits per user; cost budgets for paid APIs (SMS, email, AI).
- **Test:** `ds.py rate-limit-probe` on the local login endpoint; oversized body → 413; `limit=100000` → capped; slow-regex input → bounded time.
- **Signals:** [SEC-AUTH-NO-RATE-LIMIT] [PY-REDOS] [JS-REDOS] [PY-USER-REGEX] [JS-USER-REGEX]

## Secrets and logging
- **Prevent:** secrets from env/secret manager; never in code, logs, screenshots, URLs or error messages; redaction in logs; rotate anything ever committed.
- **Signals:** `ds.py scan-secrets` [SECRET-*], [JS-CONSOLE-LOG], [PY-DEBUG-ENABLED], [PY-INSECURE-SETTING]

## Security headers (web apps)
`Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `frame-ancestors`/`X-Frame-Options` (clickjacking), `Permissions-Policy`.
