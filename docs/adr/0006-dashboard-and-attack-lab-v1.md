# ADR 0006 — Dashboard and Attack Lab v1

## Status

Accepted (2026-06-22). Implemented and verified end-to-end on 2026-06-22 against the
local Compose `observability` profile (130 unit and integration tests passing, Jaeger
smoke verification passing, twelve deterministic Attack Lab scenarios exercising the
real execution pipeline, no unique synthetic secret observed in DB, logs, audit, traces,
metrics, API responses, or rendered HTML).

## Context

ToolWatch already provides a trusted tool registry, agent sessions, a deterministic
security pipeline, append-only audit history, OpenTelemetry traces, Prometheus-compatible
metrics, and an optional Jaeger Compose profile. Developers need a way to inspect
sessions, tool-call timelines, sanitized arguments and results, matched rules, audit
events, and traces, and to reproduce known attack categories deterministically.

The dashboard must add operational visibility without adding new attack surface. It must
not weaken the security pipeline, must never display raw payloads, and must not require
adding a JavaScript build pipeline. The Attack Lab must exercise the same execution path
real callers use, and must not accept arbitrary tools or payloads.

## Decision

### Server-rendered Jinja2 + HTMX

The dashboard is a server-rendered presentation adapter under `src/toolwatch/web/`. It
uses FastAPI, Jinja2 templates with autoescape, a small set of HTMX behaviors for
fragment replacement, vanilla CSS, and no inline JavaScript. There is no client-side
state-management library, React, Vue, Next.js, Node toolchain, or npm dependency. HTMX
is vendored as a pinned local static asset and served by the FastAPI static-files mount;
no third-party CDN is used in the default configuration.

Templates receive dedicated immutable view models. Templates never receive SQLAlchemy
entities. Web routes call read-only application query services and the existing
application services; they never run database queries directly. Domain and application
layers do not depend on Jinja2 or HTMX.

### No frontend build system

The MVP scope does not justify a Node-based build pipeline. CSS is hand-written and
served as is. HTMX is shipped as a pinned, reviewed copy under `web/static/`. Removing
the build pipeline removes a large supply-chain attack surface from a dashboard that
exists to expose security-relevant data.

### Static immutable Attack Lab registry

`src/toolwatch/attack_lab/` contains a frozen tuple of `AttackScenario` values built at
import time and exposed through `MappingProxyType`. Scenarios cannot be added or
modified at runtime through any public API. The dashboard only renders scenarios from
this registry and only executes them by ID. There is no endpoint that accepts arbitrary
tools, arbitrary arguments, arbitrary payloads, or arbitrary adapter selection. Each
scenario runs through the real ToolWatch execution pipeline (the public local API), so
no scenario can bypass the security boundary that protects normal callers.

### Dashboard read-only default until authentication exists

The dashboard does not implement authentication, authorization, or human approvals in
this milestone. As long as no authentication exists, the dashboard remains read-only
except for one explicitly gated state-changing action: running a registered Attack Lab
scenario. That action is disabled when `ATTACK_LAB_ENABLED=false`. Rule editing is not
exposed through HTML in this milestone. CSRF tokens are not required because no
authenticated session cookie exists; nevertheless, the only state-changing endpoint:

- accepts only `application/x-www-form-urlencoded` POSTs from same-origin HTML forms
  (no JSON, no `hx-vals` with untrusted serialized JSON);
- relies on a strict same-origin CSP (`form-action 'self'`, `frame-ancestors 'none'`);
- is documented as not safe to expose to a public Internet user.

Documentation warns that the dashboard must bind only to existing API configuration and
must not be exposed to the public Internet.

### Browser security controls

All `/ui/*` HTML responses set:

- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none';
  frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(),
  interest-cohort=()`
- `X-Frame-Options: DENY`
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Resource-Policy: same-origin`
- `Cache-Control: no-store`

The dashboard never renders raw prompts, raw arguments, raw results, secrets, full HMAC
fingerprints, adapter configuration, database URLs, raw exception messages,
authorization headers, cookies, or internal filesystem paths. Sanitized JSON is
pretty-printed, size-bounded, and rendered inside `<pre>` with autoescape enabled. Tool
output is never rendered as HTML and never interpolated into attributes.

### Jaeger linking

Tool-call detail constructs an external Jaeger link only when:

- `JAEGER_UI_PUBLIC_URL` is configured in trusted configuration;
- the trace ID comes from a persisted audit event (not from a request parameter);
- the trace ID matches the W3C lowercase 32-hex pattern and is not the zero trace.

The link uses `rel="noopener noreferrer"` and `target="_blank"`. When either the
configured URL or the validated trace ID is missing, no link is shown.

## Consequences

- No JavaScript build pipeline. Faster review, smaller supply-chain surface; the
  trade-off is hand-written CSS and no advanced client-side ergonomics.
- A small fixed Attack Lab registry. New scenarios require a code review and a
  deployment, which is the desired security property; users cannot escalate by
  submitting custom payloads.
- A read-oriented dashboard. Operators inspect state but do not mutate it from the
  browser in this milestone. State-changing capabilities (rule editing, approvals,
  multi-tenant project switching) are deferred until authentication and session/CSRF
  primitives are added in a future milestone.
- The dashboard remains safe to expose only on developer machines or internal networks
  where access is already controlled. README and threat model document this explicitly.

## Alternatives considered

- **React or HTMX + npm bundling.** Rejected. Adds a Node toolchain, lockfile, and a
  long supply-chain tail to a milestone that only needs server-rendered HTML.
- **Persist Attack Lab runs in a dedicated table.** Rejected for v1. Sessions, tool
  calls, risk flags, and audit events already capture everything observable about a
  scenario run; an `attack_runs` table would mostly duplicate that data.
- **Dynamic user-submitted scenarios.** Rejected. The Attack Lab must use the trusted
  registry and trusted adapter allowlist; arbitrary user-submitted scenarios would
  re-introduce the very attack surface ToolWatch exists to mitigate.
- **CSRF tokens bound to a synthetic browser session.** Rejected for v1 because no
  authenticated session exists; adding a cookie-based session purely to defend a single
  endpoint would broaden the attack surface (cookie theft, session fixation) without
  any auth benefit. Same-origin CSP plus form-only POST is sufficient for the local
  developer-tool deployment model.

## Implementation summary (2026-06-22)

Delivered:

- `src/toolwatch/web/` — `router.py`, `view_models.py`, `presenters.py`, `security.py`,
  `filters.py`, `dependencies.py`, full `templates/` tree (base, dashboard, sessions
  list/_table/detail, tool_calls timeline_item/detail, rules list/_table, audit
  list/_table, attacks index/detail/result, components pagination/risk_badge/
  status_badge/empty_state/error), and `static/` with `toolwatch.css` and a vendored
  `htmx.min.js`.
- `src/toolwatch/attack_lab/` — `models.py`, `registry.py`, `scenarios.py` (twelve
  deterministic scenarios: safe-github-read, sensitive-email-input, destructive-sql,
  multiple-sql-statements, invalid-arguments, unknown-tool, disabled-tool,
  indirect-prompt-injection, secret-in-output, persistent-replay, adapter-timeout,
  adapter-failure), `runner.py`, `__main__.py`.
- `src/toolwatch/application/queries.py` — `DashboardQueryService`.
- Config additions in `src/toolwatch/config.py`: `DASHBOARD_ENABLED`,
  `DASHBOARD_PREFIX`, `DASHBOARD_PAGE_SIZE`, `DASHBOARD_MAX_PAGE_SIZE`,
  `DASHBOARD_REFRESH_SECONDS`, `ATTACK_LAB_ENABLED`, `JAEGER_UI_PUBLIC_URL`.
- Dashboard mount wired in `src/toolwatch/main.py`.
- New tests: `tests/unit/web/test_presenters.py` (10), `tests/unit/web/test_routes.py`
  (12, includes XSS regressions and disabled-dashboard 404),
  `tests/unit/web/test_attack_lab_registry.py` (5),
  `tests/integration/test_attack_lab.py` (12, against PostgreSQL Testcontainers).
- Make targets: `attack-list`, `attack-run SCENARIO=…`, `attack-run-all`, `test-web`,
  `demo`, `verify-jaeger`.
- `scripts/verify_jaeger.py` — bounded-retry smoke check; passes against the running
  Compose `observability` profile.
- Hatchling wheel packaging updated to include templates and static assets.
- Compose, `.env.example`, README, `docs/architecture.md`, `docs/threat-model.md`,
  `docs/testing.md` updated.

Verified:

- `make check` → ruff lint and format checks pass; `pyright` 0 errors; 130 tests pass
  (118 unit, 12 attack-lab integration plus the existing 22 integration tests).
- Dashboard live under Docker Compose at `http://localhost:8000/ui` with the full
  documented CSP, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `X-Frame-Options`, COOP, CORP, and `Cache-Control: no-store` headers.
- Live XSS probe: `<script>UNIQUE-FINAL-SEC-1343b907</script>` placed in an email
  subject renders only as `&lt;script&gt;…&lt;/script&gt;` in the dashboard. No raw
  `<script>` tags appear in rendered HTML. The probe does not appear in `/metrics`,
  Jaeger traces, or audit events. A `Bearer UNIQUE-FINAL-SEC-…-token` value in the
  email body was fully redacted on every surface.
- `scripts/verify_jaeger.py` reports `allowed_call_succeeded`, `blocked_call_blocked`,
  `jaeger_allowed_adapter_span`, `jaeger_no_blocked_adapter_span`, and
  `no_secret_in_jaeger` all PASS.
- CLI: `python -m toolwatch.attack_lab list` lists twelve scenarios; per-scenario
  `run` reports structured assertion results.
