"""Health-check findings and report (HC-03 to HC-07).

Findings are reported **by dimension only** (HC-03): obligation coverage,
timeliness, documentation, reporting accuracy indicators, exposure materiality
and evidence confidence. Nothing here adds dimensions together, weights them or
produces a score, grade or percentage; tests assert that no such field exists.

* An unknown or unanswered question is "insufficient evidence", never a gap or
  a fail (HC-04). Obligations that cannot be decided from the facts are
  reported the same way.
* Findings are ordered with the most severe first (HC-05).
* A high-severity gap is a *review recommendation* (``review_recommended``),
  never a statement that tax or penalties are owed (HC-06).
* Every report carries the self-reported, indicative, not-an-official-assessment
  statement (HC-07).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ...legal import Library
from .facts import UNKNOWN
from .questions import DIMENSIONS, NOT_APPLICABLE, QuestionBank

STATEMENT = (
    "This report is based only on what you told us. It is self-reported and indicative. It is not an official "
    "assessment by the Nigeria Revenue Service or any state tax authority, and it does not say that you owe tax, "
    "penalties or interest."
)
REVIEW_NOTE = (
    "Where a finding is marked for review, we recommend that a qualified tax adviser looks at it. "
    "A review recommendation is not a finding of liability."
)
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
CELL_RANK = {"gap": 0, "insufficient_evidence": 1, "ok": 2, NOT_APPLICABLE: 3, "not_assessed": 4}
ANSWER_LABEL = {"yes": "Yes", "no": "No", UNKNOWN: "Not sure", None: "Not answered yet"}
MAX_NEXT_STEPS = 12


def _links(row: dict[str, Any]) -> list[dict[str, str]]:
    links = []
    if row.get("guide"):
        links.append({"kind": "guide", "label": "Read the guide", "path": f"/reform/{row['guide']}"})
    if row.get("calculator"):
        links.append({"kind": "calculator", "label": "Open the calculator", "path": f"/calculators/{row['calculator']}"})
    links.append({"kind": "adviser", "label": "Find an adviser", "path": "/advisers", "specialism": row.get("specialism") or ""})
    return links


def _raise(level: str) -> str:
    return {"low": "medium", "medium": "high"}.get(level, level)


def _sort_key(finding: dict[str, Any], order: dict[str, int]) -> tuple[int, int, int, str]:
    status_rank = 0 if finding["status"] == "gap" else 1
    return (status_rank, SEVERITY_RANK.get(finding["severity"] or "", 3), order.get(finding["obligation"], 99), finding["id"])


def build_report(
    *,
    bank: QuestionBank,
    evaluation: dict[str, Any],
    facts: dict[str, Any],
    answers: dict[str, Any],
    year: int,
    on: dt.date,
    library: Library,
    rules_version: str,
    generated_at: str,
    check_id: str,
) -> dict[str, Any]:
    today = on.isoformat()
    # ---- obligations matrix rows (one row per obligation, not per period)
    rows: dict[str, dict[str, Any]] = {}
    for item in evaluation["applicable"]:
        row = rows.get(item["id"])
        if row is None:
            row = rows[item["id"]] = {
                **{k: item[k] for k in ("id", "tax", "title", "frequency", "provision", "applies_because", "review_status",
                                         "due_rule", "due_date_review_status", "note", "guide", "calculator", "specialism")},
                "evidence": list(item["evidence"]),
                "status": "applies",
                "periods": [],
                "due_dates": [],
            }  # fmt: skip
        row["periods"].append(item["period"])
        row["due_dates"].append(item["due_date"])
    for row in rows.values():
        upcoming = sorted(d for d in row["due_dates"] if d >= today)
        row["next_due_date"] = upcoming[0] if upcoming else max(row["due_dates"])
    order = {oid: i for i, oid in enumerate(rows)}

    cells: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    findings: list[dict[str, Any]] = []
    missing: dict[str, dict[str, Any]] = {}

    def add_missing(oid: str, documents: list[str]) -> None:
        if not documents:
            return
        entry = missing.setdefault(oid, {"obligation": oid, "obligation_title": rows[oid]["title"], "documents": []})
        entry["documents"].extend(d for d in documents if d not in entry["documents"])

    # ---- asked dimensions
    asked_counts: dict[str, dict[str, int]] = {oid: {"total": 0, "uncertain": 0} for oid in rows}
    for q in bank.visible_evidence(set(rows), facts, on):
        row = rows[q.obligation]
        answer = answers.get(q.id)
        if answer == NOT_APPLICABLE:
            cells.setdefault((q.obligation, q.dimension), []).append((NOT_APPLICABLE, None))
            continue
        asked_counts[q.obligation]["total"] += 1
        documents = list(q.evidence) or (list(row["evidence"]) if q.dimension == "documentation" else [])
        if answer == "yes":
            cells.setdefault((q.obligation, q.dimension), []).append(("ok", None))
            continue
        base = {
            "id": f"{q.dimension}:{q.id}",
            "dimension": q.dimension,
            "obligation": q.obligation,
            "obligation_title": row["title"],
            "tax": row["tax"],
            "question": q.text,
            "answer": ANSWER_LABEL.get(answer, str(answer)),
            "provision": row["provision"],
            "links": _links(row),
        }
        if answer == "no":
            cells.setdefault((q.obligation, q.dimension), []).append(("gap", q.severity))
            findings.append(
                {
                    **base,
                    "status": "gap",
                    "severity": q.severity,
                    "review_recommended": q.severity == "high",
                    "title": f"{row['title']}: possible gap",
                    "why_it_matters": q.why,
                    "next_step": q.next_step,
                    "evidence_missing": documents if q.dimension == "documentation" else [],
                }
            )
            if q.dimension == "documentation":
                add_missing(q.obligation, documents)
        else:
            asked_counts[q.obligation]["uncertain"] += 1
            cells.setdefault((q.obligation, q.dimension), []).append(("insufficient_evidence", None))
            findings.append(
                {
                    **base,
                    "status": "insufficient_evidence",
                    "severity": None,
                    "review_recommended": False,
                    "title": f"{row['title']}: insufficient evidence",
                    "why_it_matters": "We cannot assess this point without an answer. " + q.why,
                    "next_step": "Answer this question when you can, or check your records. " + q.next_step,
                    "evidence_missing": documents if q.dimension == "documentation" else [],
                }
            )
            if q.dimension == "documentation":
                add_missing(q.obligation, documents)

    # ---- obligations that cannot be decided yet (coverage, insufficient evidence)
    undetermined_rows = []
    for u in evaluation["undetermined"]:
        if u["id"] in rows:
            continue  # applies for some periods; the matrix row already exists
        labels = [bank.fact_label(f) for f in u["unknown_facts"]]
        why = "We could not tell whether this applies to you"
        detail = f"{why}. Questions still open: {'; '.join(labels)}" if labels else f"{why} for every period of the year."
        undetermined_rows.append({**u, "status": "undetermined", "detail": detail})
        findings.append(
            {
                "id": f"obligation_coverage:undetermined:{u['id']}",
                "dimension": "obligation_coverage",
                "obligation": u["id"],
                "obligation_title": u["title"],
                "tax": u["tax"],
                "question": None,
                "answer": None,
                "status": "insufficient_evidence",
                "severity": None,
                "review_recommended": False,
                "title": f"{u['title']}: may apply",
                "why_it_matters": detail + ".",
                "next_step": "Answer the open profile questions so we can tell whether this applies.",
                "evidence_missing": [],
                "provision": u["provision"],
                "links": _links(u),
            }
        )

    # ---- exposure materiality (derived from gaps; indicative, not an amount)
    elevated = bank.elevated(facts, on)
    for oid, row in rows.items():
        gap_levels = [sev for status, sev in (c for d in ("obligation_coverage", "timeliness", "documentation", "reporting_accuracy")
                                              for c in cells.get((oid, d), [])) if status == "gap" and sev]  # fmt: skip
        if not gap_levels:
            cells.setdefault((oid, "exposure_materiality"), []).append(("not_assessed", None))
            continue
        level = min(gap_levels, key=lambda s: SEVERITY_RANK[s])
        why = "This shows the likely scale of what is at stake if the gaps above are confirmed. It is not an amount owed."
        if elevated:
            level = _raise(level)
            why += " " + str(bank.materiality.get("reason", ""))
        elif elevated is None:
            why += " Your turnover or assets are not known, so we could not scale this."
        cells.setdefault((oid, "exposure_materiality"), []).append(("gap", level))
        findings.append(
            {
                "id": f"exposure_materiality:{oid}",
                "dimension": "exposure_materiality",
                "obligation": oid,
                "obligation_title": row["title"],
                "tax": row["tax"],
                "question": None,
                "answer": None,
                "status": "gap",
                "severity": level,
                "review_recommended": level == "high",
                "title": f"{row['title']}: {level} exposure",
                "why_it_matters": why,
                "next_step": "Ask a qualified tax adviser to review this obligation." if level == "high" else "Resolve the gaps above for this obligation.",
                "evidence_missing": [],
                "provision": row["provision"],
                "links": _links(row),
            }
        )

    # ---- evidence confidence (how much of the picture we have)
    for oid, row in rows.items():
        counts = asked_counts[oid]
        if counts["total"] == 0:
            cells.setdefault((oid, "evidence_confidence"), []).append(("not_assessed", None))
            continue
        if counts["uncertain"] == 0:
            cells.setdefault((oid, "evidence_confidence"), []).append(("ok", None))
            continue
        cells.setdefault((oid, "evidence_confidence"), []).append(("insufficient_evidence", None))
        findings.append(
            {
                "id": f"evidence_confidence:{oid}",
                "dimension": "evidence_confidence",
                "obligation": oid,
                "obligation_title": row["title"],
                "tax": row["tax"],
                "question": None,
                "answer": None,
                "status": "insufficient_evidence",
                "severity": None,
                "review_recommended": False,
                "title": f"{row['title']}: limited evidence",
                "why_it_matters": f"{counts['uncertain']} of {counts['total']} questions for this obligation are unanswered or marked not sure, so findings for it are incomplete.",
                "next_step": "Check your records and update the open answers.",
                "evidence_missing": [],
                "provision": row["provision"],
                "links": _links(row),
            }
        )

    findings.sort(key=lambda f: _sort_key(f, order))

    # ---- matrix and dimension summaries (no totals across dimensions)
    def cell(oid: str, dim: str) -> dict[str, Any]:
        entries = cells.get((oid, dim))
        if not entries:
            return {"status": "not_assessed", "severity": None}
        worst = min(entries, key=lambda e: (CELL_RANK[e[0]], SEVERITY_RANK.get(e[1] or "", 3)))
        return {"status": worst[0], "severity": worst[1]}

    matrix = []
    for oid, row in rows.items():
        matrix.append({**{k: v for k, v in row.items() if k != "due_dates"}, "cells": {d: cell(oid, d) for d, _ in DIMENSIONS}})
    for u in undetermined_rows:
        matrix.append(
            {
                **{k: u[k] for k in ("id", "tax", "title", "frequency", "provision", "review_status", "guide", "calculator", "specialism")},
                "status": "undetermined",
                "applies_because": u["detail"] + ".",
                "periods": u["periods"],
                "cells": {d: {"status": "insufficient_evidence" if d == "obligation_coverage" else "not_assessed", "severity": None} for d, _ in DIMENSIONS},
            }
        )

    dimensions = []
    for key, label in DIMENSIONS:
        in_dim = [f for f in findings if f["dimension"] == key]
        gaps = {s: sum(1 for f in in_dim if f["status"] == "gap" and f["severity"] == s) for s in SEVERITY_RANK}
        insufficient = sum(1 for f in in_dim if f["status"] == "insufficient_evidence")
        ok = sum(1 for r in matrix if r["cells"][key]["status"] == "ok")
        status = "gaps_found" if any(gaps.values()) else "insufficient_evidence" if insufficient else "no_gaps_found" if ok else "not_assessed"
        dimensions.append({"id": key, "label": label, "status": status, "gaps": gaps, "insufficient_evidence": insufficient, "ok": ok})

    # ---- prioritised next steps
    steps: list[dict[str, Any]] = []
    review = [f["obligation_title"] for f in findings if f["review_recommended"]]
    if review:
        titles = list(dict.fromkeys(review))
        steps.append(
            {
                "text": "Ask a qualified tax adviser to review: " + "; ".join(titles) + ".",
                "priority": "high",
                "links": [{"kind": "adviser", "label": "Find an adviser", "path": "/advisers", "specialism": ""}],
            }
        )
    seen = {s["text"] for s in steps}
    for f in findings:
        if f["next_step"] in seen:
            continue
        seen.add(f["next_step"])
        steps.append({"text": f["next_step"], "priority": f["severity"] or "info", "obligation": f["obligation"], "links": f["links"]})
        if len(steps) >= MAX_NEXT_STEPS:
            break

    citations = []
    for pid in dict.fromkeys([r["provision"] for r in matrix]):
        p = library.provisions.get(pid)
        if p:
            citations.append({"id": p.id, "title": p.title, "instrument": p.instrument, "section": p.section, "review_status": p.review_status})

    return {
        "check_id": check_id,
        "year": year,
        "generated_at": generated_at,
        "as_of": today,
        "statement": STATEMENT,
        "review_note": REVIEW_NOTE,
        "facts": dict(facts),
        "obligations": matrix,
        "dimensions": dimensions,
        "findings": findings,
        "missing_evidence": list(missing.values()),
        "next_steps": steps,
        "citations": citations,
        "rules_version": rules_version,
    }
