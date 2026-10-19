# Writing a feature module

Phases 2 to 4 are built as feature modules on top of a shared platform. Each
module owns its own directory on the backend and the frontend. Modules talk to
each other only through the contracts at the end of this document.

## Layout

```
backend/taxng/modules/<name>/
  __init__.py      # optional init(services): register adapters, hooks, events; set services.modules["<name>"]
  schema.sql       # CREATE TABLE IF NOT EXISTS ...  (applied automatically, in module-name order)
  service.py       # domain logic: plain functions/classes over services.db
  routes.py        # @route handlers (imported automatically at startup)
  adapters.py      # Sandbox<Kind> and Production<Kind> adapters, if the module integrates externally
backend/tests/modules/test_<name>*.py
frontend/src/modules/<name>/
  site.tsx         # export const siteModule: SiteModule (public pages, hash routes)
  app.tsx          # export const appModule: AppModule  (signed-in pages under /app)
  api.ts           # typed client using ../../http
rules/parameters/*.yaml, rules/tests/*.yaml       # new tax rules and worked examples (compliance only)
content/<name>/ or content/<core>.d/*.yaml         # module content (provisions.d, guides.d, news.d are merged into the library)
```

Startup (`taxng/services.py`) imports every package under `taxng/modules`,
calls `init(services)` if it exists, and imports `routes`. The frontend
registry (`frontend/src/modules/registry.ts`) already imports every module's
`site.tsx` and `app.tsx`.

## Backend rules

- **Handlers**: `@route("POST", "/api/<area>/{id}")` on
  `def handler(services, request, params) -> (status, body) | Reply`. Read the
  caller from `request.principal`.
- **Access**: start every protected handler with `require_user`,
  `require_org(principal, org_id, roles)` (non-members get 404),
  `require_staff(principal, *roles)` or, for API keys, `require_scope`. All of
  these live in `taxng.platform.access`. Role tuples: `CAN_EDIT` (owner,
  preparer), `CAN_REVIEW` (owner, reviewer), `CAN_ADMIN` (owner).
  Personal data is filtered by `user_id = principal.user_id`, organisation data
  by `org_id`. Never skip the filter.
- **Errors**: `raise Invalid("field: message")` (422),
  `Conflict("message")` (409), `NotFound` (404), `Forbidden` (403) and
  `Unauthorized` (401). The calculators' `InputError({...})` also maps to 422.
  The router does the mapping.
- **Audit**: every state change that matters to a taxpayer, an adviser, an
  editor or money calls
  `services.audit.record(action, entity, entity_id, actor_id=..., org_id=..., data={...})`.
  Keep personal data out of `data`.
- **Money**: use `Decimal` throughout. The API returns decimal strings
  (`"1500.00"`) or integer kobo where a payment provider needs them. Never use
  floats.
- **No figures in code**: tax rates, thresholds and due-date rules live in
  `rules/parameters` or `rules/obligations` and are read through
  `ParameterView` or `services.tree`. Commercial prices live in content files
  marked `[TBC]`, never in code.
- **Integrations**: subclass `taxng.platform.adapters.Adapter`. The sandbox
  version is deterministic. The production version calls
  `self.not_configured("what is needed")`. Register both with
  `services.adapters.register(Sandbox, Production)` in `init`. Every response
  that comes from an adapter includes `"mode": adapter.mode`. A sandbox result
  is never labelled as filed, paid or verified for real.
- **Webhooks in**: verify the HMAC signature with
  `taxng.platform.util.verify_signature`. Inbound webhooks carry no session,
  so the CSRF guard does not apply.
- **Notifications**: `services.notifier.send(channel, recipient, body, subject=...)`.
- **Files**: use the platform `/api/files` endpoints (`org_id` scoped) or
  `services.files`.
- **Analytics**: `taxng.store.register_events({"name": {"allowed_prop"}})` at
  import time, then call `services.store.record_event`.
- **IDs**: `taxng.platform.util.new_id("prefix")`. Timestamps:
  `iso()` (UTC).

## Tests

```python
from ..helpers import ServicesTestCase, create_org, add_member

class Workflows(ServicesTestCase):
    def test_x(self):
        alice = self.client("alice@example.com")          # real OTP sign-in
        status, body = alice.post("/api/...", {...})       # sends cookie + CSRF header
```

Run from `backend/` with `python3 -m unittest discover -s tests -t .`. Every
module needs tests for:

- access control: anonymous gets 401, non-members get 404, wrong roles get 403
- each state-machine transition
- one cross-tenant leakage attempt per tenant-scoped resource

If a test depends on another module that may not exist yet, use
`unittest.skipUnless("<other>" in services.modules)`.

## Frontend rules

- Import `http`, `qs`, `fileToBase64` and `ApiError` from `src/http.ts`. The
  signed-in app sends cookies and the CSRF header automatically.
- Reuse `components/ui.tsx` (`MoneyField`, `SelectField`, `CheckField`,
  `Notice`, `ReviewBadge`, `useLoad`, `Loading`), `components/ResultView.tsx`,
  `components/Figures.tsx` and `app/core.tsx` (`PageHead`). Reuse the existing
  CSS classes: `card`, `cards`, `grid-2`, `table`, `table-wrap`, `list`,
  `pill pill--ok|warn|bad|muted`, `btn btn--ghost|small|danger`, `tabs`,
  `field`, `notice`, `sponsored-label`, `ad-slot`. Put any new CSS in
  `src/modules/<name>/<name>.css`. Don't import it from TypeScript;
  `build.mjs` appends every module stylesheet to `styles.css`.
- App routes are relative to `/app` (for example `"/workspaces/:orgId/returns"`).
  `AppContext` provides `me`, `meta`, `orgId`, `org`, `setOrgId`,
  `refreshMe` and `params`. Show sandbox mode wherever an adapter result is
  displayed.
- Public routes are hash routes on the main site. Never load third-party
  scripts. Ads render only on the public site, never in `/app`.
- Accessibility: label every input, use `aria-live` for results, and keep pages
  usable at 390px width.

## Build and check in this sandbox

```
cd backend && python3 -m unittest discover -s tests -t .
cd frontend && NODE_PATH=/home/claude/.npm-global/lib/node_modules node build.mjs
# Typecheck with a stand-in for React types (the real @types/react is used in CI):
/home/claude/.npm-global/lib/node_modules/typescript/bin/tsc -p /tmp/claude-0/-home-claude/6ced03ac-08d2-5481-adc1-5b24fb3fb92e/scratchpad/tsshim/tsconfig.json --noEmit \
  | grep -v TS7006 | grep -v "Property 'key' does not exist" | grep -v "is not assignable to type '{" | grep -v "^  "
```

There is no network access to PyPI or npm. Use only the Python standard
library plus starlette, uvicorn and pyyaml, and on the frontend only react
and react-dom.

## Cross-module contracts

Each module sets `services.modules["<name>"] = <object>` in `init`. Other
modules look it up when they need it and must cope with it being absent.

### compliance (`services.modules["compliance"]`)
- `obligations_for(facts: dict, year: int) -> list[dict]`. Each item:
  `{id, tax, title, frequency, period, due_date (ISO), provision, evidence: [str], applies_because: str, review_status}`.
  Facts keys (all optional): `entity_type` (`individual|company|sole_proprietor|partnership|nonprofit`),
  `state`, `has_employees`, `employee_count`, `annual_turnover`, `fixed_assets`, `sells_taxable_supplies`,
  `makes_wht_payments`, `has_rental_income`, `has_foreign_income`, `has_capital_gains`,
  `is_professional_services`, `non_resident`.
- `account_summary(user_id: str) -> dict`: the user's saved profile facts and their latest health-check findings by
  dimension (no raw document data). Used by Tax AI (AI-04) and by advisory intake.

### billing (`services.modules["billing"]`)
- `create_checkout(*, payer_user_id, org_id, purpose, reference_id, amount_kobo, description) -> dict`
  returns `{checkout_id, url, mode}`. `purpose` is one of `subscription | course | advisory | sponsorship | advertising`.
- `register_payment_handler(purpose: str, fn: Callable[[services, dict], None])`. Billing calls
  `fn(services, payment)` once a verified provider webhook marks the payment paid. Commercial payments only:
  tax remittances never pass through billing.

### workspace (`services.modules["workspace"]`)
- `org_summary(org_id: str) -> dict`: organisation profile facts, open returns by status and upcoming obligations
  (for AI-04 and dashboards).

### einvoicing (`services.modules["einvoicing"]`)
- `import_invoices(org_id: str, actor_id: str, invoices: list[dict], *, source: str) -> dict`, used by ERP
  connectors. Idempotent on `(org_id, source, external_id)`.
