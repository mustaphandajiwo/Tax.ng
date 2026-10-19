"""Newsletter editions (NEWS-02, NEWS-04): Nigerian Tax Brief and Global Tax Watch.

Workflow: select stories -> draft -> fact_check -> fact_checked -> approved
-> (preview) -> scheduled -> sent -> archived. Sending uses the platform
subscriber list and the sandbox outbox, and every message carries an
unsubscribe line. Sent editions are public in the archive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ...api.router import NotFound
from ...platform.access import Forbidden, Principal
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id, now
from .commerce import audience_status, serve
from .service import EDITORIAL_STAFF, SITE_URL, card, labels, parse_when

if TYPE_CHECKING:
    from ...services import Services

NEWSLETTERS = {"nigerian_tax_brief": "Nigerian Tax Brief", "global_tax_watch": "Global Tax Watch"}

# action -> (from states, to state, roles)
FLOW: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {
    "submit": (("draft",), "fact_check", EDITORIAL_STAFF),
    "fact_checked": (("fact_check",), "fact_checked", EDITORIAL_STAFF + ("legal_reviewer",)),
    "approve": (("fact_checked",), "approved", EDITORIAL_STAFF),
    "revise": (("fact_check", "fact_checked", "approved", "scheduled"), "draft", EDITORIAL_STAFF + ("legal_reviewer",)),
    "schedule": (("approved",), "scheduled", EDITORIAL_STAFF),
    "send": (("approved", "scheduled"), "sent", EDITORIAL_STAFF),
    "archive": (("sent",), "archived", EDITORIAL_STAFF),
}


def _edition(services: Services, edition_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_editions WHERE id = ?", (edition_id,))
    if row is None:
        raise NotFound("Edition not found")
    return row


def _items(services: Services, raw: Any) -> str:
    if not isinstance(raw, list):
        raise Invalid("items: send a list of stories")
    news_ids = {n.id for n in services.library.news}
    clean = []
    for item in raw[:30]:
        kind, ref = str((item or {}).get("kind", "")), str((item or {}).get("id", ""))
        if kind == "article":
            if not services.db.one("SELECT 1 FROM pub_articles WHERE id = ? AND state IN ('published', 'corrected')", (ref,)):
                raise Invalid(f"items: article {ref} is not published")
        elif kind == "news":
            if ref not in news_ids:
                raise Invalid(f"items: news item {ref} not found")
        else:
            raise Invalid("items: kind must be article or news")
        clean.append({"kind": kind, "id": ref})
    return json.dumps(clean)


def _sponsorship(services: Services, value: Any) -> str | None:
    if not value:
        return None
    order = services.db.one("SELECT * FROM pub_sponsorships WHERE id = ?", (str(value),))
    if order is None or order["placement"] != "newsletter_sponsor" or order["status"] != "open":
        raise Invalid("sponsorship_id: choose an open newsletter sponsor order")
    return order["id"]


def create(services: Services, principal: Principal, body: dict[str, Any]) -> dict[str, Any]:
    newsletter = str(body.get("newsletter", ""))
    if newsletter not in NEWSLETTERS:
        raise Invalid("newsletter: choose nigerian_tax_brief or global_tax_watch")
    title = str(body.get("title", "")).strip()
    if not title or len(title) > 200:
        raise Invalid("title: is required (under 200 characters)")
    stamp = iso()
    row = {
        "id": new_id("edn"),
        "newsletter": newsletter,
        "title": title,
        "intro": str(body.get("intro", "")).strip()[:2000],
        "items_json": _items(services, body.get("items", [])),
        "sponsorship_id": _sponsorship(services, body.get("sponsorship_id")),
        "created_by": principal.user_id,
        "created_at": stamp,
        "updated_at": stamp,
    }
    services.db.insert("pub_editions", row)
    services.audit.record("publishing.edition.create", "edition", row["id"], actor_id=principal.user_id, data={"newsletter": newsletter})
    return view(services, _edition(services, row["id"]))


def update(services: Services, principal: Principal, edition_id: str, body: dict[str, Any]) -> dict[str, Any]:
    edition = _edition(services, edition_id)
    if edition["state"] != "draft":
        raise Conflict("Only a draft edition can be changed; send it back to draft first")
    values: dict[str, Any] = {}
    if "title" in body:
        title = str(body["title"]).strip()
        if not title or len(title) > 200:
            raise Invalid("title: is required (under 200 characters)")
        values["title"] = title
    if "intro" in body:
        values["intro"] = str(body["intro"]).strip()[:2000]
    if "items" in body:
        values["items_json"] = _items(services, body["items"])
    if "sponsorship_id" in body:
        values["sponsorship_id"] = _sponsorship(services, body["sponsorship_id"])
    if values:
        values.update({"updated_at": iso(), "fact_checked_by": None, "approved_by": None})
        services.db.update("pub_editions", values, "id = ?", (edition_id,))
        services.audit.record("publishing.edition.edit", "edition", edition_id, actor_id=principal.user_id)
    return view(services, _edition(services, edition_id))


def sponsor_slot(services: Services, edition: dict[str, Any]) -> dict[str, Any] | None:
    if not edition["sponsorship_id"]:
        return None
    order = services.db.one("SELECT * FROM pub_sponsorships WHERE id = ?", (edition["sponsorship_id"],))
    if order is None:
        return None
    return {"label": order["label"], "sponsor": order["sponsor_name"], "funding_relationship": order["funding_relationship"], "description": order["description"]}


def _send_blockers(services: Services, edition: dict[str, Any]) -> list[str]:
    if not edition["sponsorship_id"]:
        return []
    order = services.db.one("SELECT * FROM pub_sponsorships WHERE id = ?", (edition["sponsorship_id"],))
    problems = []
    if order is None or order["status"] != "open":
        problems.append("The sponsor order is no longer open")
    elif not order["sponsor_name"].strip() or not order["funding_relationship"].strip():
        problems.append("The sponsor slot needs the sponsor's name and funding relationship")
    elif order["arcon_required"] and not (order["arcon_reference"] or "").strip():
        problems.append("The sponsor slot needs an ARCON vetting reference")
    if not audience_status(services)["open"]:
        problems.append("Newsletter sponsorship is closed until the audience threshold is reached")
    return problems


def render(services: Services, edition: dict[str, Any], recipient: str | None = None) -> dict[str, Any]:
    """Edition content as data and as plain text. Labels propagate to every item."""
    news = {n.id: n for n in services.library.news}
    items = []
    for ref in json.loads(edition["items_json"] or "[]"):
        if ref["kind"] == "article":
            row = services.db.one("SELECT * FROM pub_articles WHERE id = ?", (ref["id"],))
            if row is None or row["state"] not in ("published", "corrected"):
                continue
            c = card(services, row)
            items.append({"kind": "article", "id": c["id"], "title": c["title"], "summary": c["summary"], "url": f"{SITE_URL}/#{c['url']}", "badge": c["badge"], "sponsored": c["sponsored"], "label": c["label"], "sponsor": c["sponsor"]})
        else:
            n = news.get(ref["id"])
            if n:
                items.append({"kind": "news", "id": n.id, "title": n.headline, "summary": n.standfirst, "url": n.source_url, "badge": "News", "source_name": n.source_name, "sample": n.sample, "sponsored": False, "label": None, "sponsor": None})
    sponsor = sponsor_slot(services, edition)
    ad = serve(services, "newsletter", {})["ad"]
    lines = [NEWSLETTERS[edition["newsletter"]], edition["title"], ""]
    if edition["intro"]:
        lines += [edition["intro"], ""]
    if sponsor:
        lines += [f"[{sponsor['label']}] This edition is supported by {sponsor['sponsor']} ({sponsor['funding_relationship']}).", ""]
    for i in items:
        prefix = f"[{i['label']}] " if i["sponsored"] else ""
        lines += [f"{prefix}{i['title']}", i["summary"], i["url"] or "", ""]
    if ad:
        lines += [f"[{ad['label']}] {ad['headline']} ({ad['advertiser']})", ad["body"], ad["link_url"], ""]
    unsubscribe = None
    if recipient:
        token = services.store.token_for(recipient)
        unsubscribe = f"{SITE_URL}/#/newsletter/unsubscribe/{quote(recipient, safe='')}/{token}"
        lines += ["You receive this because you subscribed at tax.ng.", f"Unsubscribe: {unsubscribe}"]
    lines += ["tax.ng is owned and licensed by Astound Innovation Hub. General information, not tax advice."]
    return {
        "subject": f"{NEWSLETTERS[edition['newsletter']]}: {edition['title']}",
        "newsletter": edition["newsletter"],
        "newsletter_name": NEWSLETTERS[edition["newsletter"]],
        "items": items,
        "sponsor": sponsor,
        "ad": ad,
        "unsubscribe_url": unsubscribe,
        "text": "\n".join(lines),
    }


def view(services: Services, edition: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in edition.items() if k != "items_json"}
    out["items"] = json.loads(edition["items_json"] or "[]")
    out["newsletter_name"] = NEWSLETTERS[edition["newsletter"]]
    out["sponsor"] = sponsor_slot(services, edition)
    out["send_blockers"] = _send_blockers(services, edition) if edition["state"] in ("approved", "scheduled") else []
    return out


def _deliver(services: Services, edition: dict[str, Any]) -> int:
    sent = 0
    for email in services.store.subscribers(edition["newsletter"]):
        content = render(services, edition, email)
        services.notifier.send("email", email, content["text"], subject=content["subject"])
        sent += 1
    return sent


def transition(services: Services, principal: Principal | None, edition_id: str, action: str, body: dict[str, Any], *, system: bool = False) -> dict[str, Any]:
    if action not in FLOW:
        raise NotFound(f"Unknown action {action}")
    sources, target, roles = FLOW[action]
    if not system:
        assert principal is not None
        if principal.staff_role not in roles:
            raise Forbidden("Your role cannot change this edition")
    edition = _edition(services, edition_id)
    if edition["state"] not in sources:
        raise Conflict(f"Cannot {action.replace('_', ' ')} an edition in state {edition['state']}")
    actor_id = principal.user_id if principal else None
    values: dict[str, Any] = {"state": target, "updated_at": iso()}
    if action == "submit" and not json.loads(edition["items_json"] or "[]"):
        raise Conflict("Select at least one story first")
    if action == "fact_checked":
        values["fact_checked_by"] = actor_id
    if action == "approve":
        values["approved_by"] = actor_id
    if action == "revise":
        values.update({"fact_checked_by": None, "approved_by": None, "scheduled_for": None})
    if action == "schedule":
        when = parse_when(body.get("scheduled_for", ""), "scheduled_for")
        if when <= now():
            raise Invalid("scheduled_for: choose a time in the future")
        values["scheduled_for"] = iso(when)
    if action == "send":
        problems = _send_blockers(services, edition)
        if problems:
            raise Conflict(problems[0])
        values["sent_count"] = _deliver(services, edition)
        values["sent_at"] = iso()
    services.db.update("pub_editions", values, "id = ?", (edition_id,))
    services.audit.record(
        f"publishing.edition.{action}", "edition", edition_id, actor_id=actor_id, data={"from": edition["state"], "to": target, "sent": values.get("sent_count")}
    )
    return view(services, _edition(services, edition_id))


def run_due(services: Services) -> dict[str, Any]:
    sent, held = [], []
    for row in services.db.query("SELECT id, scheduled_for FROM pub_editions WHERE state = 'scheduled'"):
        if row["scheduled_for"] and parse_when(row["scheduled_for"], "scheduled_for") <= now():
            try:
                transition(services, None, row["id"], "send", {}, system=True)
                sent.append(row["id"])
            except Conflict as exc:
                held.append({"id": row["id"], "reason": str(exc)})
    return {"sent": sent, "held": held}


def listing(services: Services) -> list[dict[str, Any]]:
    return [view(services, r) for r in services.db.query("SELECT * FROM pub_editions ORDER BY updated_at DESC LIMIT 200")]


def archive(services: Services) -> list[dict[str, Any]]:
    rows = services.db.query(
        "SELECT id, newsletter, title, intro, sent_at, sponsorship_id FROM pub_editions WHERE state IN ('sent', 'archived') ORDER BY sent_at DESC"
    )
    return [
        {"id": r["id"], "newsletter": r["newsletter"], "newsletter_name": NEWSLETTERS[r["newsletter"]], "title": r["title"], "intro": r["intro"], "sent_at": r["sent_at"], "sponsored": bool(r["sponsorship_id"])}
        for r in rows
    ]


def archived_edition(services: Services, edition_id: str) -> dict[str, Any]:
    edition = _edition(services, edition_id)
    if edition["state"] not in ("sent", "archived"):
        raise NotFound("Edition not found")
    content = render(services, edition)
    return {"id": edition["id"], "title": edition["title"], "intro": edition["intro"], "sent_at": edition["sent_at"], **content}


def newsletter_items(services: Services, limit: int = 10) -> list[dict[str, Any]]:
    """Contract for other modules: recent published articles with their labels."""
    from .service import published

    return [card(services, a) for a in published(services, limit=limit)]


__all__ = ["NEWSLETTERS", "archive", "archived_edition", "create", "labels", "listing", "newsletter_items", "render", "run_due", "transition", "update", "view"]
