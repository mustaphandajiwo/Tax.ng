"""Platform endpoints: sign-in, account, identity checks, files, admin and demo tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..api.router import Cookie, NotFound, Reply, Request, route, routes
from ..platform.errors import Invalid
from .access import CAN_EDIT, require_org, require_staff, require_user
from .auth import SESSION_COOKIE, SESSION_TTL

if TYPE_CHECKING:
    from ..services import Services


def _me(services: Services, request: Request) -> dict[str, Any]:
    p = require_user(request.principal)
    orgs = services.db.query(
        "SELECT o.id, o.name, o.entity_type, m.role FROM memberships m JOIN organisations o ON o.id = m.org_id "
        "WHERE m.user_id = ? ORDER BY o.name",
        (p.user_id,),
    )
    return {**p.to_dict(), "organisations": orgs}


# ------------------------------------------------------------------ sign-in
@route("POST", "/api/auth/request-code")
def request_code(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    services.auth.request_code(str(request.body.get("email", "")))
    # Same response whether or not the address has an account.
    return 202, {"status": "code_sent", "demo_outbox": services.demo_mode}


@route("POST", "/api/auth/verify")
def verify(services: Services, request: Request, params: dict[str, str]) -> Reply:
    token, user = services.auth.verify_code(str(request.body.get("email", "")), str(request.body.get("code", "")))
    services.audit.record("auth.sign_in", "user", user["id"], actor_id=user["id"])
    cookie = Cookie(SESSION_COOKIE, token, max_age=int(SESSION_TTL.total_seconds()))
    return Reply(200, {"status": "signed_in", "user_id": user["id"]}, cookies=[cookie])


@route("POST", "/api/auth/logout")
def logout(services: Services, request: Request, params: dict[str, str]) -> Reply:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        services.auth.revoke(token)
    return Reply(200, {"status": "signed_out"}, cookies=[Cookie(SESSION_COOKIE, "", max_age=0)])


@route("GET", "/api/session")
def session(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Signed-in check that never errors, so the app can decide what to show."""
    if request.principal is None or request.principal.via != "session":
        return 200, {"signed_in": False}
    return 200, {"signed_in": True, "me": _me(services, request)}


@route("GET", "/api/me")
def me(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, _me(services, request)


@route("POST", "/api/me")
def update_me(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    body = request.body
    values: dict[str, Any] = {}
    if "name" in body:
        name = str(body["name"]).strip()
        if len(name) > 120:
            raise Invalid("name: keep it under 120 characters")
        values["name"] = name
    if "phone" in body:
        phone = str(body["phone"]).strip()
        if phone and not phone.lstrip("+").isdigit():
            raise Invalid("phone: digits only, optionally starting with +")
        values["phone"] = phone or None
    if "ai_account_access" in body:
        # AI-04: explicit, revocable permission for Tax AI to read account data.
        values["ai_account_access"] = 1 if body["ai_account_access"] is True else 0
        services.audit.record(
            "consent.ai_account_access", "user", p.user_id, actor_id=p.user_id, data={"granted": bool(values["ai_account_access"])}
        )
    if values:
        services.db.update("users", values, "id = ?", (p.user_id,))
        request.principal = None
        # Re-resolve so the response reflects the change.
        from ..api.router import _resolve_principal

        _resolve_principal(services, request)
    return 200, _me(services, request)


# ----------------------------------------------------------- identity checks
@route("POST", "/api/me/identity")
def verify_identity(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    result = services.identity.verify("user", p.user_id, str(request.body.get("id_type", "")), str(request.body.get("number", "")))
    services.audit.record("identity.check", "user", p.user_id, actor_id=p.user_id, data={k: result[k] for k in ("id_type", "result", "mode")})
    return 200, result


@route("GET", "/api/me/identity")
def list_identity(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": services.identity.latest("user", p.user_id)}


# ---------------------------------------------------------------------- files
def _file_access(services: Services, request: Request, record: dict[str, Any], *, write: bool) -> None:
    p = require_user(request.principal)
    if record["org_id"]:
        require_org(p, record["org_id"], CAN_EDIT if write else ("owner", "preparer", "reviewer", "read_only"))
    elif record["owner_user_id"] != p.user_id:
        raise NotFound("File not found")


@route("POST", "/api/files")
def upload(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    org_id = request.body.get("org_id") or None
    if org_id:
        require_org(p, str(org_id), CAN_EDIT)
    record = services.files.save(
        owner_user_id=p.user_id,
        org_id=org_id,
        name=str(request.body.get("name", "file")),
        content_type=str(request.body.get("content_type", "")),
        data_base64=str(request.body.get("data_base64", "")),
        category=str(request.body.get("category", "general")),
    )
    services.audit.record("file.upload", "file", record["id"], actor_id=p.user_id, org_id=org_id, data={"sha256": record["sha256"], "size": record["size"]})
    return 201, record


@route("GET", "/api/files")
def list_files(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    org_id = request.query.get("org_id")
    if org_id:
        require_org(p, org_id)
        rows = services.db.query("SELECT * FROM files WHERE org_id = ? AND deleted_at IS NULL ORDER BY created_at DESC", (org_id,))
    else:
        rows = services.db.query(
            "SELECT * FROM files WHERE org_id IS NULL AND owner_user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC", (p.user_id,)
        )
    return 200, {"items": rows}


@route("POST", "/api/files/{file_id}/link")
def file_link(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    record = services.files.get(params["file_id"])
    if record is None:
        raise NotFound("File not found")
    _file_access(services, request, record, write=False)
    return 200, services.files.signed_link(record["id"])


@route("GET", "/api/files/{file_id}/download")
def download(services: Services, request: Request, params: dict[str, str]) -> Reply:
    record, data = services.files.read_signed(params["file_id"], request.query.get("exp", ""), request.query.get("sig", ""))
    return Reply(
        200,
        raw=data,
        content_type=record["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{record["name"]}"', "Cache-Control": "private, no-store"},
    )


@route("DELETE", "/api/files/{file_id}")
def delete_file(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    record = services.files.get(params["file_id"])
    if record is None:
        raise NotFound("File not found")
    _file_access(services, request, record, write=True)
    services.files.soft_delete(record["id"])
    services.audit.record("file.delete", "file", record["id"], actor_id=request.principal.user_id if request.principal else None, org_id=record["org_id"])
    return 200, {"status": "deleted"}


# ---------------------------------------------------------------------- admin
@route("GET", "/api/admin/adapters")
def adapters(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal, "support")
    return 200, {"items": services.adapters.info()}


@route("GET", "/api/admin/audit/verify")
def audit_verify(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal)
    return 200, services.audit.verify()


@route("GET", "/api/admin/metrics")
def metrics(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Operational snapshot for enterprise monitoring (Phase 4)."""
    require_staff(request.principal, "support")
    count = lambda table: services.db.scalar(f"SELECT COUNT(*) FROM {table}")  # noqa: E731 (fixed table names)
    return 200, {
        "users": count("users"),
        "organisations": count("organisations"),
        "audit_events": count("audit_events"),
        "files": count("files"),
        "subscribers": services.store.subscriber_count(),
        "events": services.store.event_counts(),
        "adapters": services.adapters.info(),
        "routes": len(routes()),
        "audit_chain": services.audit.verify(),
    }


@route("POST", "/api/admin/users/{user_id}/staff-role")
def set_staff_role(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    admin = require_staff(request.principal)
    role = str(request.body.get("staff_role", ""))
    if role not in ("none", "editor", "legal_reviewer", "sales", "support", "admin"):
        raise Invalid("staff_role: unknown role")
    if services.db.update("users", {"staff_role": role}, "id = ?", (params["user_id"],)) == 0:
        raise NotFound("User not found")
    services.audit.record("staff.role_set", "user", params["user_id"], actor_id=admin.user_id, data={"staff_role": role})
    return 200, {"status": "updated"}


# ---------------------------------------------------------------- demo tools
@route("GET", "/api/dev/outbox")
def outbox(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Demo only: shows sent messages so sign-in codes work without email."""
    if not services.demo_mode:
        raise NotFound("Not available")
    email = request.query.get("recipient", "").strip().lower() or None
    return 200, {"items": services.notifier.recent(email, limit=10)}
