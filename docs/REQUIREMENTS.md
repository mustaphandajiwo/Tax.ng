# Requirement traceability (Phase 1)

Status key: **Done** = implemented and tested; **Partial** = implemented with a
documented gap; **Not started** = scheduled for the phase shown in the PRD.

| ID | Requirement (short) | Status | Where | Test |
|---|---|---|---|---|
| GOV-01 | Ownership page naming Astound Innovation Hub | Done | `frontend/src/pages/content.tsx` (About), `api/handlers.py` (meta.owner) | `test_api.py::test_meta_lists_phase_one_nav_only` |
| GOV-02/03/05 | Recusal, conflicts register, editorial independence | Partial | Stated on the About page; the register and editor workflow are operational | — |
| CH-01 | Mobile-first, light first load | Done | `styles.css`; app bundle about 225 KB minified | Manual (390px screenshot, no overflow) |
| CH-02 | WhatsApp channel | Not started | Reuses `dispatch()` when built | — |
| CH-04 | Language summaries | Partial | `guides.yaml: translations`, UI shows languages when present | — |
| CALC-01 | PIT/PAYE under NTA 2025 | Done | `calculators/pit.py`, `rules/parameters/pit/nta2025.yaml` | legislative cases 1–5 |
| CALC-02 | CIT, small company, development levy | Done | `calculators/cit.py` | legislative cases 8–10, `test_calculators.py` |
| CALC-03 | VAT | Done | `calculators/vat.py` | legislative cases 11–13 |
| CALC-04 | WHT | Done | `calculators/wht.py` | legislative cases 14–18 |
| CALC-05 | Old versus new PIT | Done | `pit.compare_pit` | `test_compare_reports_direction` |
| CALC-07 | One rules engine, no figures in code | Done | `rules/engine.py`; calculators read only `ParameterView` | `test_every_parameter_has_review_status_and_provision` |
| CALC-08 | Steps, citations, assumptions, worksheet | Done | `CalculationResult.to_dict`, `ResultView.tsx` | `test_result_is_reproducible`, `test_bands_sum_to_tax` |
| CALC-09 | Anonymous inputs not stored | Done | Calculator endpoints persist nothing; events carry only calculator ids | `test_event_props_are_filtered` |
| LAW-01 | Provision metadata | Done | `content/provisions.yaml`, `legal/corpus.py` | `test_content_with_a_figure_is_rejected` |
| LAW-02 | Launch corpus | Partial | Summaries only; gazette text ingestion is a production pipeline | — |
| LAW-04 | Reform guide hub | Done | `content/guides.yaml`, `/reform` | — |
| LAW-05 | Badges distinguishing summary from statute | Done | Law page "Explanatory summary" badge and notice | — |
| AI-01 | Grounded, period-aware answers with escalation | Done | `ai/assistant.py` | `test_old_year_retrieves_old_law_only`, `test_out_of_scope_escalates` |
| AI-02 | Citations only from retrieval | Done | `guard()` | `test_rejects_citation_not_retrieved`, `test_invented_answer_is_blocked` |
| AI-03 | Figures only from rules engine | Done | `guard()`, `Tools` | `test_rejects_figure_not_from_engine`, `test_salary_question_uses_calculator_tool` |
| AI-04 | No account data in Phases 1–3 | Done | Assistant has no data access beyond the rules and corpus | — |
| AI-05/06 | Golden set and sign-off | Not started | Needed before an LLM provider replaces the template (D4) | — |
| NEWS-01 | Nigeria news, attributed | Done | `content/news.yaml` (sample items flagged) | — |
| NEWS-03 | Consent, preferences, unsubscribe | Done | `store.py`, `/newsletter` | `test_newsletter_requires_consent`, `test_unsubscribe_needs_valid_token` |
| AN-01/02 | First-party analytics, whitelisted events | Done | `store.EVENTS`, `api.event()` | `test_events_whitelist` |
| AN-03 | Weekly dashboard feed | Partial | `/api/analytics/summary` (needs staff authentication) | — |
| NFR-01 | WCAG 2.2 AA | Partial | Labels, focus styles, skip link, aria-live results; audit pending | — |
| NFR-06 | Reproducibility | Done | `rules_version`, `engine_version`, `parameters_used` on every result | `test_result_is_reproducible` |
| ADR-06 | Strict CSP on the public origin | Done | `api/app.py: SECURITY_HEADERS` | Manual (response headers) |
| PRD s.5 | Phase 1 navigation only | Done | `handlers.NAV`, `App.tsx: ROUTES` | `test_meta_lists_phase_one_nav_only` |
