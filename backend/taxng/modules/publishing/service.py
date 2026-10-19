"""Articles: contributor submissions, editorial workflow, corrections, labels and distribution.

Workflow (Annex A8)::

    draft -> submitted -> screening -> fact_legal_review -> approved -> scheduled -> published
                 \\-----------\\--------------\\-> revision_requested -> (contributor edits) -> submitted
    published -> corrected (repeatable) | withdrawn (tombstone)

Who may do what is enforced here, not in the UI:

* contributors (the author) edit drafts and revision requests, and submit;
* staff ``editor`` (and ``admin``) move every editorial state;
* staff ``legal_reviewer`` signs off fact and legal review, and may send an
  article in review back for revision;
* ``sales`` never moves an editorial state.

Editorial approval never reads payment state (SPON-03, Annex B). The publish
guard checks disclosure, ARCON vetting and the audience threshold for paid
content; it does not check payment either, and payment never publishes.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

import yaml

from ... import config
from ...api.router import NotFound
from ...legal import Document, SearchIndex
from ...platform.access import Forbidden, Principal
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id, now, parse_iso, sign

if TYPE_CHECKING:
    from ...services import Services

SITE_URL = f"https://{config.PUBLIC_HOST}" if config.PUBLIC_HOST else "https://tax.ng"
PUBLISHER = "tax.ng (Astound Innovation Hub)"

TYPE_LABEL = {
    "commentary": "Explanatory commentary",
    "news": "News",
    "opinion": "Opinion",
    "submission": "User submission",
    "sponsored": "Sponsored",
}
SECTIONS = ("nigeria", "africa", "global")
EDITABLE_BY_AUTHOR = ("draft", "revision_requested")
PRE_PUBLISH = ("submitted", "screening", "fact_legal_review", "approved", "scheduled")
PUBLIC_STATES = ("published", "corrected")
EDITORIAL_STAFF = ("editor", "admin")
READ_STAFF = ("editor", "legal_reviewer", "admin")

# action -> (allowed from-states, to-state, who)
TRANSITIONS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "submit": (("draft", "revision_requested"), "submitted", "author"),
    "screen": (("submitted",), "screening", "editor"),
    "request_revision": (("submitted", "screening", "fact_legal_review"), "revision_requested", "editor_or_legal"),
    "send_to_review": (("screening",), "fact_legal_review", "editor"),
    "sign_off": (("fact_legal_review",), "fact_legal_review", "legal"),
    "approve": (("fact_legal_review",), "approved", "editor"),
    "reject": (("submitted", "screening", "fact_legal_review"), "rejected", "editor"),
    "schedule": (("approved",), "scheduled", "editor"),
    "publish": (("approved", "scheduled"), "published", "editor"),
    "correct": (("published", "corrected"), "corrected", "editor"),
    "withdraw": (("approved", "scheduled", "published", "corrected"), "withdrawn", "editor"),
}

TEXT_LIMITS = {
    "title": 200,
    "summary": 600,
    "body": 60000,
    "author_name": 120,
    "author_credentials": 300,
    "affiliation": 200,
    "jurisdiction": 80,
    "conflicts": 1000,
    "ai_disclosure": 1000,
}


# ------------------------------------------------------------------- policy
@lru_cache(maxsize=4)
def _policy_at(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def policy(services: Services) -> dict[str, Any]:
    return _policy_at(str(services.content_dir / "publishing" / "policy.yaml"))


# ------------------------------------------------------------------ helpers
def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-") or "article"
    return base


def parse_when(value: Any, field: str) -> dt.datetime:
    try:
        moment = parse_iso(str(value))
    except ValueError:
        raise Invalid(f"{field}: use an ISO date and time, e.g. 2026-11-02T08:00") from None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def _citations(raw: Any) -> list[dict[str, str]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise Invalid("citations: send a list")
    out = []
    for item in raw[:50]:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            raise Invalid("citations: each citation needs text")
        url = str(item.get("url", "")).strip()
        if url and not url.startswith(("https://", "http://")):
            raise Invalid("citations: links must start with https://")
        out.append({"text": str(item["text"]).strip()[:500], "url": url[:500]})
    return out


def get_article(services: Services, article_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_articles WHERE id = ?", (article_id,))
    if row is None:
        raise NotFound("Article not found")
    return row


def is_paid(article: dict[str, Any]) -> bool:
    return (
        article["article_type"] == "sponsored"
        or article["sponsorship_declaration"] != "none"
        or bool(article.get("sponsorship_id"))
    )


def disclosure_for(services: Services, article_id: str) -> dict[str, Any] | None:
    return services.db.one("SELECT * FROM pub_disclosures WHERE article_id = ?", (article_id,))


def can_read(principal: Principal, article: dict[str, Any]) -> bool:
    if article["author_user_id"] == principal.user_id or principal.staff_role in READ_STAFF:
        return True
    return principal.staff_role == "sales" and is_paid(article)


def visible_article(services: Services, principal: Principal, article_id: str) -> dict[str, Any]:
    article = get_article(services, article_id)
    if not can_read(principal, article):
        raise NotFound("Article not found")
    return article


def _check_role(principal: Principal, who: str, article: dict[str, Any]) -> str:
    role = principal.staff_role
    if who == "author":
        if article["author_user_id"] != principal.user_id:
            raise Forbidden("Only the author can do this")
        return "author"
    if who == "editor" and role in EDITORIAL_STAFF:
        return role
    if who == "legal" and role in ("legal_reviewer", "admin"):
        return role
    if who == "editor_or_legal":
        if role in EDITORIAL_STAFF:
            return role
        if role == "legal_reviewer" and article["state"] == "fact_legal_review":
            return role
    raise Forbidden("Your role cannot make this editorial change")


def _append_revision(services: Services, article: dict[str, Any], version: int, actor_id: str | None, reason: str) -> None:
    services.db.insert(
        "pub_revisions",
        {
            "id": new_id("rev"),
            "article_id": article["id"],
            "version": version,
            "actor_id": actor_id,
            "reason": reason,
            "title": article["title"],
            "summary": article["summary"],
            "body": article["body"],
            "citations_json": article["citations_json"],
            "created_at": iso(),
        },
    )


def _history(services: Services, article_id: str, action: str, from_state: str, to_state: str, actor_id: str | None, role: str, note: str = "") -> None:
    services.db.insert(
        "pub_history",
        {
            "article_id": article_id,
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "actor_id": actor_id,
            "actor_role": role,
            "note": note[:2000],
            "created_at": iso(),
        },
    )


# ---------------------------------------------------------- create and edit
def _clean_fields(body: dict[str, Any], *, staff: bool) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, limit in TEXT_LIMITS.items():
        if name in body:
            text = str(body[name] or "").strip()
            if len(text) > limit:
                raise Invalid(f"{name}: keep it under {limit} characters")
            values[name] = text
    if "citations" in body:
        values["citations_json"] = json.dumps(_citations(body["citations"]))
    if "rights_warranty" in body:
        values["rights_warranty"] = 1 if body["rights_warranty"] is True else 0
    if "sponsorship_declaration" in body:
        decl = str(body["sponsorship_declaration"])
        if decl not in ("none", "paid", "in_kind"):
            raise Invalid("sponsorship_declaration: choose none, paid or in_kind")
        values["sponsorship_declaration"] = decl
    if "section" in body:
        section = body["section"] or None
        if section is not None and section not in SECTIONS:
            raise Invalid("section: choose nigeria, africa or global")
        values["section"] = section
    if "article_type" in body:
        kind = str(body["article_type"])
        allowed = ("commentary", "news", "opinion", "submission") if staff else ("submission",)
        if kind not in allowed:
            raise Invalid("article_type: not allowed for your role")
        values["article_type"] = kind
    return values


def create_article(services: Services, principal: Principal, body: dict[str, Any]) -> dict[str, Any]:
    staff = principal.staff_role in EDITORIAL_STAFF
    values = _clean_fields(body, staff=staff)
    if not values.get("title"):
        raise Invalid("title: is required")
    if values.get("sponsorship_declaration", "none") != "none":
        values["article_type"] = "sponsored"
    article_id = new_id("art")
    stamp = iso()
    row = {
        "id": article_id,
        "slug": f"{_slugify(values['title'])}-{article_id[-6:]}",
        "author_user_id": principal.user_id,
        "author_name": values.pop("author_name", "") or principal.name,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "state": "draft",
        **values,
    }
    with services.db.transaction():
        services.db.insert("pub_articles", row)
        article = get_article(services, article_id)
        _append_revision(services, article, 1, principal.user_id, "created")
        _history(services, article_id, "create", "draft", "draft", principal.user_id, "author")
    services.audit.record("publishing.article.create", "article", article_id, actor_id=principal.user_id)
    return article


def update_article(services: Services, principal: Principal, article_id: str, body: dict[str, Any]) -> dict[str, Any]:
    article = visible_article(services, principal, article_id)
    if article["author_user_id"] != principal.user_id:
        raise Forbidden("Only the author edits a submission; editors request revisions")
    if article["state"] not in EDITABLE_BY_AUTHOR:
        raise Conflict(f"An article in state {article['state']} cannot be edited")
    values = _clean_fields(body, staff=principal.staff_role in EDITORIAL_STAFF)
    if "title" in values and not values["title"]:
        raise Invalid("title: is required")
    declaration = values.get("sponsorship_declaration", article["sponsorship_declaration"])
    if declaration != "none":
        values["article_type"] = "sponsored"
    elif article["article_type"] == "sponsored" and not article["sponsorship_id"]:
        values["article_type"] = "submission"
    if not values:
        return article
    version = article["version"] + 1
    values.update({"version": version, "updated_at": iso(), "legal_signoff_by": None, "legal_signoff_at": None})
    with services.db.transaction():
        services.db.update("pub_articles", values, "id = ?", (article_id,))
        article = get_article(services, article_id)
        _append_revision(services, article, version, principal.user_id, "edited")
    services.audit.record("publishing.article.edit", "article", article_id, actor_id=principal.user_id, data={"version": version})
    return article


def classify(services: Services, principal: Principal, article_id: str, body: dict[str, Any]) -> dict[str, Any]:
    article = visible_article(services, principal, article_id)
    _check_role(principal, "editor", article)
    if article["state"] not in PRE_PUBLISH:
        raise Conflict("Classify an article before it is published")
    values: dict[str, Any] = {}
    if "article_type" in body:
        kind = str(body["article_type"])
        if kind not in TYPE_LABEL:
            raise Invalid("article_type: unknown type")
        if kind != "sponsored" and (article["sponsorship_declaration"] != "none" or article["sponsorship_id"]):
            raise Conflict("Paid content must stay labelled sponsored")
        values["article_type"] = kind
    if "section" in body:
        section = body["section"] or None
        if section is not None and section not in SECTIONS:
            raise Invalid("section: choose nigeria, africa or global")
        values["section"] = section
    if values:
        values["updated_at"] = iso()
        services.db.update("pub_articles", values, "id = ?", (article_id,))
        services.audit.record("publishing.article.classify", "article", article_id, actor_id=principal.user_id, data=values)
    return get_article(services, article_id)


# ------------------------------------------------------------------ guards
def _guard_submit(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    missing = [
        name
        for name in ("title", "summary", "body", "author_credentials", "affiliation", "jurisdiction", "conflicts", "ai_disclosure")
        if not str(article.get(name) or "").strip()
    ]
    if missing:
        raise Invalid(f"{missing[0]}: is required before submission")
    if not json.loads(article["citations_json"] or "[]"):
        raise Invalid("citations: add at least one source")
    if not article["rights_warranty"]:
        raise Invalid("rights_warranty: you must confirm you hold the rights to publish this work")
    return {"feedback": ""}


def _guard_note(field: str) -> Any:
    def guard(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        note = str(body.get("note", "")).strip()
        if not note:
            raise Invalid(f"note: {field} is required")
        return {"feedback": note[:2000]} if field == "feedback" else {}

    return guard


def _guard_sign_off(services: Services, article: dict[str, Any], body: dict[str, Any], actor: Principal) -> dict[str, Any]:
    return {"legal_signoff_by": actor.user_id, "legal_signoff_at": iso()}


def _guard_approve(services: Services, article: dict[str, Any], body: dict[str, Any], actor: Principal) -> dict[str, Any]:
    """Editorial approval. Reads only editorial fields: never payment or orders."""
    if not article["legal_signoff_by"]:
        raise Conflict("Fact and legal review must be signed off by a legal reviewer first")
    if article["author_user_id"] == actor.user_id:
        raise Conflict("An editor cannot approve their own article")
    return {"approved_by": actor.user_id, "approved_at": iso()}


def _guard_schedule(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    when = parse_when(body.get("scheduled_for", ""), "scheduled_for")
    if when <= now():
        raise Invalid("scheduled_for: choose a time in the future")
    return {"scheduled_for": iso(when)}


def publish_blockers(services: Services, article: dict[str, Any]) -> list[str]:
    """SPON-03 and SPON-04 checks for paid content. Payment state is not consulted."""
    if not is_paid(article):
        return []
    from .commerce import audience_status

    problems = []
    disclosure = disclosure_for(services, article["id"])
    if disclosure is None or not disclosure["sponsor_name"].strip() or not disclosure["funding_relationship"].strip():
        problems.append("Paid content needs a disclosure record naming the sponsor and the funding relationship")
    elif disclosure["arcon_required"] and not (disclosure["arcon_reference"] or "").strip():
        problems.append("This sponsored content needs an ARCON vetting reference before publication")
    if not audience_status(services)["open"]:
        problems.append("Sponsored publishing is closed until the newsletter reaches the audience threshold")
    return problems


def _guard_publish(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    problems = publish_blockers(services, article)
    if problems:
        raise Conflict(problems[0])
    return {"published_at": iso(), "scheduled_for": None}


def _guard_correct(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    note = str(body.get("note", "")).strip()
    if not note:
        raise Invalid("note: a public correction note is required")
    values: dict[str, Any] = {}
    for name in ("title", "summary", "body"):
        if name in body:
            text = str(body[name] or "").strip()
            if not text or len(text) > TEXT_LIMITS[name]:
                raise Invalid(f"{name}: is required and must be under {TEXT_LIMITS[name]} characters")
            values[name] = text
    if "citations" in body:
        values["citations_json"] = json.dumps(_citations(body["citations"]))
    return values


def _guard_withdraw(services: Services, article: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    reason = str(body.get("note", "")).strip()
    if not reason:
        raise Invalid("note: give the public reason for withdrawal")
    return {"withdrawn_at": iso(), "withdrawn_reason": reason[:1000], "scheduled_for": None}


GUARDS = {
    "submit": _guard_submit,
    "request_revision": _guard_note("feedback"),
    "reject": _guard_note("feedback"),
    "schedule": _guard_schedule,
    "publish": _guard_publish,
    "correct": _guard_correct,
    "withdraw": _guard_withdraw,
}
ACTOR_GUARDS = {"sign_off": _guard_sign_off, "approve": _guard_approve}


def transition(services: Services, principal: Principal | None, article_id: str, action: str, body: dict[str, Any], *, system: bool = False) -> dict[str, Any]:
    """Applies one workflow action. ``system`` is the scheduler (no principal)."""
    if action not in TRANSITIONS:
        raise NotFound(f"Unknown action {action}")
    sources, target, who = TRANSITIONS[action]
    if system:
        article, role, actor_id = get_article(services, article_id), "system", None
    else:
        assert principal is not None
        article = visible_article(services, principal, article_id)
        role = _check_role(principal, who, article)
        actor_id = principal.user_id
    if article["state"] not in sources:
        raise Conflict(f"Cannot {action.replace('_', ' ')} an article in state {article['state']}")
    if action in ACTOR_GUARDS:
        assert principal is not None
        values = ACTOR_GUARDS[action](services, article, body, principal)
    else:
        values = GUARDS[action](services, article, body) if action in GUARDS else {}
    content_changed = any(k in values for k in ("title", "summary", "body", "citations_json"))
    version = article["version"] + 1 if content_changed else article["version"]
    values.update({"state": target, "updated_at": iso(), "version": version})
    note = str(body.get("note", "")).strip()
    with services.db.transaction():
        services.db.update("pub_articles", values, "id = ?", (article_id,))
        updated = get_article(services, article_id)
        if content_changed:
            _append_revision(services, updated, version, actor_id, "correction")
        if action == "correct":
            services.db.insert(
                "pub_corrections",
                {"id": new_id("cor"), "article_id": article_id, "version": version, "note": note[:2000], "actor_id": actor_id, "created_at": iso()},
            )
        _history(services, article_id, action, article["state"], target, actor_id, role, note)
    services.audit.record(
        f"publishing.article.{action}", "article", article_id, actor_id=actor_id, data={"from": article["state"], "to": target, "role": role}
    )
    return updated


def run_due(services: Services) -> dict[str, Any]:
    """Publishes scheduled articles whose time has come; called by the scheduler or staff."""
    published, held = [], []
    for row in services.db.query("SELECT id, scheduled_for FROM pub_articles WHERE state = 'scheduled'"):
        if row["scheduled_for"] and parse_when(row["scheduled_for"], "scheduled_for") <= now():
            try:
                transition(services, None, row["id"], "publish", {}, system=True)
                published.append(row["id"])
            except Conflict as exc:
                held.append({"id": row["id"], "reason": str(exc)})
    return {"published": published, "held": held}


# ------------------------------------------------------------ app read views
def detail(services: Services, principal: Principal, article_id: str) -> dict[str, Any]:
    article = visible_article(services, principal, article_id)
    out = _private(article)
    out["revisions"] = services.db.query(
        "SELECT version, reason, actor_id, title, created_at FROM pub_revisions WHERE article_id = ? ORDER BY version", (article_id,)
    )
    out["history"] = services.db.query(
        "SELECT action, from_state, to_state, actor_role, note, created_at FROM pub_history WHERE article_id = ? ORDER BY id", (article_id,)
    )
    out["corrections"] = corrections(services, article_id)
    out["disclosure"] = disclosure_for(services, article_id)
    out["publish_blockers"] = publish_blockers(services, article) if article["state"] in ("approved", "scheduled") else []
    out["labels"] = labels(services, article)
    out["allowed_actions"] = allowed_actions(principal, article)
    return out


def _private(article: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in article.items() if k != "citations_json"}
    out["citations"] = json.loads(article["citations_json"] or "[]")
    out["rights_warranty"] = bool(article["rights_warranty"])
    out["badge"] = TYPE_LABEL[article["article_type"]]
    return out


def allowed_actions(principal: Principal, article: dict[str, Any]) -> list[str]:
    out = []
    for action, (sources, _target, who) in TRANSITIONS.items():
        if article["state"] not in sources:
            continue
        try:
            _check_role(principal, who, article)
        except Forbidden:
            continue
        out.append(action)
    return out


def mine(services: Services, principal: Principal) -> list[dict[str, Any]]:
    rows = services.db.query(
        "SELECT id, slug, title, state, article_type, feedback, updated_at, version FROM pub_articles WHERE author_user_id = ? ORDER BY updated_at DESC",
        (principal.user_id,),
    )
    for r in rows:
        r["badge"] = TYPE_LABEL[r["article_type"]]
    return rows


def queue(services: Services, principal: Principal, state: str | None) -> list[dict[str, Any]]:
    role = principal.staff_role
    if role == "legal_reviewer":
        sql, params = "SELECT * FROM pub_articles WHERE state = 'fact_legal_review'", []
    elif role in EDITORIAL_STAFF:
        sql, params = "SELECT * FROM pub_articles WHERE state != 'draft'", []
        if state:
            sql, params = "SELECT * FROM pub_articles WHERE state = ?", [state]
    else:
        raise Forbidden("Editorial queue is for editors and legal reviewers")
    rows = services.db.query(sql + " ORDER BY updated_at DESC LIMIT 200", params)
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "state": r["state"],
            "badge": TYPE_LABEL[r["article_type"]],
            "sponsored": is_paid(r),
            "legal_signed_off": bool(r["legal_signoff_by"]),
            "author_name": r["author_name"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


# --------------------------------------------- labels and public distribution
def labels(services: Services, article: dict[str, Any]) -> dict[str, Any]:
    paid = is_paid(article)
    disclosure = disclosure_for(services, article["id"]) if paid else None
    text = policy(services).get("labels", {})
    label = None
    if paid:
        label = disclosure["label"] if disclosure else text.get("sponsored", "Sponsored")
    return {
        "badge": TYPE_LABEL[article["article_type"]],
        "sponsored": paid,
        "label": label,
        "sponsor": (
            {"name": disclosure["sponsor_name"], "funding_relationship": disclosure["funding_relationship"]} if disclosure else None
        ),
    }


def corrections(services: Services, article_id: str) -> list[dict[str, Any]]:
    return services.db.query("SELECT version, note, created_at FROM pub_corrections WHERE article_id = ? ORDER BY created_at, version", (article_id,))


def public_url(article: dict[str, Any]) -> str:
    return f"{SITE_URL}/#/insights/{article['slug']}"


def card(services: Services, article: dict[str, Any]) -> dict[str, Any]:
    tag = labels(services, article)
    return {
        "id": article["id"],
        "slug": article["slug"],
        "title": article["title"],
        "summary": article["summary"],
        "article_type": article["article_type"],
        "section": article["section"],
        "author_name": article["author_name"],
        "affiliation": article["affiliation"],
        "published_at": article["published_at"],
        "corrected": article["state"] == "corrected",
        "url": f"/insights/{article['slug']}",
        **tag,
    }


def json_ld(services: Services, article: dict[str, Any], tag: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "NewsArticle" if article["article_type"] == "news" else "Article",
        "headline": article["title"],
        "description": article["summary"],
        "datePublished": article["published_at"],
        "dateModified": article["updated_at"],
        "url": public_url(article),
        "author": {"@type": "Person", "name": article["author_name"], "affiliation": article["affiliation"]},
        "publisher": {"@type": "Organization", "name": PUBLISHER},
        "genre": tag["badge"],
    }
    if tag["sponsored"]:
        data["sponsor"] = {"@type": "Organization", "name": tag["sponsor"]["name"] if tag["sponsor"] else "Undisclosed sponsor"}
        data["genre"] = tag["label"]
    return data


def open_graph(article: dict[str, Any], tag: dict[str, Any]) -> dict[str, str]:
    title = f"{tag['label']}: {article['title']}" if tag["sponsored"] else article["title"]
    description = f"{tag['label']} content. {article['summary']}" if tag["sponsored"] else article["summary"]
    og = {
        "og:type": "article",
        "og:site_name": "tax.ng",
        "og:title": title,
        "og:description": description,
        "og:url": public_url(article),
        "article:published_time": article["published_at"] or "",
        "twitter:card": "summary",
        "twitter:title": title,
        "twitter:description": description,
    }
    if tag["sponsored"]:
        og["article:tag"] = tag["label"]
        if tag["sponsor"]:
            og["article:sponsor"] = tag["sponsor"]["name"]
    return og


def published(services: Services, *, article_type: str | None = None, section: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM pub_articles WHERE state IN ('published', 'corrected')"
    params: list[Any] = []
    if article_type:
        sql += " AND article_type = ?"
        params.append(article_type)
    if section:
        sql += " AND section = ?"
        params.append(section)
    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)
    return services.db.query(sql, params)


def public_page(services: Services, slug: str) -> dict[str, Any]:
    article = services.db.one(
        "SELECT * FROM pub_articles WHERE slug = ? AND state IN ('published', 'corrected', 'withdrawn')", (slug,)
    )
    if article is None:
        raise NotFound("Article not found")
    if article["state"] == "withdrawn":
        return {
            "slug": article["slug"],
            "title": article["title"],
            "state": "withdrawn",
            "tombstone": True,
            "withdrawn_at": article["withdrawn_at"],
            "withdrawn_reason": article["withdrawn_reason"],
            "corrections": corrections(services, article["id"]),
            "meta": {"robots": "noindex", "open_graph": {"og:title": f"Withdrawn: {article['title']}", "og:type": "article"}},
        }
    tag = labels(services, article)
    out = card(services, article)
    out.update(
        {
            "state": article["state"],
            "tombstone": False,
            "body": article["body"],
            "citations": json.loads(article["citations_json"] or "[]"),
            "author_credentials": article["author_credentials"],
            "jurisdiction": article["jurisdiction"],
            "conflicts": article["conflicts"],
            "ai_disclosure": article["ai_disclosure"],
            "version": article["version"],
            "updated_at": article["updated_at"],
            "header_label": tag["label"],
            "corrections": corrections(services, article["id"]),
            "meta": {"json_ld": json_ld(services, article, tag), "open_graph": open_graph(article, tag)},
        }
    )
    return out


def search(services: Services, q: str) -> list[dict[str, Any]]:
    articles = {a["id"]: a for a in published(services, limit=500)}
    docs = [Document(a["id"], "article", a["title"], " ".join([a["summary"], a["body"], a["author_name"]])) for a in articles.values()]
    out = []
    if docs:
        for hit in SearchIndex(docs).search(q, limit=10):
            c = card(services, articles[hit.document.id])
            out.append({"id": c["id"], "kind": "article", "title": c["title"], "url": c["url"], "summary": c["summary"], "badge": c["badge"], "sponsored": c["sponsored"], "label": c["label"]})
    for hit in services.index.search(q, limit=10):
        path = "/laws/" if hit.document.kind == "provision" else "/reform/"
        out.append({"id": hit.document.id, "kind": hit.document.kind, "title": hit.document.title, "url": path + hit.document.id, "sponsored": False, "label": None})
    return out


def news(services: Services, section: str) -> list[dict[str, Any]]:
    if section not in SECTIONS:
        raise Invalid("section: choose nigeria, africa or global")
    items: list[dict[str, Any]] = [
        {
            "id": n.id,
            "date": n.date.isoformat(),
            "section": n.section,
            "headline": n.headline,
            "standfirst": n.standfirst,
            "source_name": n.source_name,
            "source_url": n.source_url,
            "sample": n.sample,
            "url": None,
            "sponsored": False,
            "label": None,
        }
        for n in services.library.news
        if n.section == section
    ]
    for a in published(services, article_type="news", section=section):
        tag = labels(services, a)
        items.append(
            {
                "id": a["id"],
                "date": (a["published_at"] or "")[:10],
                "section": section,
                "headline": a["title"],
                "standfirst": a["summary"],
                "source_name": "tax.ng",
                "source_url": None,
                "sample": False,
                "url": f"/insights/{a['slug']}",
                "sponsored": tag["sponsored"],
                "label": tag["label"],
            }
        )
    items.sort(key=lambda i: i["date"], reverse=True)
    return items


def rss(services: Services, section: str | None) -> bytes:
    if section and section not in SECTIONS:
        raise Invalid("section: choose nigeria, africa or global")
    entries = []
    for a in published(services, section=section, limit=50):
        tag = labels(services, a)
        title = f"{tag['label']}: {a['title']}" if tag["sponsored"] else a["title"]
        cats = [f"<category>{escape(tag['badge'])}</category>"]
        if tag["sponsored"]:
            cats = [f"<category>{escape(tag['label'])}</category>"]
            if tag["sponsor"]:
                cats.append(f"<category>{escape('Sponsor: ' + tag['sponsor']['name'])}</category>")
        published_at = dt.datetime.fromisoformat(a["published_at"]).strftime("%a, %d %b %Y %H:%M:%S +0000") if a["published_at"] else ""
        entries.append(
            "<item>"
            f"<title>{escape(title)}</title>"
            f"<link>{escape(public_url(a))}</link>"
            f"<guid isPermaLink=\"false\">{escape(a['id'])}</guid>"
            f"<description>{escape(a['summary'])}</description>"
            f"<pubDate>{published_at}</pubDate>"
            + "".join(cats)
            + "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        "<title>tax.ng Insights</title>"
        f"<link>{SITE_URL}/#/insights</link>"
        "<description>Commentary, news and analysis on Nigerian and international tax from tax.ng.</description>"
        + "".join(entries)
        + "</channel></rss>"
    )
    return xml.encode()


# ---------------------------------------------------------------- complaints
COMPLAINT_KINDS = ("accuracy", "legal", "privacy", "sponsorship", "advertising", "other")
COMPLAINT_FLOW = {"received": ("investigating", "resolved", "rejected"), "investigating": ("resolved", "rejected")}


def complaint_token(services: Services, complaint_id: str) -> str:
    return sign(services.secret, f"complaint:{complaint_id}")[:32]


def file_complaint(services: Services, principal: Principal | None, body: dict[str, Any]) -> dict[str, Any]:
    kind = str(body.get("kind", ""))
    if kind not in COMPLAINT_KINDS:
        raise Invalid("kind: choose " + ", ".join(COMPLAINT_KINDS))
    details = str(body.get("details", "")).strip()
    if len(details) < 10 or len(details) > 5000:
        raise Invalid("details: describe the problem in 10 to 5000 characters")
    article_id = None
    slug = str(body.get("article_slug", "") or "").strip()
    if slug:
        row = services.db.one("SELECT id FROM pub_articles WHERE slug = ? AND state IN ('published', 'corrected', 'withdrawn')", (slug,))
        if row is None:
            raise Invalid("article_slug: no published article has that address")
        article_id = row["id"]
    email = str(body.get("contact_email", "") or "").strip().lower()[:254] or None
    if email and "@" not in email:
        raise Invalid("contact_email: enter a valid email address")
    complaint_id = new_id("cmp")
    stamp = iso()
    services.db.insert(
        "pub_complaints",
        {
            "id": complaint_id,
            "article_id": article_id,
            "kind": kind,
            "details": details,
            "contact_email": email,
            "submitted_by": principal.user_id if principal else None,
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    services.audit.record("publishing.complaint.received", "complaint", complaint_id, actor_id=principal.user_id if principal else None, data={"kind": kind, "article_id": article_id})
    return {"id": complaint_id, "status": "received", "tracking_token": complaint_token(services, complaint_id)}


def complaint_status(services: Services, complaint_id: str, token: str) -> dict[str, Any]:
    row = services.db.one("SELECT id, kind, status, resolution, created_at, updated_at FROM pub_complaints WHERE id = ?", (complaint_id,))
    if row is None or not hmac.compare_digest(complaint_token(services, complaint_id), token or ""):
        raise NotFound("Complaint not found")
    return row


def update_complaint(services: Services, principal: Principal, complaint_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_complaints WHERE id = ?", (complaint_id,))
    if row is None:
        raise NotFound("Complaint not found")
    status = str(body.get("status", ""))
    if status not in COMPLAINT_FLOW.get(row["status"], ()):
        raise Conflict(f"Cannot move a {row['status']} complaint to {status or 'nothing'}")
    resolution = str(body.get("resolution", "")).strip()[:2000]
    if status in ("resolved", "rejected") and not resolution:
        raise Invalid("resolution: explain the outcome")
    services.db.update("pub_complaints", {"status": status, "resolution": resolution, "handled_by": principal.user_id, "updated_at": iso()}, "id = ?", (complaint_id,))
    services.audit.record("publishing.complaint.status", "complaint", complaint_id, actor_id=principal.user_id, data={"from": row["status"], "to": status})
    return services.db.one("SELECT * FROM pub_complaints WHERE id = ?", (complaint_id,)) or {}
