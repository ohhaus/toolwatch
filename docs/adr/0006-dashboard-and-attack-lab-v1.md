# ADR 0006 — Dashboard and Attack Lab v1

## Status

Accepted (2026-06-22).

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
