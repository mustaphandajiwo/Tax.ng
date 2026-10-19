"""Publishing endpoints: public insights, news, RSS, search, ads and archive; contributor portal; staff desks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import Reply, Request, route
from ...platform.access import require_staff, require_user
from ...platform.errors import Invalid
from . import commerce, newsletter, service

if TYPE_CHECKING:
    from ...services import Services

Result = tuple[int, Any]


# ===================================================================== public
@route("GET", "/api/publishing/policy")
def get_policy(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = service.policy(services)
    return 200, {
        "terms_version": p.get("terms_version"),
        "labels": p.get("labels", {}),
        "rate_card": p.get("rate_card", []),
        "placement_policy": p.get("placement_policy", []),
        "disclosure_rules": p.get("disclosure_rules", []),
        "rejection_and_refund": p.get("rejection_and_refund", []),
        "slots": [{"id": k, "label": v.get("label", k)} for k, v in commerce.slots(services).items()],
        "audience": commerce.audience_status(services),
    }


@route("GET", "/api/publishing/articles")
def public_articles(services: Services, request: Request, params: dict[str, str]) -> Result:
    kind = request.query.get("type") or None
    if kind and kind not in service.TYPE_LABEL:
        raise Invalid("type: unknown article type")
    section = request.query.get("section") or None
    if section and section not in service.SECTIONS:
        raise Invalid("section: choose nigeria, africa or global")
    items = [service.card(services, a) for a in service.published(services, article_type=kind, section=section)]
    return 200, {"items": items}


@route("GET", "/api/publishing/articles/{slug}")
def public_article(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, service.public_page(services, params["slug"])


@route("GET", "/api/publishing/search")
def search(services: Services, request: Request, params: dict[str, str]) -> Result:
    q = request.query.get("q", "").strip()
    if not q:
        raise Invalid("q: is required")
    return 200, {"items": service.search(services, q[:200])}


@route("GET", "/api/publishing/news")
def news(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, {"section": request.query.get("section", ""), "items": service.news(services, request.query.get("section", "nigeria"))}


@route("GET", "/api/publishing/rss.xml")
def rss(services: Services, request: Request, params: dict[str, str]) -> Reply:
    data = service.rss(services, request.query.get("section") or None)
    return Reply(200, raw=data, content_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})


@route("GET", "/api/publishing/newsletter/archive")
def edition_archive(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, {"items": newsletter.archive(services)}


@route("GET", "/api/publishing/newsletter/archive/{edition_id}")
def edition_archived(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, newsletter.archived_edition(services, params["edition_id"])


@route("POST", "/api/publishing/complaints")
def complain(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 201, service.file_complaint(services, request.principal, request.body)


@route("GET", "/api/publishing/complaints/{complaint_id}/status")
def complaint_status(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, service.complaint_status(services, params["complaint_id"], request.query.get("token", ""))


# ------------------------------------------------------------------- ads
@route("GET", "/api/ads/slot/{slot}")
def ad_slot(services: Services, request: Request, params: dict[str, str]) -> Reply:
    # Deliberately ignores request.principal and cookies: no targeting (Annex B).
    body = commerce.serve(services, params["slot"], dict(request.query))
    return Reply(200, body, headers={"Cache-Control": "no-store"})


@route("POST", "/api/ads/impression/{creative_id}")
def ad_impression(services: Services, request: Request, params: dict[str, str]) -> Result:
    commerce.count(services, params["creative_id"], "impressions")
    return 202, {"status": "counted"}


@route("POST", "/api/ads/click/{creative_id}")
def ad_click(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.count(services, params["creative_id"], "clicks")


# ========================================================= contributor portal
@route("GET", "/api/publishing/submissions")
def my_submissions(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, {"items": service.mine(services, require_user(request.principal))}


@route("POST", "/api/publishing/submissions")
def create_submission(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    return 201, service.detail(services, p, service.create_article(services, p, request.body)["id"])


@route("GET", "/api/publishing/submissions/{article_id}")
def get_submission(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, service.detail(services, require_user(request.principal), params["article_id"])


@route("POST", "/api/publishing/submissions/{article_id}")
def edit_submission(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    service.update_article(services, p, params["article_id"], request.body)
    return 200, service.detail(services, p, params["article_id"])


@route("POST", "/api/publishing/submissions/{article_id}/transition/{action}")
def transition_submission(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    service.transition(services, p, params["article_id"], params["action"], request.body)
    return 200, service.detail(services, p, params["article_id"])


@route("POST", "/api/publishing/submissions/{article_id}/classify")
def classify_submission(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    service.classify(services, p, params["article_id"], request.body)
    return 200, service.detail(services, p, params["article_id"])


@route("POST", "/api/publishing/submissions/{article_id}/disclosure")
def disclosure(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "sales")
    service.visible_article(services, p, params["article_id"])
    commerce.record_disclosure(services, p, params["article_id"], request.body)
    return 200, service.detail(services, p, params["article_id"])


# =============================================================== staff desks
@route("GET", "/api/publishing/dashboard")
def dashboard(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "legal_reviewer", "sales", "support")
    counts = {r["state"]: r["n"] for r in services.db.query("SELECT state, COUNT(*) AS n FROM pub_articles GROUP BY state")}
    return 200, {
        "role": p.staff_role,
        "articles_by_state": counts,
        "awaiting_legal_signoff": services.db.scalar("SELECT COUNT(*) FROM pub_articles WHERE state = 'fact_legal_review' AND legal_signoff_by IS NULL"),
        "creatives_pending_review": services.db.scalar("SELECT COUNT(*) FROM pub_ad_creatives WHERE review_status = 'pending'"),
        "open_complaints": services.db.scalar("SELECT COUNT(*) FROM pub_complaints WHERE status IN ('received', 'investigating')"),
        "editions_in_progress": services.db.scalar("SELECT COUNT(*) FROM pub_editions WHERE state NOT IN ('sent', 'archived')"),
        "audience": commerce.audience_status(services),
    }


@route("GET", "/api/publishing/queue")
def editorial_queue(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "legal_reviewer")
    return 200, {"items": service.queue(services, p, request.query.get("state") or None)}


@route("POST", "/api/publishing/run-scheduled")
def run_scheduled(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "editor")
    return 200, {"articles": service.run_due(services), "editions": newsletter.run_due(services)}


@route("GET", "/api/publishing/complaints")
def complaints(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "editor", "legal_reviewer", "support")
    rows = services.db.query(
        "SELECT c.id, c.kind, c.details, c.status, c.resolution, c.created_at, c.updated_at, c.contact_email, a.title AS article_title, a.id AS article_id "
        "FROM pub_complaints c LEFT JOIN pub_articles a ON a.id = c.article_id ORDER BY c.created_at DESC LIMIT 200"
    )
    return 200, {"items": rows}


@route("POST", "/api/publishing/complaints/{complaint_id}")
def handle_complaint(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "legal_reviewer", "support")
    return 200, service.update_complaint(services, p, params["complaint_id"], request.body)


# ---------------------------------------------------------------- editions
@route("GET", "/api/publishing/editions")
def editions(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "editor", "legal_reviewer")
    return 200, {"items": newsletter.listing(services)}


@route("POST", "/api/publishing/editions")
def create_edition(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 201, newsletter.create(services, require_staff(request.principal, "editor"), request.body)


@route("POST", "/api/publishing/editions/{edition_id}")
def update_edition(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, newsletter.update(services, require_staff(request.principal, "editor"), params["edition_id"], request.body)


@route("GET", "/api/publishing/editions/{edition_id}/preview")
def preview_edition(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "editor", "legal_reviewer")
    edition = newsletter._edition(services, params["edition_id"])
    return 200, {**newsletter.render(services, edition, "preview@tax.ng"), "edition": newsletter.view(services, edition)}


@route("POST", "/api/publishing/editions/{edition_id}/transition/{action}")
def transition_edition(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "legal_reviewer")
    return 200, newsletter.transition(services, p, params["edition_id"], params["action"], request.body)


# ------------------------------------------------------------ sponsorships
@route("GET", "/api/publishing/sponsorships")
def sponsorships(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "sales", "editor")
    rows = services.db.query("SELECT * FROM pub_sponsorships ORDER BY created_at DESC LIMIT 200")
    return 200, {"items": [commerce.order_view(services, r) for r in rows], "audience": commerce.audience_status(services)}


@route("POST", "/api/publishing/sponsorships")
def create_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 201, commerce.create_order(services, require_staff(request.principal, "sales"), request.body)


@route("POST", "/api/publishing/sponsorships/{order_id}")
def update_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.update_order(services, require_staff(request.principal, "sales"), params["order_id"], request.body)


@route("POST", "/api/publishing/sponsorships/{order_id}/attach")
def attach_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "sales")
    return 200, commerce.attach_order(services, p, params["order_id"], str(request.body.get("article_id", "")))


@route("POST", "/api/publishing/sponsorships/{order_id}/checkout")
def checkout_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.checkout(services, require_staff(request.principal, "sales"), "sponsorship", params["order_id"])


@route("POST", "/api/publishing/sponsorships/{order_id}/reject")
def reject_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "sales", "editor")
    return 200, commerce.reject_order(services, p, params["order_id"], str(request.body.get("reason", "")))


@route("POST", "/api/publishing/sponsorships/{order_id}/refunded")
def refunded_sponsorship(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.record_refund(services, require_staff(request.principal, "sales"), "pub_sponsorships", params["order_id"])


@route("GET", "/api/publishing/reports")
def sales_reports(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "sales")
    return 200, commerce.reports(services)


# ----------------------------------------------------------- ad campaigns
@route("GET", "/api/ads/campaigns")
def campaigns(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "sales", "editor", "support")
    rows = services.db.query("SELECT * FROM pub_ad_campaigns ORDER BY created_at DESC LIMIT 200")
    return 200, {"items": [commerce.campaign_view(services, r) for r in rows], "audience": commerce.audience_status(services)}


@route("POST", "/api/ads/campaigns")
def create_campaign(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 201, commerce.create_campaign(services, require_staff(request.principal, "sales"), request.body)


@route("POST", "/api/ads/campaigns/{campaign_id}/creatives")
def add_creative(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 201, commerce.add_creative(services, require_staff(request.principal, "sales"), params["campaign_id"], request.body)


@route("POST", "/api/ads/campaigns/{campaign_id}/status")
def campaign_status(services: Services, request: Request, params: dict[str, str]) -> Result:
    status = str(request.body.get("status", ""))
    roles = ("sales", "editor", "support") if status == "rejected" else ("sales",)
    p = require_staff(request.principal, *roles)
    return 200, commerce.set_campaign_status(services, p, params["campaign_id"], status, str(request.body.get("reason", "")))


@route("POST", "/api/ads/campaigns/{campaign_id}/checkout")
def campaign_checkout(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.checkout(services, require_staff(request.principal, "sales"), "advertising", params["campaign_id"])


@route("POST", "/api/ads/campaigns/{campaign_id}/refunded")
def campaign_refunded(services: Services, request: Request, params: dict[str, str]) -> Result:
    return 200, commerce.record_refund(services, require_staff(request.principal, "sales"), "pub_ad_campaigns", params["campaign_id"])


@route("GET", "/api/ads/campaigns/{campaign_id}/report")
def campaign_report(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_staff(request.principal, "sales")
    return 200, commerce.campaign_report(services, params["campaign_id"])


@route("POST", "/api/ads/creatives/{creative_id}/review")
def review_creative(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_staff(request.principal, "editor", "support")
    return 200, commerce.review_creative(services, p, params["creative_id"], str(request.body.get("decision", "")), str(request.body.get("note", "")))
