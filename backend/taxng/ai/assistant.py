"""Tax AI pipeline (AI-01 to AI-06).

    question -> classify (tax, period, amount) -> retrieve in-force provisions
             -> tool calls to the rules engine -> compose (provider)
             -> guards -> answer

Two guards run on every draft before anything is shown:

* Citation guard (AI-02): every cited provision must be one that retrieval
  returned for this question. Anything else blocks the answer.
* Figure guard (AI-03): every naira amount and percentage in the text must
  equal a value returned by a rules-engine tool call. Anything else blocks it.

The provider is the only part that would call an LLM. The demo ships a
deterministic TemplateProvider; an LLM provider implements the same
``compose`` method and is subject to the same guards (docs/DECISIONS.md, D4).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from ..calculators import InputError, calculate_pit
from ..format import naira, percent
from ..legal import Library, Provision, SearchIndex
from ..rules import ParameterError, ParameterTree

DISCLAIMER = (
    "General information from the approved legal library, not tax advice. "
    "Figures come from the tax.ng rules engine. Rules are pending legal sign-off."
)

_TAX_HINTS: dict[str, set[str]] = {
    "pit": {"paye", "salary", "salaries", "income", "employee", "employment", "personal", "pit",
            "wage", "wages", "rent", "relief", "pension", "earn", "earning", "individual"},
    "cit": {"company", "companies", "cit", "corporate", "profit", "profits", "small", "levy", "business", "sme"},
    "vat": {"vat", "value", "added", "invoice", "goods", "supply", "supplies", "zero"},
    "wht": {"withholding", "wht", "dividend", "dividends", "royalty", "royalties", "tin", "deduct"},
}
_WORD = re.compile(r"[a-z]+")
_YEAR = re.compile(r"\b(20[1-3]\d)\b")
_AMOUNT = re.compile(
    r"(?P<cur>₦|\bngn\s*|\bn(?=\d))?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>million|m\b|billion|bn\b|k\b|thousand)?",
    re.IGNORECASE,
)
_MULTIPLIERS = {"million": 10**6, "m": 10**6, "billion": 10**9, "bn": 10**9, "k": 10**3, "thousand": 10**3}
_MONTHLY = re.compile(r"\b(per month|a month|monthly|every month)\b", re.IGNORECASE)

REGIME_LABELS = {"nta2025": "Nigeria Tax Act 2025", "pita": "Personal Income Tax Act"}

_TEXT_MONEY = re.compile(r"₦\s?(\d[\d,]*(?:\.\d+)?)")
_TEXT_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


# --------------------------------------------------------------------- intent
@dataclass
class Intent:
    taxes: set[str]
    year: int
    amount: Decimal | None
    monthly: bool


def classify(question: str, default_year: int) -> Intent:
    words = set(_WORD.findall(question.lower()))
    taxes = {tax for tax, hints in _TAX_HINTS.items() if words & hints}
    year_match = _YEAR.search(question)
    year = int(year_match.group(1)) if year_match else default_year

    amount: Decimal | None = None
    for m in _AMOUNT.finditer(question):
        raw = m.group("num").replace(",", "")
        cur, mult = m.group("cur"), (m.group("mult") or "").lower()
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        looks_like_year = not cur and not mult and len(raw) == 4 and 2011 <= value <= 2035
        if looks_like_year or (not cur and not mult and value < 1000):
            continue
        amount = value * _MULTIPLIERS.get(mult, 1)
        break
    return Intent(taxes, year, amount, bool(_MONTHLY.search(question)))


# ---------------------------------------------------------------------- tools
def _numbers(value: Any) -> set[Decimal]:
    """Every number in a tool result, plus its percentage form for rates."""
    found: set[Decimal] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float, Decimal)):
        d = Decimal(str(value))
        return {d, d * 100}
    if isinstance(value, str):
        try:
            d = Decimal(value)
        except InvalidOperation:
            return found
        return {d, d * 100} if d.is_finite() else found
    if isinstance(value, dict):
        for v in value.values():
            found |= _numbers(v)
    if isinstance(value, (list, tuple)):
        for v in value:
            found |= _numbers(v)
    return found


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any

    def figures(self) -> set[Decimal]:
        return _numbers(self.result)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}


class Tools:
    """The only route from the assistant to figures: the rules engine."""

    def __init__(self, tree: ParameterTree) -> None:
        self.tree = tree
        self.calls: list[ToolCall] = []
        self.account: dict[str, Any] | None = None

    def get_account_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        """AI-04: the caller's own account data, fetched by the route after permission checks.

        The assistant never queries the database itself; it only receives what
        the route has already scoped to the signed-in user and active organisation.
        """
        self.calls.append(ToolCall("get_account_summary", {"scopes": sorted(summary)}, summary))
        self.account = summary
        return summary

    def get_parameter(self, name: str, on: dt.date) -> Any | None:
        try:
            if self.tree.is_scale(name):
                result: Any = [{"threshold": str(b.threshold), "rate": str(b.rate)} for b in self.tree.scale(name, on)]
            else:
                result = self.tree.value(name, on)
                result = str(result) if isinstance(result, Decimal) else result
        except ParameterError:
            return None
        self.calls.append(ToolCall("get_parameter", {"name": name, "on": on.isoformat()}, result))
        return result

    def calculate_pit(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            result = calculate_pit(payload, self.tree).to_dict()
        except (InputError, ParameterError):
            return None
        self.calls.append(ToolCall("calculate_pit", payload, result["outputs"]))
        return result


# ------------------------------------------------------------------- composer
@dataclass
class Draft:
    text: str
    cited: list[str]


class Provider(Protocol):
    def compose(self, question: str, intent: Intent, passages: list[Provision],
                tools: Tools, calculation: dict[str, Any] | None) -> Draft: ...


def describe_parameter(tree: ParameterTree, name: str, value: Any) -> str:
    info = tree.info(name)
    label = info.description
    if isinstance(value, list) and value and isinstance(value[0], dict):
        parts = []
        for i, band in enumerate(value):
            lower = Decimal(band["threshold"])
            rate = Decimal(band["rate"])
            if i + 1 < len(value):
                upper = Decimal(value[i + 1]["threshold"])
                parts.append(f"{naira(lower)} to {naira(upper)} at {percent(rate)}")
            else:
                parts.append(f"above {naira(lower)} at {percent(rate)}")
        return f"{label}: " + "; ".join(parts) + "."
    if isinstance(value, list):
        return f"{label}: " + "; ".join(str(v) for v in value) + "."
    if isinstance(value, bool):
        return f"{label}: {'yes' if value else 'no'}."
    if isinstance(value, str) and value in REGIME_LABELS:
        return f"{label}: {REGIME_LABELS[value]}."
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return f"{label}: {value}."
    if info.unit == "currency-NGN":
        return f"{label}: {naira(number)}."
    if info.unit == "/1":
        return f"{label}: {percent(number)}."
    return f"{label}: {number}."


def describe_account(account: dict[str, Any]) -> list[str]:
    """Plain-language lines about the caller's own account. States no figures."""
    lines: list[str] = []
    personal = account.get("personal")
    if personal is not None:
        check = personal.get("latest_check")
        if not check:
            lines.append("From your account: you have not completed a tax health check yet, so I can't comment on your own position.")
        else:
            flagged = [
                f["title"]
                for items in check["findings_by_dimension"].values()
                for f in items
                if f.get("review_recommended") or f.get("severity") == "high"
            ]
            text = f"From your account: your latest health check ({check['year']}) "
            text += ("flags " + "; ".join(sorted(set(flagged))[:4]) + ".") if flagged else "has no findings that need review."
            lines.append(text)
    org = account.get("organisation")
    if org is not None:
        upcoming = org.get("upcoming_obligations") or []
        if upcoming:
            items = "; ".join(f"{o['title']} due {o['due_date']}" for o in upcoming[:3])
            lines.append(f"For {org['org']['name']}: next obligations are {items}.")
        else:
            lines.append(f"For {org['org']['name']}: no upcoming obligations are on the calendar.")
    return lines


class TemplateProvider:
    """Deterministic composer used in the demo and in tests."""

    def compose(self, question: str, intent: Intent, passages: list[Provision],
                tools: Tools, calculation: dict[str, Any] | None) -> Draft:
        if not passages and not calculation and not tools.account:
            return Draft(
                "I could not find an approved source in the tax.ng library for that question. "
                "A tax professional can help.",
                [],
            )
        paragraphs: list[str] = []
        if calculation:
            out = calculation["outputs"]
            gross = Decimal(calculation["inputs"]["annual_gross_income"])
            paragraphs.append(
                f"For gross annual income of {naira(gross)} in tax year {intent.year}, the rules engine "
                f"computes annual tax of {naira(Decimal(out['annual_tax']))}, about "
                f"{naira(Decimal(out['monthly_tax']))} a month. That is an effective rate of "
                f"{out['effective_rate_percent']}%."
            )
        if tools.account:
            paragraphs.extend(describe_account(tools.account))
        if "cit" in intent.taxes and intent.amount is not None:
            paragraphs.append(
                "Company tax depends on turnover, fixed assets and profits together. "
                "Use the CIT calculator to work it out."
            )
        for p in passages:
            lines = [f"{p.title} ({p.instrument}). {p.summary}"]
            for name in p.parameters[:4]:
                value = tools.get_parameter(name, dt.date(intent.year, 1, 1))
                if value is not None:
                    lines.append("Rules engine: " + describe_parameter(tools.tree, name, value))
            paragraphs.append(" ".join(lines))
        return Draft("\n\n".join(paragraphs), [p.id for p in passages])


# ---------------------------------------------------------------------- guard
@dataclass
class GuardReport:
    citations_ok: bool
    figures_ok: bool
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.citations_ok and self.figures_ok


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def guard(draft: Draft, retrieved_ids: set[str], tool_calls: list[ToolCall]) -> GuardReport:
    report = GuardReport(True, True)
    for cid in draft.cited:
        if cid not in retrieved_ids:
            report.citations_ok = False
            report.problems.append(f"citation {cid} was not returned by retrieval")
    allowed: set[Decimal] = set()
    for call in tool_calls:
        allowed |= call.figures()
    for match in _TEXT_MONEY.finditer(draft.text):
        if _decimal(match.group(1)) not in allowed:
            report.figures_ok = False
            report.problems.append(f"amount ₦{match.group(1)} did not come from the rules engine")
    for match in _TEXT_PERCENT.finditer(draft.text):
        if _decimal(match.group(1)) not in allowed:
            report.figures_ok = False
            report.problems.append(f"rate {match.group(1)}% did not come from the rules engine")
    return report


# ------------------------------------------------------------------ assistant
class Assistant:
    def __init__(self, tree: ParameterTree, library: Library, index: SearchIndex,
                 provider: Provider | None = None, *, default_year: int = 2026) -> None:
        self.tree = tree
        self.library = library
        self.index = index
        self.provider = provider or TemplateProvider()
        self.default_year = default_year

    def retrieve(self, question: str, intent: Intent, limit: int = 3) -> list[Provision]:
        on = dt.date(intent.year, 1, 1)
        query = question + " " + " ".join(sorted(intent.taxes))
        passages: list[Provision] = []
        for hit in self.index.search(query, limit=12, kinds={"provision"}):
            p = self.library.provisions[hit.document.id]
            if not p.in_force(on):
                continue
            if intent.taxes and p.tax not in intent.taxes and p.tax != "general":
                continue
            passages.append(p)
            if len(passages) == limit:
                break
        return passages

    def answer(self, question: str, *, account: dict[str, Any] | None = None) -> dict[str, Any]:
        """Answer a question. ``account`` is the caller's own, already-scoped account data (AI-04)."""
        question = question.strip()[:500]
        intent = classify(question, self.default_year)
        passages = self.retrieve(question, intent)
        tools = Tools(self.tree)
        if account is not None:
            tools.get_account_summary(account)

        calculation = None
        notices: list[str] = []
        if "pit" in intent.taxes and intent.amount is not None:
            annual = intent.amount * 12 if intent.monthly else intent.amount
            if intent.monthly:
                notices.append("Monthly amount converted to annual (× 12).")
            calculation = tools.calculate_pit({"annual_gross_income": str(annual), "tax_year": intent.year})

        draft = self.provider.compose(question, intent, passages, tools, calculation)
        report = guard(draft, {p.id for p in passages}, tools.calls)

        if not report.passed:
            return self._blocked(intent, tools, report)

        cited = [self.library.provisions[c] for c in draft.cited]
        confidence = "high" if cited and tools.calls else "medium" if cited or tools.account else "low"
        return {
            "answer": draft.text,
            "blocked": False,
            "confidence": confidence,
            "escalate": confidence == "low",
            "tax_year": intent.year,
            "citations": [_citation(p) for p in cited],
            "tool_calls": [c.to_dict() for c in tools.calls],
            "calculation": calculation,
            "guard": {"citations_ok": True, "figures_ok": True, "problems": []},
            "notices": notices,
            "account_used": tools.account is not None,
            "disclaimer": DISCLAIMER,
        }

    def _blocked(self, intent: Intent, tools: Tools, report: GuardReport) -> dict[str, Any]:
        return {
            "answer": "I can't give a reliable answer to that. Please speak to a tax professional.",
            "blocked": True,
            "confidence": "low",
            "escalate": True,
            "tax_year": intent.year,
            "citations": [],
            "tool_calls": [c.to_dict() for c in tools.calls],
            "calculation": None,
            "guard": {"citations_ok": report.citations_ok, "figures_ok": report.figures_ok, "problems": report.problems},
            "notices": [],
            "account_used": tools.account is not None,
            "disclaimer": DISCLAIMER,
        }


def _citation(p: Provision) -> dict[str, Any]:
    return {"id": p.id, "title": p.title, "instrument": p.instrument, "section": p.section,
            "review_status": p.review_status}
