# tax.ng — working notes for Claude Code

Nigerian tax platform (all four PRD phases), owned and licensed by Astound Innovation Hub.
Read README.md, docs/MODULES.md (module contract) and docs/DECISIONS.md before changing code.

## Commands
- Install: `make install` (pip install -e backend[dev]; npm install in frontend)
- Test: `make test` (backend unittest, incl. legislative worked examples in rules/tests)
- Lint/typecheck: `make lint` (ruff, mypy, tsc)
- Build web: `make web` · Run: `make run` → http://127.0.0.1:8000 (public) and /app/ (signed-in app)
- Demo data: `cd backend && python -m taxng seed` (demo mode only; sign-in code shows on screen)

## Non-negotiable rules
- No tax figures in code or content text. Rates, bands, thresholds and due-date rules live in
  `rules/parameters` and `rules/obligations` with a review_status; read them via ParameterView.
- Tax AI states no figure that did not come from a rules-engine tool call, and cites only retrieved
  provisions (guards in backend/taxng/ai/assistant.py). Never weaken these guards.
- No rule is `legal_approved` until two legal reviewers sign off (a test enforces this).
- Money is Decimal end to end; the API returns decimal strings.
- Every external integration is an adapter with sandbox and production forms
  (backend/taxng/platform/adapters.py). Sandbox results are never presented as real filings,
  payments or verifications. "File & Pay" stays hidden until an authorised filing adapter exists.
- Tenant data only through `require_org` (non-members get 404). API keys work on /api/v1 only.
- Audit every state change via services.audit; the audit table is append-only and hash-chained.
- Sponsored content: disclosure + ARCON reference before publishing; editorial approval never
  depends on payment; the label propagates to every surface.
- User-facing copy: no em dashes.

## Known next steps (see docs/DECISIONS.md)
- Migrate to the target stack: openfisca-core (D1), FastAPI (D2), Next.js (D3), PostgreSQL with
  row-level security (D5), hybrid search (D6), an LLM provider behind the guarded Provider (D4).
- Production adapters need credentials and accreditation (NRS filing and e-invoicing, PSP, KYC,
  CITN/ICAN registers, WhatsApp BSP, email/SMS).
- Legal review of every parameter and obligation marked unverified or secondary_source.
