# Decisions log (demo)

The PRD's Annex A records the target architecture (ADR-01 to ADR-10). This log
records where the demo departs from it, why, and what migration involves.
The demo was built in a sandbox with no access to PyPI or npm, so it uses only
packages that were already installed. Every departure sits behind a seam that
keeps migration local.

## D1. Rules engine: OpenFisca-format YAML with a minimal reader

- **Target (ADR-02):** an `openfisca-core` country package.
- **Demo:** `backend/taxng/rules/engine.py` reads the same YAML layout:
  `values` keyed by start date, `brackets` for scales, nested nodes, and
  `value: null` to repeal.
- **Why:** `openfisca-core` could not be installed in the build environment.
- **Migration:** move `rules/parameters` into the country package's
  `parameters/` directory. Re-express calculators as OpenFisca variables, and
  convert `rules/tests/*.yaml` into OpenFisca YAML tests. Three demo
  conveniences need attention:
  - Child nodes inherit metadata.
  - List-valued parameters (deduction lists, VAT examples) belong in
    reference data.
  - `review_status` and `provision` are custom metadata keys. OpenFisca allows
    these.

## D2. API framework: Starlette behind a framework-free handler layer

- **Target (ADR-03):** FastAPI.
- **Demo:** endpoints are plain functions in `api/handlers.py`, served by a thin
  Starlette adapter in `api/app.py`.
- **Migration:** replace `app.py` with a FastAPI app that calls `dispatch()`, or
  register each handler as a FastAPI route. Pydantic request models can replace
  `calculators.common.Fields`. Tests call `dispatch()` directly, so they don't
  change.

## D3. Frontend: React + TypeScript bundled with esbuild, hash routing

- **Target:** Next.js with server rendering for SEO-friendly public pages
  (PRD section 5).
- **Demo:** a single-page app with hash routes. Assets are served from the same
  origin under a strict CSP.
- **Migration:** pages map one-to-one to Next.js routes. `src/api.ts` and the
  components carry over unchanged. Server-render the laws, guides and news pages.
- **Typecheck:** `npm run typecheck` runs `tsc` with the real React types. In the
  build sandbox it ran against a temporary type shim and passed.

## D4. Tax AI composer: deterministic template provider

- **Target:** an LLM provider. The vendor and hosting region are still open
  (ADR-10).
- **Demo:** `TemplateProvider` composes answers from retrieved provisions and
  tool results.
- **Migration:** implement the `Provider.compose()` protocol with an LLM using
  tool calling. Expose only the `Tools` methods (`get_parameter`,
  `calculate_pit`) as tools. Keep `guard()` as it is: it runs on every draft from
  any provider. `tests/test_ai.py::BadProvider` is the regression test for this.
  Add the golden-set evaluation (AI-05) before any model change (AI-06).

## D5. Storage: SQLite

- **Target (ADR-04):** PostgreSQL, with row-level security from Phase 2
  (ADR-08).
- **Demo:** `store.py` uses SQLite for newsletter subscribers and analytics
  events. Phase 1 has no taxpayer accounts, so no tenant data is stored.
- **Migration:** port `Store` to PostgreSQL with the same method signatures.

## D6. Search: in-memory BM25

- **Target (ADR-04):** hybrid keyword and vector retrieval over provision-level
  chunks, using Postgres full-text search with pgvector.
- **Demo:** `legal/search.py` provides the keyword half behind a `SearchIndex`
  interface.
- **Migration:** implement the same `search()` signature over Postgres.

## Known gaps (intentionally out of scope for the demo)

- WhatsApp channel (CH-02), translations (CH-04: the data model exists, no
  approved translations yet), and the CGT and stamp duty calculators (CALC-06).
- The unsubscribe email is not sent; production sends the signed link by email.
- `/api/analytics/summary` is unauthenticated. Put it behind staff
  authentication before deployment.
- The PITA low-income exemption and the minimum ETR computation are flagged as
  warnings but not modelled.
