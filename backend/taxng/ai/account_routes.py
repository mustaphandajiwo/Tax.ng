"""Tax AI with access to the caller's own account data (AI-04, Phase 4).

Access requires, in order: a signed-in session (API keys are refused), the
user's explicit and revocable permission (``users.ai_account_access``), and
membership of any organisation whose data is requested. The route fetches
the summaries itself through the module contracts, so the assistant only
ever sees data already scoped to the caller. Every access is audited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..api.router import Request, route
from ..platform.access import Forbidden, require_org, require_user
from ..platform.errors import Invalid

if TYPE_CHECKING:
    from ..services import Services


@route("POST", "/api/ask/account")
def ask_with_account(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    principal = require_user(request.principal)
    if principal.via != "session":
        raise Forbidden("Account-aware answers are available in the signed-in app only")
    if not principal.ai_account_access:
        raise Forbidden("Turn on Tax AI access to your account in Account settings first")
    question = str(request.body.get("question", "")).strip()
    if len(question) < 3:
        raise Invalid("question: ask a question of at least a few words")

    account: dict[str, Any] = {}
    compliance = services.modules.get("compliance")
    if compliance is not None:
        account["personal"] = compliance.account_summary(principal.user_id)
    org_id = request.body.get("org_id")
    if org_id:
        require_org(principal, str(org_id))
        workspace = services.modules.get("workspace")
        if workspace is not None:
            account["organisation"] = workspace.org_summary(str(org_id))

    services.audit.record(
        "ai.account_access",
        "user",
        principal.user_id,
        actor_id=principal.user_id,
        org_id=str(org_id) if org_id else None,
        data={"scopes": sorted(account)},
    )
    result = services.assistant.answer(question, account=account)
    services.store.record_event("ai_question_asked", {"confidence": result["confidence"], "blocked": result["blocked"]})
    return 200, result
