"""Channels endpoints: WhatsApp webhook and demo, i18n catalogues, translation review."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import NotFound, Request, route
from ...legal.corpus import ContentError, _check_no_figures
from ...platform.access import Unauthorized, require_staff
from ...platform.errors import Invalid
from .whatsapp import RETENTION_NOTE, verify_webhook

if TYPE_CHECKING:
    from ...services import Services
    from . import Channels

SUBMITTERS = ("editor", "legal_reviewer", "support", "sales")
REVIEWERS = ("editor", "legal_reviewer")


def _ch(services: Services) -> Channels:
    return services.modules["channels"]


# ----------------------------------------------------------------- WhatsApp
@route("POST", "/api/channels/whatsapp/webhook")
def whatsapp_webhook(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Inbound messages from the WhatsApp provider. No session: the HMAC signature is the authentication."""
    if not verify_webhook(services, request):
        raise Unauthorized("Invalid webhook signature")
    body = request.body
    result = _ch(services).whatsapp.handle_inbound(
        str(body.get("from", "")), str(body.get("text", "")), str(body["message_id"]) if body.get("message_id") else None
    )
    # The provider needs only an acknowledgement; replies go out through the adapter.
    return 200, {"status": result["status"], "kind": result.get("kind"), "mode": result["mode"]}


@route("GET", "/api/channels/whatsapp/status")
def whatsapp_status(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, {"adapter": _ch(services).whatsapp.adapter.info(), "demo_available": services.demo_mode, "retention_note": RETENTION_NOTE}


@route("POST", "/api/channels/whatsapp/demo")
def whatsapp_demo(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Demo only: send a message as a phone number and see the bot's reply."""
    if not services.demo_mode:
        raise NotFound("Not available")
    text = str(request.body.get("text", "")).strip()
    if not text:
        raise Invalid("text: type a message")
    result = _ch(services).whatsapp.handle_inbound(str(request.body.get("phone", "")), text)
    if result["status"] == "rate_limited":
        return 429, {"error": "rate_limited", "message": "Too many messages from this number. Wait a minute and try again.", "mode": result["mode"]}
    return 200, result


@route("GET", "/api/channels/whatsapp/log")
def whatsapp_log(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal, "support")
    return 200, _ch(services).whatsapp.log()


@route("POST", "/api/channels/whatsapp/alerts")
def whatsapp_alert(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, "support")
    text = str(request.body.get("text", "")).strip()
    if not 3 <= len(text) <= 1000:
        raise Invalid("text: enter between 3 and 1000 characters")
    try:
        _check_no_figures("text", text)
    except ContentError:
        raise Invalid("text: alerts may not state figures; link to a calculator or guide instead") from None
    result = _ch(services).whatsapp.send_alert(str(request.body.get("phone", "")), text)
    services.audit.record("whatsapp.alert", "wa_alert", None, actor_id=staff.user_id, data={"status": result["status"]})
    return 200, result


# --------------------------------------------------------------- i18n public
@route("GET", "/api/i18n")
def languages(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    loc = _ch(services).i18n
    return 200, {"default": "en", "languages": loc.languages(), "in_review": loc.pending_languages()}


@route("GET", "/api/i18n/{lang}")
def catalogue(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, _ch(services).i18n.catalogue(params["lang"])


@route("GET", "/api/channels/guide-translations/{guide_id}")
def guide_translations(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, _ch(services).i18n.guide_translations(params["guide_id"])


# -------------------------------------------------------------- i18n staff
@route("GET", "/api/channels/translations")
def staff_strings(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal, *SUBMITTERS)
    return 200, _ch(services).i18n.staff_view(request.query.get("lang", ""))


@route("POST", "/api/channels/translations")
def submit_string(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *SUBMITTERS)
    b = request.body
    return 201, _ch(services).i18n.submit_string(staff.user_id, str(b.get("lang", "")), str(b.get("key", "")), str(b.get("text", "")))


@route("POST", "/api/channels/translations/{sub_id}/approve")
def approve_string(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *REVIEWERS)
    return 200, _ch(services).i18n.review_string(staff.user_id, params["sub_id"], "approved", str(request.body.get("note", "")))


@route("POST", "/api/channels/translations/{sub_id}/reject")
def reject_string(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *REVIEWERS)
    return 200, _ch(services).i18n.review_string(staff.user_id, params["sub_id"], "rejected", str(request.body.get("note", "")))


@route("GET", "/api/channels/guide-translations")
def staff_guides(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal, *SUBMITTERS)
    return 200, {"items": _ch(services).i18n.guide_submissions(request.query.get("status") or None)}


@route("POST", "/api/channels/guide-translations")
def submit_guide(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *SUBMITTERS)
    b = request.body
    return 201, _ch(services).i18n.submit_guide(staff.user_id, str(b.get("guide_id", "")), str(b.get("lang", "")), str(b.get("summary", "")))


@route("POST", "/api/channels/guide-translations/{sub_id}/approve")
def approve_guide(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *REVIEWERS)
    return 200, _ch(services).i18n.review_guide(staff.user_id, params["sub_id"], "approved", str(request.body.get("note", "")))


@route("POST", "/api/channels/guide-translations/{sub_id}/reject")
def reject_guide(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, *REVIEWERS)
    return 200, _ch(services).i18n.review_guide(staff.user_id, params["sub_id"], "rejected", str(request.body.get("note", "")))
