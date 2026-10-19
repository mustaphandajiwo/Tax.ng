"""Who is asking, and what they may do. Every protected handler starts here.

Tenancy rule (ADR-08 stand-in): organisation data is reachable only through
``require_org``. It returns 404 rather than 403 for non-members, so callers
cannot probe which organisations exist. In PostgreSQL the same rule is backed
by row-level security; in the demo it is enforced here and covered by the
cross-tenant tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ORG_ROLES = ("owner", "preparer", "reviewer", "read_only")
CAN_EDIT = ("owner", "preparer")
CAN_REVIEW = ("owner", "reviewer")
CAN_ADMIN = ("owner",)
STAFF_ROLES = ("editor", "legal_reviewer", "sales", "support", "admin")


class Unauthorized(PermissionError):
    """No valid session (HTTP 401)."""


class Forbidden(PermissionError):
    """Signed in but not allowed (HTTP 403)."""


class NotFoundError(LookupError):
    """Missing, or hidden from this principal (HTTP 404)."""


@dataclass
class Principal:
    user_id: str
    email: str
    name: str
    staff_role: str
    ai_account_access: bool
    memberships: dict[str, str] = field(default_factory=dict)  # org_id -> role
    via: str = "session"  # "session" | "api_key"
    scopes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.user_id,
            "email": self.email,
            "name": self.name,
            "staff_role": self.staff_role,
            "ai_account_access": self.ai_account_access,
            "memberships": self.memberships,
        }


def principal_from_user(user: dict[str, Any], memberships: list[dict[str, Any]]) -> Principal:
    return Principal(
        user_id=user["id"],
        email=user["email"],
        name=user.get("name") or "",
        staff_role=user.get("staff_role") or "none",
        ai_account_access=bool(user.get("ai_account_access")),
        memberships={m["org_id"]: m["role"] for m in memberships},
    )


def require_user(principal: Principal | None) -> Principal:
    if principal is None:
        raise Unauthorized("Sign in to continue")
    return principal


def require_staff(principal: Principal | None, *roles: str) -> Principal:
    p = require_user(principal)
    if p.staff_role == "admin" or p.staff_role in roles:
        return p
    raise Forbidden("This needs a staff role")


def require_org(principal: Principal | None, org_id: str, roles: tuple[str, ...] = ORG_ROLES) -> str:
    """Return the caller's role in ``org_id`` if it is one of ``roles``."""
    p = require_user(principal)
    role = p.memberships.get(org_id)
    if role is None:
        raise NotFoundError("Organisation not found")
    if role not in roles:
        raise Forbidden(f"Your role ({role}) cannot do this")
    return role


def require_scope(principal: Principal | None, scope: str) -> Principal:
    """For API-key callers (Phase 4 public API). Session callers pass."""
    p = require_user(principal)
    if p.via == "api_key" and scope not in p.scopes:
        raise Forbidden(f"API key lacks scope {scope}")
    return p
