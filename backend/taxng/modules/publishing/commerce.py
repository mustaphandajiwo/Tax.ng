"""Sponsorship orders, disclosure records, display advertising and payments (SPON-02 to SPON-05, Annex B).

Rules that live here:

* SPON-04: sponsored publishing and display ads open only once active
  newsletter subscribers reach the audience threshold (policy.yaml, or
  ``TAXNG_SPONSOR_THRESHOLD`` for demos).
* Payment is taken through the billing module's contract. A paid webhook only
  updates ``payment_status`` on the order; it never touches an article's
  editorial state.
* Ads are never targeted. The serve endpoint takes only the slot and the page
  path, never reads the caller, and rejects any other input. Counters are
  aggregate daily totals.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from ...platform.access import Forbidden, Principal
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id, now
from .service import PUBLIC_STATES, get_article, policy

if TYPE_CHECKING:
    from ...services import Services

LABELS = ("Sponsored", "Paid Partnership")


# ------------------------------------------------------------ SPON-04 gate
def threshold(services: Services) -> int:
    raw = os.environ.get("TAXNG_SPONSOR_THRESHOLD", "").strip()
    if raw.isdigit():
        return int(raw)
    return int(policy(services).get("audience_threshold", 0))


def audience_status(services: Services) -> dict[str, Any]:
    count = services.store.subscriber_count()
    limit = threshold(services)
    return {"subscribers": count, "threshold": limit, "open": count >= limit}


def require_open(services: Services) -> None:
    if not audience_status(services)["open"]:
        raise Conflict("Sponsored publishing and display ads open once the newsletter reaches the audience threshold (SPON-04)")


def _money(kobo: int) -> str:
    return str((Decimal(kobo) / 100).quantize(Decimal("0.01")))


def _kobo(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Invalid("amount_kobo: enter the agreed amount in kobo as a whole number")
    return value


def _text(body: dict[str, Any], name: str, limit: int, *, required: bool = True) -> str:
    text = str(body.get(name, "") or "").strip()
    if required and not text:
        raise Invalid(f"{name}: is required")
    if len(text) > limit:
        raise Invalid(f"{name}: keep it under {limit} characters")
    return text


# ------------------------------------------------------------ sponsorships
def _order(services: Services, order_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_sponsorships WHERE id = ?", (order_id,))
    if row is None:
        raise NotFound("Sponsorship order not found")
    return row


def order_view(services: Services, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["amount"] = _money(row["amount_kobo"])
    out["arcon_required"] = bool(row["arcon_required"])
    out["articles"] = services.db.query("SELECT id, title, state, slug FROM pub_articles WHERE sponsorship_id = ?", (row["id"],))
    out["editions"] = services.db.query("SELECT id, title, state FROM pub_editions WHERE sponsorship_id = ?", (row["id"],))
    return out


def create_order(services: Services, principal: Principal, body: dict[str, Any]) -> dict[str, Any]:
    require_open(services)
    placement = str(body.get("placement", "sponsored_article"))
    if placement not in ("sponsored_article", "newsletter_sponsor"):
        raise Invalid("placement: choose sponsored_article or newsletter_sponsor")
    label = str(body.get("label", "Sponsored"))
    if label not in LABELS:
        raise Invalid("label: choose Sponsored or Paid Partnership")
    stamp = iso()
    row = {
        "id": new_id("spo"),
        "sponsor_name": _text(body, "sponsor_name", 200),
        "funding_relationship": _text(body, "funding_relationship", 500),
        "placement": placement,
        "label": label,
        "arcon_required": 1 if body.get("arcon_required") is True else 0,
        "arcon_reference": _text(body, "arcon_reference", 100, required=False) or None,
        "amount_kobo": _kobo(body.get("amount_kobo")),
        "description": _text(body, "description", 1000, required=False),
        "terms_version": str(policy(services).get("terms_version", "")),
        "created_by": principal.user_id,
        "created_at": stamp,
        "updated_at": stamp,
    }
    services.db.insert("pub_sponsorships", row)
    services.audit.record("publishing.sponsorship.create", "sponsorship", row["id"], actor_id=principal.user_id, data={"placement": placement, "amount_kobo": row["amount_kobo"]})
    return order_view(services, _order(services, row["id"]))


def update_order(services: Services, principal: Principal, order_id: str, body: dict[str, Any]) -> dict[str, Any]:
    order = _order(services, order_id)
    if order["status"] != "open":
        raise Conflict(f"A {order['status']} order cannot be changed")
    values: dict[str, Any] = {}
    if "funding_relationship" in body:
        values["funding_relationship"] = _text(body, "funding_relationship", 500)
    if "arcon_reference" in body:
        values["arcon_reference"] = _text(body, "arcon_reference", 100, required=False) or None
    if "arcon_required" in body:
        values["arcon_required"] = 1 if body["arcon_required"] is True else 0
    if values:
        values["updated_at"] = iso()
        services.db.update("pub_sponsorships", values, "id = ?", (order_id,))
        sync = {k: v for k, v in values.items() if k in ("funding_relationship", "arcon_reference", "arcon_required")}
        if sync:
            services.db.update("pub_disclosures", sync, "sponsorship_id = ?", (order_id,))
        services.audit.record("publishing.sponsorship.update", "sponsorship", order_id, actor_id=principal.user_id, data=sorted(values))
    return order_view(services, _order(services, order_id))


def record_disclosure(
    services: Services, principal: Principal, article_id: str, body: dict[str, Any], *, sponsorship_id: str | None = None
) -> dict[str, Any]:
    """SPON-03: the disclosure record a paid article needs before publication."""
    article = get_article(services, article_id)
    if article["state"] in PUBLIC_STATES + ("withdrawn", "rejected"):
        raise Conflict("Record disclosure before publication")
    label = str(body.get("label", "Sponsored"))
    if label not in LABELS:
        raise Invalid("label: choose Sponsored or Paid Partnership")
    row = {
        "article_id": article_id,
        "sponsorship_id": sponsorship_id,
        "sponsor_name": _text(body, "sponsor_name", 200),
        "funding_relationship": _text(body, "funding_relationship", 500),
        "label": label,
        "arcon_required": 1 if body.get("arcon_required") in (True, 1) else 0,
        "arcon_reference": _text(body, "arcon_reference", 100, required=False) or None,
        "recorded_by": principal.user_id,
        "recorded_at": iso(),
    }
    with services.db.transaction():
        services.db.execute("DELETE FROM pub_disclosures WHERE article_id = ?", (article_id,))
        services.db.insert("pub_disclosures", row)
        services.db.update("pub_articles", {"article_type": "sponsored", "updated_at": iso()}, "id = ?", (article_id,))
    services.audit.record("publishing.disclosure.record", "article", article_id, actor_id=principal.user_id, data={"sponsorship_id": sponsorship_id, "arcon_required": bool(row["arcon_required"])})
    return row


def attach_order(services: Services, principal: Principal, order_id: str, article_id: str) -> dict[str, Any]:
    order = _order(services, order_id)
    if order["status"] != "open":
        raise Conflict(f"A {order['status']} order cannot be attached")
    if order["placement"] != "sponsored_article":
        raise Conflict("This order is for a newsletter sponsor slot")
    article = get_article(services, article_id)
    if article["state"] in PUBLIC_STATES + ("withdrawn", "rejected"):
        raise Conflict("Attach sponsorship before publication")
    services.db.update("pub_articles", {"sponsorship_id": order_id}, "id = ?", (article_id,))
    record_disclosure(
        services,
        principal,
        article_id,
        {
            "sponsor_name": order["sponsor_name"],
            "funding_relationship": order["funding_relationship"],
            "label": order["label"],
            "arcon_required": bool(order["arcon_required"]),
            "arcon_reference": order["arcon_reference"],
        },
        sponsorship_id=order_id,
    )
    return order_view(services, _order(services, order_id))


def reject_order(services: Services, principal: Principal, order_id: str, reason: str) -> dict[str, Any]:
    """SPON-05: tax.ng's right to reject under the published terms, with refund if paid."""
    order = _order(services, order_id)
    if order["status"] != "open":
        raise Conflict(f"A {order['status']} order cannot be rejected")
    if not reason.strip():
        raise Invalid("reason: explain the rejection under the published terms")
    live = services.db.scalar(
        "SELECT COUNT(*) FROM pub_articles WHERE sponsorship_id = ? AND state IN ('published', 'corrected')", (order_id,)
    )
    if live:
        raise Conflict("Withdraw the published article before rejecting its sponsorship")
    payment = "refund_due" if order["payment_status"] == "paid" else ("unpaid" if order["payment_status"] == "pending" else order["payment_status"])
    with services.db.transaction():
        services.db.update(
            "pub_sponsorships",
            {"status": "rejected", "payment_status": payment, "rejection_reason": reason.strip()[:1000], "updated_at": iso()},
            "id = ?",
            (order_id,),
        )
        services.db.execute("DELETE FROM pub_disclosures WHERE sponsorship_id = ?", (order_id,))
        services.db.update("pub_articles", {"sponsorship_id": None}, "sponsorship_id = ?", (order_id,))
        services.db.update("pub_editions", {"sponsorship_id": None}, "sponsorship_id = ? AND state NOT IN ('sent', 'archived')", (order_id,))
    _request_refund(services, "sponsorship", order_id, payment)
    services.audit.record("publishing.sponsorship.reject", "sponsorship", order_id, actor_id=principal.user_id, data={"payment_status": payment})
    return order_view(services, _order(services, order_id))


def record_refund(services: Services, principal: Principal, table: str, entity_id: str) -> dict[str, Any]:
    row = services.db.one(f"SELECT id, payment_status FROM {table} WHERE id = ?", (entity_id,))  # noqa: S608 (fixed table names)
    if row is None:
        raise NotFound("Order not found")
    if row["payment_status"] != "refund_due":
        raise Conflict("No refund is due on this order")
    services.db.update(table, {"payment_status": "refunded", "updated_at": iso()}, "id = ?", (entity_id,))
    services.audit.record("publishing.refund.recorded", table, entity_id, actor_id=principal.user_id)
    return {"id": entity_id, "payment_status": "refunded"}


def _request_refund(services: Services, purpose: str, reference_id: str, payment_status: str) -> None:
    billing = services.modules.get("billing")
    refund = getattr(billing, "refund", None) if billing else None
    if payment_status == "refund_due" and callable(refund):
        try:
            refund(purpose=purpose, reference_id=reference_id)
        except Exception:  # noqa: BLE001  billing optional; refund recorded as due either way
            pass


# ----------------------------------------------------------------- billing
def ensure_payment_handlers(services: Services) -> bool:
    billing = services.modules.get("billing")
    if billing is None or not hasattr(billing, "register_payment_handler"):
        return False
    registered = services.hooks.get("publishing.payments_registered_with")
    if registered is None or registered() is not billing:
        billing.register_payment_handler("sponsorship", on_payment)
        billing.register_payment_handler("advertising", on_payment)
        services.hooks["publishing.payments_registered_with"] = lambda: billing
    return True


def on_payment(services: Services, payment: dict[str, Any]) -> None:
    """Billing calls this once a verified webhook marks a payment paid.

    It updates payment state only. It does not approve, schedule or publish
    anything: editorial state is untouched by design (Annex B).
    """
    purpose = payment.get("purpose")
    table = {"sponsorship": "pub_sponsorships", "advertising": "pub_ad_campaigns"}.get(str(purpose))
    reference = str(payment.get("reference_id", ""))
    if table is None or not reference:
        return
    row = services.db.one(f"SELECT id, status FROM {table} WHERE id = ?", (reference,))  # noqa: S608 (fixed table names)
    if row is None:
        return
    status = "refund_due" if row["status"] == "rejected" else "paid"
    services.db.update(table, {"payment_status": status, "updated_at": iso()}, "id = ?", (reference,))
    services.audit.record("publishing.payment.received", table, reference, data={"payment_status": status})


def checkout(services: Services, principal: Principal, kind: str, entity_id: str) -> dict[str, Any]:
    table = "pub_sponsorships" if kind == "sponsorship" else "pub_ad_campaigns"
    row = services.db.one(f"SELECT * FROM {table} WHERE id = ?", (entity_id,))  # noqa: S608 (fixed table names)
    if row is None:
        raise NotFound("Order not found")
    if row["status"] in ("rejected", "cancelled", "ended"):
        raise Conflict(f"A {row['status']} order cannot be paid")
    if row["payment_status"] in ("paid", "refund_due", "refunded"):
        raise Conflict("This order is already settled")
    if not row["amount_kobo"]:
        raise Conflict("Set the agreed amount before taking payment")
    if not ensure_payment_handlers(services):
        return {"billing_available": False, "checkout": None, "message": "Billing is not available. Invoice the sponsor offline and record payment when billing is connected."}
    billing = services.modules["billing"]
    name = row.get("sponsor_name") or row.get("advertiser")
    result = billing.create_checkout(
        payer_user_id=principal.user_id,
        org_id=None,
        purpose="sponsorship" if kind == "sponsorship" else "advertising",
        reference_id=entity_id,
        amount_kobo=int(row["amount_kobo"]),
        description=f"tax.ng {kind} order for {name}",
    )
    services.db.update(table, {"payment_status": "pending", "checkout_id": result.get("checkout_id"), "updated_at": iso()}, "id = ?", (entity_id,))
    services.audit.record(f"publishing.{kind}.checkout", table, entity_id, actor_id=principal.user_id, data={"mode": result.get("mode")})
    return {"billing_available": True, "checkout": result, "mode": result.get("mode")}


# --------------------------------------------------------------------- ads
CAMPAIGN_FIELDS = {"advertiser", "starts_on", "ends_on", "slots", "arcon_reference", "amount_kobo"}
CREATIVE_FIELDS = {"headline", "body", "link_url", "image_file_id"}
SERVE_QUERY = {"page"}


def _reject_unknown(body: dict[str, Any], allowed: set[str]) -> None:
    for key in body:
        if key not in allowed:
            raise Invalid(f"{key}: not accepted. Ads on tax.ng are never targeted and take no audience data")


def slots(services: Services) -> dict[str, Any]:
    return policy(services).get("slots", {})


def is_sensitive(services: Services, page: str) -> bool:
    page = page or "/"
    for prefix in policy(services).get("sensitive_paths", []):
        if page == prefix or page.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _page_allowed(pages: list[str], page: str) -> bool:
    for p in pages:
        if p == "/" and page == "/":
            return True
        if p != "/" and (page == p or page.startswith(p + "/")):
            return True
    return False


def _date(value: Any, field: str) -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise Invalid(f"{field}: use a date (YYYY-MM-DD)") from None


def _campaign(services: Services, campaign_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_ad_campaigns WHERE id = ?", (campaign_id,))
    if row is None:
        raise NotFound("Campaign not found")
    return row


def campaign_view(services: Services, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["slots"] = row["slots"].split(",")
    out["amount"] = _money(row["amount_kobo"])
    out["creatives"] = services.db.query(
        "SELECT c.*, COALESCE(SUM(s.impressions), 0) AS impressions, COALESCE(SUM(s.clicks), 0) AS clicks "
        "FROM pub_ad_creatives c LEFT JOIN pub_ad_stats s ON s.creative_id = c.id WHERE c.campaign_id = ? GROUP BY c.id ORDER BY c.created_at",
        (row["id"],),
    )
    return out


def create_campaign(services: Services, principal: Principal, body: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(body, CAMPAIGN_FIELDS)
    require_open(services)
    known = slots(services)
    chosen = body.get("slots")
    if not isinstance(chosen, list) or not chosen:
        raise Invalid("slots: choose at least one placement")
    for slot in chosen:
        if str(slot).startswith("app") or slot not in known:
            raise Invalid(f"slots: {slot} is not a public placement")
    starts, ends = _date(body.get("starts_on"), "starts_on"), _date(body.get("ends_on"), "ends_on")
    if ends < starts:
        raise Invalid("ends_on: must be on or after starts_on")
    amount = body.get("amount_kobo", 0)
    if amount:
        amount = _kobo(amount)
    stamp = iso()
    row = {
        "id": new_id("cmp_ad"),
        "advertiser": _text(body, "advertiser", 200),
        "starts_on": starts,
        "ends_on": ends,
        "slots": ",".join(sorted(set(map(str, chosen)))),
        "arcon_reference": _text(body, "arcon_reference", 100, required=False) or None,
        "amount_kobo": amount or 0,
        "created_by": principal.user_id,
        "created_at": stamp,
        "updated_at": stamp,
    }
    services.db.insert("pub_ad_campaigns", row)
    services.audit.record("publishing.ad_campaign.create", "ad_campaign", row["id"], actor_id=principal.user_id, data={"slots": row["slots"]})
    return campaign_view(services, _campaign(services, row["id"]))


def add_creative(services: Services, principal: Principal, campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(body, CREATIVE_FIELDS)
    campaign = _campaign(services, campaign_id)
    if campaign["status"] in ("ended", "rejected"):
        raise Conflict("This campaign is closed")
    link = _text(body, "link_url", 500)
    if not link.startswith("https://"):
        raise Invalid("link_url: must start with https://")
    image = str(body.get("image_file_id", "") or "").strip() or None
    if image:
        record = services.files.get(image)
        if record is None or record["owner_user_id"] != principal.user_id or record["org_id"]:
            raise Invalid("image_file_id: upload the image first as a personal file")
        if not record["content_type"].startswith("image/"):
            raise Invalid("image_file_id: must be a PNG or JPEG image")
    row = {
        "id": new_id("crv"),
        "campaign_id": campaign_id,
        "headline": _text(body, "headline", 90),
        "body": _text(body, "body", 240, required=False),
        "link_url": link,
        "image_file_id": image,
        "created_at": iso(),
    }
    services.db.insert("pub_ad_creatives", row)
    services.audit.record("publishing.ad_creative.create", "ad_creative", row["id"], actor_id=principal.user_id)
    return row


def review_creative(services: Services, principal: Principal, creative_id: str, decision: str, note: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM pub_ad_creatives WHERE id = ?", (creative_id,))
    if row is None:
        raise NotFound("Creative not found")
    if decision not in ("approved", "rejected"):
        raise Invalid("decision: choose approved or rejected")
    if decision == "rejected" and not note.strip():
        raise Invalid("note: explain the rejection")
    services.db.update(
        "pub_ad_creatives",
        {"review_status": decision, "review_note": note.strip()[:500], "reviewed_by": principal.user_id, "reviewed_at": iso()},
        "id = ?",
        (creative_id,),
    )
    services.audit.record("publishing.ad_creative.review", "ad_creative", creative_id, actor_id=principal.user_id, data={"decision": decision})
    return services.db.one("SELECT * FROM pub_ad_creatives WHERE id = ?", (creative_id,)) or {}


def set_campaign_status(services: Services, principal: Principal, campaign_id: str, status: str, reason: str = "") -> dict[str, Any]:
    campaign = _campaign(services, campaign_id)
    flow = {"draft": ("active", "rejected"), "active": ("paused", "ended"), "paused": ("active", "ended")}
    if status not in flow.get(campaign["status"], ()):
        raise Conflict(f"Cannot move a {campaign['status']} campaign to {status or 'nothing'}")
    if status == "rejected" and principal.staff_role not in ("editor", "support", "admin", "sales"):
        raise Forbidden("Not allowed")
    values: dict[str, Any] = {"status": status, "updated_at": iso()}
    if status == "rejected":
        if not reason.strip():
            raise Invalid("reason: explain the rejection under the published terms")
        if campaign["payment_status"] == "paid":
            values["payment_status"] = "refund_due"
    services.db.update("pub_ad_campaigns", values, "id = ?", (campaign_id,))
    if status == "rejected":
        _request_refund(services, "advertising", campaign_id, values.get("payment_status", ""))
    services.audit.record("publishing.ad_campaign.status", "ad_campaign", campaign_id, actor_id=principal.user_id, data={"from": campaign["status"], "to": status})
    return campaign_view(services, _campaign(services, campaign_id))


def serve(services: Services, slot: str, query: dict[str, str]) -> dict[str, Any]:
    """Public ad selection. Inputs: slot and page path only. Never reads the caller."""
    _reject_unknown(query, SERVE_QUERY)
    page = str(query.get("page", "") or "/")
    known = slots(services)
    if slot.startswith("app") or slot not in known:
        raise NotFound("Unknown ad slot")
    if is_sensitive(services, page):
        return {"slot": slot, "ad": None, "reason": "sensitive_page"}
    if "page" in query and not _page_allowed(known[slot].get("pages", []), page):
        return {"slot": slot, "ad": None, "reason": "slot_not_on_page"}
    if not audience_status(services)["open"]:
        return {"slot": slot, "ad": None, "reason": "below_audience_threshold"}
    today = now().date().isoformat()
    candidates = services.db.query(
        "SELECT c.id, c.headline, c.body, c.link_url, c.image_file_id, k.advertiser, k.slots, "
        "COALESCE((SELECT impressions FROM pub_ad_stats s WHERE s.creative_id = c.id AND s.day = ?), 0) AS shown "
        "FROM pub_ad_creatives c JOIN pub_ad_campaigns k ON k.id = c.campaign_id "
        "WHERE c.review_status = 'approved' AND k.status = 'active' AND k.starts_on <= ? AND k.ends_on >= ? "
        "ORDER BY shown, c.id",
        (today, today, today),
    )
    for c in candidates:
        if slot in c["slots"].split(","):
            label = policy(services).get("labels", {}).get("advertisement", "Advertisement")
            ad = {"creative_id": c["id"], "headline": c["headline"], "body": c["body"], "link_url": c["link_url"], "advertiser": c["advertiser"], "label": label, "image_url": None}
            if c["image_file_id"] and services.files.get(c["image_file_id"]):
                ad["image_url"] = services.files.signed_link(c["image_file_id"])["url"]
            return {"slot": slot, "ad": ad}
    return {"slot": slot, "ad": None, "reason": "no_campaign"}


def count(services: Services, creative_id: str, column: str) -> dict[str, Any]:
    row = services.db.one(
        "SELECT c.link_url FROM pub_ad_creatives c JOIN pub_ad_campaigns k ON k.id = c.campaign_id WHERE c.id = ? AND c.review_status = 'approved'",
        (creative_id,),
    )
    if row is None:
        raise NotFound("Ad not found")
    day = now().date().isoformat()
    col = {"impressions": "impressions", "clicks": "clicks"}[column]
    services.db.execute(
        f"INSERT INTO pub_ad_stats (creative_id, day, {col}) VALUES (?, ?, 1) "  # noqa: S608 (fixed column names)
        f"ON CONFLICT(creative_id, day) DO UPDATE SET {col} = {col} + 1",
        (creative_id, day),
    )
    return {"url": row["link_url"]}


def campaign_report(services: Services, campaign_id: str) -> dict[str, Any]:
    campaign = campaign_view(services, _campaign(services, campaign_id))
    daily = services.db.query(
        "SELECT s.day, SUM(s.impressions) AS impressions, SUM(s.clicks) AS clicks FROM pub_ad_stats s "
        "JOIN pub_ad_creatives c ON c.id = s.creative_id WHERE c.campaign_id = ? GROUP BY s.day ORDER BY s.day",
        (campaign_id,),
    )
    return {
        "campaign": campaign,
        "daily": daily,
        "totals": {"impressions": sum(d["impressions"] for d in daily), "clicks": sum(d["clicks"] for d in daily)},
        "privacy": "Aggregate daily counts only. No personal data, cookies or IP addresses are stored.",
    }


def reports(services: Services) -> dict[str, Any]:
    campaigns = [campaign_view(services, r) for r in services.db.query("SELECT * FROM pub_ad_campaigns ORDER BY created_at DESC")]
    for c in campaigns:
        c["impressions"] = sum(x["impressions"] for x in c["creatives"])
        c["clicks"] = sum(x["clicks"] for x in c["creatives"])
    orders = [order_view(services, r) for r in services.db.query("SELECT * FROM pub_sponsorships ORDER BY created_at DESC")]
    return {"audience": audience_status(services), "campaigns": campaigns, "sponsorships": orders}
