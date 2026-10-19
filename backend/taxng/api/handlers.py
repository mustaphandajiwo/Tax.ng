"""HTTP-framework-independent API.

Every endpoint is a plain function ``(services, request) -> (status, body)``.
The Starlette app in ``app.py`` is a thin adapter, so moving to FastAPI (ADR-03)
touches only that file, and tests call ``dispatch`` directly.

Money values in responses are decimal strings (e.g. "330000.00"), never floats.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..calculators import CALCULATORS, InputError, compare_pit, payment_types
from ..calculators.pit import DEDUCTIONS
from ..calculators.vat import CATEGORIES
from ..legal import Guide, Provision
from ..rules import ENGINE_VERSION, ParameterError
from ..services import Services
from ..store import StoreError

NAV = [
    {"id": "reform", "label": "New Tax Law 2026", "path": "/reform"},
    {"id": "calculators", "label": "Calculators", "path": "/calculators"},
    {"id": "laws", "label": "Laws & Regulations", "path": "/laws"},
    {"id": "news", "label": "Tax News", "path": "/news"},
    {"id": "ask", "label": "Ask Tax AI", "path": "/ask"},
    {"id": "newsletter", "label": "Newsletter", "path": "/newsletter"},
    {"id": "about", "label": "About & Ownership", "path": "/about"},
]
CONSENT_TEXT = (
    "I agree to receive the weekly Nigerian Tax Brief from tax.ng (Astound Innovation Hub). "
    "I can unsubscribe at any time."
)


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)


class NotFound(LookupError):
    pass


Handler = Callable[[Services, Request, dict[str, str]], tuple[int, Any]]
_ROUTES: list[tuple[str, re.Pattern[str], Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[A-Za-z0-9_.\-]+)", pattern) + "$")

    def register(fn: Handler) -> Handler:
        _ROUTES.append((method, regex, fn))
        return fn

    return register


def dispatch(services: Services, request: Request) -> tuple[int, Any]:
    allowed: list[str] = []
    for method, regex, fn in _ROUTES:
        match = regex.match(request.path)
        if not match:
            continue
        if method != request.method:
            allowed.append(method)
            continue
        try:
            return fn(services, request, match.groupdict())
        except InputError as exc:
            return 422, {"error": "invalid_input", "fields": exc.errors}
        except StoreError as exc:
            fieldname, _, message = str(exc).partition(": ")
            return 422, {"error": "invalid_input", "fields": {fieldname: message}}
        except ParameterError as exc:
            return 422, {"error": "rule_not_in_force", "message": str(exc)}
        except NotFound as exc:
            return 404, {"error": "not_found", "message": str(exc)}
    if allowed:
        return 405, {"error": "method_not_allowed", "allowed": allowed}
    return 404, {"error": "not_found", "message": f"No route for {request.path}"}


# ------------------------------------------------------------------- helpers
def _on(request: Request) -> dt.date:
    raw = request.query.get("on")
    if not raw:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise InputError({"on": "must be a date (YYYY-MM-DD)"}) from None


def _parameter_card(services: Services, name: str, on: dt.date) -> dict[str, Any]:
    tree = services.tree
    info = tree.info(name)
    card: dict[str, Any] = {
        "name": name,
        "description": info.description,
        "unit": info.unit,
        "review_status": info.review_status,
        "reference": info.reference,
        "in_force": True,
    }
    try:
        if tree.is_scale(name):
            card["scale"] = [{"threshold": str(b.threshold), "rate": str(b.rate)} for b in tree.scale(name, on)]
        else:
            value = tree.value(name, on)
            card["value"] = value if isinstance(value, (list, bool)) else str(value)
    except ParameterError:
        card["in_force"] = False
    return card


def _provision(services: Services, p: Provision, on: dt.date) -> dict[str, Any]:
    return {
        "id": p.id,
        "instrument": p.instrument,
        "section": p.section,
        "title": p.title,
        "tax": p.tax,
        "effective_from": p.effective_from.isoformat(),
        "effective_to": p.effective_to.isoformat() if p.effective_to else None,
        "in_force": p.in_force(on),
        "summary": p.summary,
        "review_status": p.review_status,
        "parameters": [_parameter_card(services, n, on) for n in p.parameters],
    }


def _guide(services: Services, g: Guide, *, full: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": g.id,
        "title": g.title,
        "summary": g.summary,
        "applies_from": g.applies_from.isoformat(),
        "calculator": g.calculator,
        "languages": sorted(g.translations),
    }
    if full:
        on = max(g.applies_from, dt.date.today())
        data["body"] = list(g.body)
        data["provisions"] = [
            {"id": pid, "title": services.library.provisions[pid].title} for pid in g.provisions
        ]
        data["figures"] = [_parameter_card(services, n, on) for n in g.parameters]
        data["translations"] = g.translations
    return data


# -------------------------------------------------------------------- routes
@route("GET", "/api/health")
def health(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, {"status": "ok"}


@route("GET", "/api/meta")
def meta(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    tree = services.tree
    wht_types = []
    for t in payment_types(tree):
        recipients = [r for r in ("corporate", "non_corporate") if tree.has(f"wht.rates.{t}.{r}")]
        wht_types.append({"id": t, "label": tree.info(f"wht.rates.{t}.{recipients[0]}").description, "recipients": recipients})
    return 200, {
        "owner": "Astound Innovation Hub",
        "rules_version": tree.version,
        "engine_version": ENGINE_VERSION,
        "nav": NAV,
        "pit_deductions": [{"id": k, "label": v} for k, v in DEDUCTIONS.items()],
        "vat_categories": CATEGORIES,
        "wht_payment_types": wht_types,
        "consent_text": CONSENT_TEXT,
    }


@route("POST", "/api/calculate/pit-compare")
def calc_compare(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, compare_pit(request.body, services.tree)


@route("POST", "/api/calculate/{calculator}")
def calculate(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    calc = CALCULATORS.get(params["calculator"])
    if calc is None:
        raise NotFound(f"Unknown calculator {params['calculator']}")
    return 200, calc(request.body, services.tree).to_dict()


@route("GET", "/api/parameters/{name}")
def parameter(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    if not services.tree.has(params["name"]):
        raise NotFound(f"Unknown parameter {params['name']}")
    return 200, _parameter_card(services, params["name"], _on(request))


@route("GET", "/api/laws")
def laws(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    on = _on(request)
    tax = request.query.get("tax")
    items = [
        _provision(services, p, on)
        for p in services.library.provisions.values()
        if not tax or p.tax == tax
    ]
    return 200, {"on": on.isoformat(), "items": items}


@route("GET", "/api/laws/{id}")
def law(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = services.library.provisions.get(params["id"])
    if p is None:
        raise NotFound(f"Unknown provision {params['id']}")
    return 200, _provision(services, p, _on(request))


@route("GET", "/api/guides")
def guides(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, {"items": [_guide(services, g, full=False) for g in services.library.guides.values()]}


@route("GET", "/api/guides/{id}")
def guide(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    g = services.library.guides.get(params["id"])
    if g is None:
        raise NotFound(f"Unknown guide {params['id']}")
    return 200, _guide(services, g, full=True)


@route("GET", "/api/news")
def news(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, {
        "items": [
            {
                "id": n.id,
                "date": n.date.isoformat(),
                "section": n.section,
                "headline": n.headline,
                "standfirst": n.standfirst,
                "source_name": n.source_name,
                "source_url": n.source_url,
                "sample": n.sample,
            }
            for n in services.library.news
        ]
    }


@route("GET", "/api/search")
def search(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    q = request.query.get("q", "").strip()
    if not q:
        raise InputError({"q": "is required"})
    hits = services.index.search(q[:200], limit=10)
    return 200, {"items": [{"id": h.document.id, "kind": h.document.kind, "title": h.document.title} for h in hits]}


@route("POST", "/api/ask")
def ask(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    question = str(request.body.get("question", "")).strip()
    if len(question) < 3:
        raise InputError({"question": "ask a question of at least a few words"})
    result = services.assistant.answer(question)
    services.store.record_event(
        "ai_question_asked", {"confidence": result["confidence"], "blocked": result["blocked"]}
    )
    return 200, result


@route("POST", "/api/newsletter/subscribe")
def subscribe(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    body = request.body
    services.store.subscribe(
        str(body.get("email", "")),
        consent=body.get("consent") is True,
        consent_text=CONSENT_TEXT,
        topics=body.get("topics"),
    )
    services.store.record_event("newsletter_signup")
    # The unsubscribe token is emailed in production; it is never returned here.
    return 201, {"status": "subscribed"}


@route("POST", "/api/newsletter/unsubscribe")
def unsubscribe(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    ok = services.store.unsubscribe(str(request.body.get("email", "")), str(request.body.get("token", "")))
    if not ok:
        raise NotFound("No active subscription matches that link")
    return 200, {"status": "unsubscribed"}


@route("POST", "/api/events")
def events(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    services.store.record_event(str(request.body.get("name", "")), request.body.get("props") or {})
    return 202, {"status": "recorded"}


@route("GET", "/api/analytics/summary")
def analytics_summary(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Weekly dashboard feed (AN-03). Internal; protect behind staff auth in production."""
    return 200, {"events": services.store.event_counts(), "subscribers": services.store.subscriber_count()}
