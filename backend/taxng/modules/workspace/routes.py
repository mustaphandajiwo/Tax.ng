"""HTTP endpoints for business workspaces, returns, review, export, filing and receipts.

Every organisation endpoint starts with ``require_org`` (non-members get 404).
There is no staff bypass: editorial, advertising and support staff have no
access to taxpayer records unless they are members of the organisation.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from ...api.router import Reply, Request, route
from ...platform.access import CAN_ADMIN, CAN_EDIT, CAN_REVIEW, ORG_ROLES, Forbidden, Principal, require_org, require_scope, require_user
from ...platform.errors import Invalid
from . import filing, returns, service

if TYPE_CHECKING:
    from ...services import Services

Result = tuple[int, Any]


def _org(request: Request, org_id: str, roles: tuple[str, ...] = ORG_ROLES, *, write: bool = False, human: bool = False) -> tuple[Principal, str]:
    p = require_user(request.principal)
    role = require_org(p, org_id, roles)
    if human and p.via != "session":
        raise Forbidden("This action needs a signed-in person, not an API key")
    require_scope(p, "workspace:write" if write else "workspace:read")
    return p, role


def _comment(request: Request, key: str = "comment") -> str:
    value = str(request.body.get(key) or "")
    if len(value) > 2000:
        raise Invalid(f"{key}: keep it under 2000 characters")
    return value


# ----------------------------------------------------------- organisations
@route("POST", "/api/orgs")
def create_org(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    if p.via != "session":
        raise Forbidden("Organisations are created by a signed-in person")
    return 201, service.create_org(services, p, request.body)


@route("GET", "/api/orgs")
def list_orgs(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    return 200, {"items": service.list_orgs(services, p)}


@route("GET", "/api/orgs/{org_id}")
def get_org(services: Services, request: Request, params: dict[str, str]) -> Result:
    _, role = _org(request, params["org_id"])
    return 200, service.org_view(services, service.org_row(services, params["org_id"]), role)


@route("PUT", "/api/orgs/{org_id}")
def update_org(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    service.update_org(services, p, params["org_id"], request.body)
    return 200, service.org_view(services, service.org_row(services, params["org_id"]), role)


@route("PUT", "/api/orgs/{org_id}/facts")
def update_facts(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_EDIT, write=True)
    service.update_facts(services, p, params["org_id"], request.body)
    return 200, service.org_view(services, service.org_row(services, params["org_id"]), role)


@route("POST", "/api/orgs/{org_id}/verify")
def verify_org(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    return 200, service.verify_org_identifier(services, p, params["org_id"], str(request.body.get("id_type", "")))


@route("GET", "/api/orgs/{org_id}/summary")
def summary(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    return 200, services.modules["workspace"].org_summary(params["org_id"])


# ------------------------------------------------------------------ members
@route("GET", "/api/orgs/{org_id}/members")
def members(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    return 200, {"items": service.list_members(services, params["org_id"])}


@route("PUT", "/api/orgs/{org_id}/members/{user_id}")
def change_role(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    service.change_role(services, p, params["org_id"], params["user_id"], str(request.body.get("role", "")))
    return 200, {"items": service.list_members(services, params["org_id"])}


@route("DELETE", "/api/orgs/{org_id}/members/{user_id}")
def remove_member(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    # Any member may leave; only an owner may remove someone else.
    roles = ORG_ROLES if params["user_id"] == p.user_id else CAN_ADMIN
    p, _ = _org(request, params["org_id"], roles, write=True, human=True)
    service.remove_member(services, p, params["org_id"], params["user_id"])
    return 200, {"status": "removed"}


@route("GET", "/api/orgs/{org_id}/invitations")
def invitations(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"], CAN_ADMIN)
    return 200, {"items": service.list_invitations(services, params["org_id"])}


@route("POST", "/api/orgs/{org_id}/invitations")
def invite(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    return 201, service.invite(services, p, params["org_id"], request.body)


@route("DELETE", "/api/orgs/{org_id}/invitations/{invitation_id}")
def revoke_invitation(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    service.revoke_invitation(services, p, params["org_id"], params["invitation_id"])
    return 200, {"status": "revoked"}


@route("POST", "/api/invitations/accept")
def accept_invitation(services: Services, request: Request, params: dict[str, str]) -> Result:
    p = require_user(request.principal)
    if p.via != "session":
        raise Forbidden("Invitations are accepted by a signed-in person")
    return 200, service.accept_invitation(services, p, str(request.body.get("token", "")))


# ----------------------------------------------------------------- calendar
@route("GET", "/api/orgs/{org_id}/calendar")
def calendar(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    try:
        year = int(request.query.get("year") or dt.date.today().year)
    except ValueError:
        raise Invalid("year: must be a year") from None
    if not 2020 <= year <= 2035:
        raise Invalid("year: must be between 2020 and 2035")
    return 200, service.calendar(services, params["org_id"], year)


# ------------------------------------------------------------------ returns
@route("GET", "/api/workspace/return-types")
def return_types(services: Services, request: Request, params: dict[str, str]) -> Result:
    require_user(request.principal)
    return 200, {"items": returns.return_types(), "channels": list(filing.CHANNELS)}


@route("GET", "/api/orgs/{org_id}/returns")
def list_returns(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    sql = "SELECT * FROM ws_returns WHERE org_id = ?"
    args: list[Any] = [params["org_id"]]
    status = request.query.get("status")
    if status:
        sql += " AND status = ?"
        args.append(status)
    rows = services.db.query(sql + " ORDER BY period DESC, created_at DESC", args)
    return 200, {"items": [returns.summary_row(r) for r in rows]}


@route("POST", "/api/orgs/{org_id}/returns")
def create_return(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    return 201, returns.summary_row(returns.create_return(services, p, params["org_id"], request.body))


@route("GET", "/api/orgs/{org_id}/returns/{return_id}")
def get_return(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"])
    return 200, returns.detail(services, p, role, params["org_id"], params["return_id"])


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/lines")
def add_line(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    return 201, returns.add_line(services, p, params["org_id"], params["return_id"], request.body)


@route("PUT", "/api/orgs/{org_id}/returns/{return_id}/lines/{line_id}")
def update_line(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    return 200, returns.update_line(services, p, params["org_id"], params["return_id"], params["line_id"], request.body)


@route("DELETE", "/api/orgs/{org_id}/returns/{return_id}/lines/{line_id}")
def delete_line(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    returns.delete_line(services, p, params["org_id"], params["return_id"], params["line_id"])
    return 200, {"status": "deleted"}


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/submit")
def submit(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_EDIT, write=True)
    returns.submit(services, p, params["org_id"], params["return_id"], _comment(request))
    return 200, returns.detail(services, p, role, params["org_id"], params["return_id"])


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/approve")
def approve(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_REVIEW, write=True, human=True)
    returns.approve(services, p, role, params["org_id"], params["return_id"], _comment(request))
    return 200, returns.detail(services, p, role, params["org_id"], params["return_id"])


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/request-changes")
def request_changes(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_REVIEW, write=True, human=True)
    returns.request_changes(services, p, role, params["org_id"], params["return_id"], _comment(request))
    return 200, returns.detail(services, p, role, params["org_id"], params["return_id"])


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/reopen")
def reopen(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, role = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    returns.reopen(services, p, params["org_id"], params["return_id"], _comment(request, "reason"))
    return 200, returns.detail(services, p, role, params["org_id"], params["return_id"])


@route("GET", "/api/orgs/{org_id}/returns/{return_id}/export")
def export(services: Services, request: Request, params: dict[str, str]) -> Reply:
    p, _ = _org(request, params["org_id"])
    content_type, filename, text = returns.export(services, p, params["org_id"], params["return_id"], request.query.get("format", "json"))
    return Reply(
        200,
        raw=text.encode(),
        content_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


# ---------------------------------------------------------------- documents
@route("POST", "/api/orgs/{org_id}/returns/{return_id}/documents")
def link_document(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    filing.link_document(services, p, params["org_id"], params["return_id"], str(request.body.get("file_id", "")))
    return 201, {"status": "linked"}


@route("DELETE", "/api/orgs/{org_id}/returns/{return_id}/documents/{file_id}")
def unlink_document(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    filing.unlink_document(services, p, params["org_id"], params["return_id"], params["file_id"])
    return 200, {"status": "unlinked"}


@route("GET", "/api/orgs/{org_id}/document-links")
def document_links(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    return 200, {"links": filing.document_links(services, params["org_id"])}


# ------------------------------------------------------------------- filing
@route("GET", "/api/filing/status")
def filing_status(services: Services, request: Request, params: dict[str, str]) -> Result:
    """Public: whether direct filing is available. Used by the /file-pay page."""
    info = filing.adapter_info(services)
    return 200, {k: info[k] for k in ("mode", "authorised", "available", "description", "needs")}


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/file")
def file_return(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    key = str(request.body.get("idempotency_key") or request.headers.get("idempotency-key") or "")
    replayed, submission = filing.file_return(services, p, params["org_id"], params["return_id"], key)
    return (200 if replayed else 201), {**submission, "replayed": replayed}


@route("GET", "/api/orgs/{org_id}/submissions")
def submissions(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    return 200, {"items": filing.submissions_for(services, params["org_id"]), "filing": filing.adapter_info(services)}


@route("POST", "/api/orgs/{org_id}/submissions/{submission_id}/reconcile")
def reconcile(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_REVIEW, write=True, human=True)
    return 200, filing.reconcile_submission(services, p, params["org_id"], params["submission_id"], _comment(request, "note"))


# ----------------------------------------------------------------- payments
@route("GET", "/api/orgs/{org_id}/payments")
def org_payments(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"])
    return 200, {"items": filing.org_payments(services, params["org_id"])}


@route("POST", "/api/orgs/{org_id}/returns/{return_id}/payments")
def record_payment(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_EDIT, write=True)
    return 201, filing.record_payment(services, p, params["org_id"], params["return_id"], request.body)


@route("DELETE", "/api/orgs/{org_id}/payments/{payment_id}")
def void_payment(services: Services, request: Request, params: dict[str, str]) -> Result:
    p, _ = _org(request, params["org_id"], CAN_ADMIN, write=True, human=True)
    filing.void_payment(services, p, params["org_id"], params["payment_id"])
    return 200, {"status": "voided"}


# -------------------------------------------------------------------- audit
@route("GET", "/api/orgs/{org_id}/audit")
def audit(services: Services, request: Request, params: dict[str, str]) -> Result:
    _org(request, params["org_id"], CAN_REVIEW)
    try:
        limit = max(1, min(int(request.query.get("limit") or 200), 1000))
    except ValueError:
        raise Invalid("limit: must be a number") from None
    events = services.audit.events(org_id=params["org_id"], entity_id=request.query.get("entity_id") or None, limit=limit)
    actor_ids = sorted({e["actor_id"] for e in events if e["actor_id"]})
    names: dict[str, str] = {}
    if actor_ids:
        marks = ", ".join("?" for _ in actor_ids)
        names = {u["id"]: u["email"] for u in services.db.query(f"SELECT id, email FROM users WHERE id IN ({marks})", actor_ids)}
    items = [
        {
            "seq": e["seq"],
            "at": e["at"],
            "action": e["action"],
            "entity": e["entity"],
            "entity_id": e["entity_id"],
            "actor": names.get(e["actor_id"] or "", None),
            "data": json.loads(e["data_json"]),
            "hash": e["hash"],
        }
        for e in events
    ]
    return 200, {"items": items}
