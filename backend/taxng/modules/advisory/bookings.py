"""Bookings, consents and engagements (ADV-02, ADV-03, ADV-05, GOV-04).

Booking state machine (``advisory_bookings.status``)::

    requested --adviser accepts--> accepted  (an engagement is created)
    requested --adviser declines-> declined
    requested --client cancels---> cancelled

Engagement (``advisory_engagements.status``): ``active`` until the client or the
adviser ends it (``ended``). Ending revokes any engagement consent.

Consents are separate records (``advisory_consents.kind``):

* ``pre_engagement`` is recorded *before* the booking exists, with the intake
  fields the client selected from their compliance ``account_summary``. Only
  those fields are copied to the booking (ADV-02).
* ``engagement`` grants the adviser scoped, revocable read access to the
  client's latest health-check report during an active engagement (ADV-03).
* ``marketing`` and ``findings_matching`` are user-level and never created as a
  side effect of a booking. Findings feed adviser suggestions only with
  ``findings_matching`` consent, and are never used for advertising (ADV-05).

Every read of client data by an adviser (intake or report) is written to the
audit trail as ``advisory.client_data_accessed``; clients can see that log.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from ...platform.access import Forbidden
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id
from .advisers import Advisers
from .policy import CONSENT_TEXT, ENGAGEMENT_SCOPES, PRACTITIONER_NOTICE, SPECIALISMS, USER_CONSENT_KINDS

if TYPE_CHECKING:
    from ...services import Services

ACCESS_ACTION = "advisory.client_data_accessed"
HEALTH_CHECK_FIELD = "health_check.dimensions"


class Bookings:
    def __init__(self, services: Services, advisers: Advisers) -> None:
        self.services = services
        self.db = services.db
        self.advisers = advisers

    # ------------------------------------------------------------------ helpers
    def _summary(self, user_id: str) -> dict[str, Any] | None:
        compliance = self.services.modules.get("compliance")
        return compliance.account_summary(user_id) if compliance else None

    def _email(self, user_id: str) -> str | None:
        return self.services.db.scalar("SELECT email FROM users WHERE id = ?", (user_id,))

    def _notify(self, user_id: str, subject: str, body: str) -> None:
        email = self._email(user_id)
        if email:
            self.services.notifier.send("email", email, body, subject=subject)

    def _consent(self, user_id: str, kind: str, **refs: Any) -> str:
        consent_id = new_id("cns")
        self.db.insert(
            "advisory_consents",
            {
                "id": consent_id,
                "user_id": user_id,
                "kind": kind,
                "consent_text": CONSENT_TEXT[kind],
                "granted_at": iso(),
                "scope_json": json.dumps(refs.pop("scope", [])),
                **refs,
            },
        )
        self.services.audit.record("consent.granted", "consent", consent_id, actor_id=user_id, data={"kind": kind})
        return consent_id

    def _revoke(self, user_id: str, consent_id: str) -> None:
        self.db.update("advisory_consents", {"revoked_at": iso()}, "id = ? AND revoked_at IS NULL", (consent_id,))
        self.services.audit.record("consent.revoked", "consent", consent_id, actor_id=user_id)

    def _booking_view(self, row: dict[str, Any], *, with_intake: bool) -> dict[str, Any]:
        adviser = self.advisers.row(row["adviser_id"])
        view = {
            **{k: row[k] for k in ("id", "status", "topic", "message", "preferred_date", "created_at", "decided_at", "decision_note")},
            "adviser": {"id": adviser["id"], "name": adviser["name"], "firm": adviser["firm"]},
            "intake_fields": sorted(json.loads(row["intake_json"]).get("fields", [])),
            "engagement": self._engagement_for_booking(row["id"]),
            "practitioner_notice": PRACTITIONER_NOTICE,
        }
        if with_intake:
            view["intake"] = json.loads(row["intake_json"])
        return view

    def _engagement_for_booking(self, booking_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM advisory_engagements WHERE booking_id = ?", (booking_id,))
        return self._engagement_view(row) if row else None

    def _active_consent(self, engagement_id: str) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM advisory_consents WHERE engagement_id = ? AND kind = 'engagement' AND revoked_at IS NULL "
            "ORDER BY granted_at DESC LIMIT 1",
            (engagement_id,),
        )

    def _engagement_view(self, row: dict[str, Any]) -> dict[str, Any]:
        consent = self._active_consent(row["id"])
        return {
            **{k: row[k] for k in ("id", "booking_id", "status", "created_at", "ended_at", "terms_notice")},
            "consent": (
                {"id": consent["id"], "scope": json.loads(consent["scope_json"]), "granted_at": consent["granted_at"]} if consent else None
            ),
        }

    # ------------------------------------------------------------------ client: intake and booking
    def intake_options(self, user_id: str) -> list[dict[str, Any]]:
        """ADV-02: fields the client may choose to share, from the compliance account summary."""
        summary = self._summary(user_id)
        if not summary:
            return []
        options = [
            {"id": f"fact.{key}", "label": summary.get("labels", {}).get(key, key.replace("_", " ")), "value": value}
            for key, value in sorted(summary["facts"].items())
        ]
        latest = summary.get("latest_check")
        if latest:
            options.append(
                {
                    "id": HEALTH_CHECK_FIELD,
                    "label": f"Health-check summary by dimension ({latest['year']}), without your answers or documents",
                    "value": [{"dimension": d["label"], "status": d["status"]} for d in latest["dimensions"]],
                }
            )
        return options

    def request(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        adviser_id = str(body.get("adviser_id") or "")
        adviser = self.db.one("SELECT * FROM advisory_advisers WHERE id = ? AND status = 'approved'", (adviser_id,))
        if not adviser:
            raise NotFound("Adviser not found")
        if adviser["user_id"] == user_id:
            raise Conflict("You cannot book yourself")
        if body.get("pre_engagement_consent") is not True:
            raise Invalid("pre_engagement_consent: confirm what you are sharing with this adviser")
        topic = str(body.get("topic") or "").strip()
        if not topic or len(topic) > 120:
            raise Invalid("topic: give a short topic (up to 120 characters)")
        message = str(body.get("message") or "").strip()
        if len(message) > 1000:
            raise Invalid("message: keep it under 1000 characters")
        preferred = body.get("preferred_date") or None
        if preferred is not None:
            try:
                dt.date.fromisoformat(str(preferred))
            except ValueError:
                raise Invalid("preferred_date: must be a date (YYYY-MM-DD)") from None
        fields = body.get("intake_fields") or []
        if not isinstance(fields, list):
            raise Invalid("intake_fields: must be a list")
        options = {o["id"]: o for o in self.intake_options(user_id)}
        unknown = [f for f in fields if f not in options]
        if unknown:
            raise Invalid(f"intake_fields: not available to share: {', '.join(map(str, unknown))}")
        intake = {"fields": sorted(set(fields)), "data": {f: options[f]["value"] for f in sorted(set(fields))}}

        with self.db.transaction():
            consent_id = self._consent(user_id, "pre_engagement", adviser_id=adviser_id, scope=intake["fields"])
            booking_id = new_id("bkg")
            self.db.insert(
                "advisory_bookings",
                {
                    "id": booking_id,
                    "client_user_id": user_id,
                    "adviser_id": adviser_id,
                    "status": "requested",
                    "topic": topic,
                    "message": message,
                    "preferred_date": preferred,
                    "intake_json": json.dumps(intake, sort_keys=True),
                    "intake_consent_id": consent_id,
                    "created_at": iso(),
                },
            )
            self.db.update("advisory_consents", {"booking_id": booking_id}, "id = ?", (consent_id,))
        self.services.audit.record("advisory.booking_requested", "booking", booking_id, actor_id=user_id, data={"intake_fields": intake["fields"]})
        self._notify(adviser["user_id"], "New booking request on tax.ng", "You have a new booking request. Sign in to tax.ng to review it.")
        return self._booking_view(self._client_booking(user_id, booking_id), with_intake=True)

    def _client_booking(self, user_id: str, booking_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM advisory_bookings WHERE id = ? AND client_user_id = ?", (booking_id, user_id))
        if not row:
            raise NotFound("Booking not found")
        return row

    def client_bookings(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM advisory_bookings WHERE client_user_id = ? ORDER BY created_at DESC", (user_id,))
        return [self._booking_view(r, with_intake=True) for r in rows]

    def cancel(self, user_id: str, booking_id: str) -> dict[str, Any]:
        row = self._client_booking(user_id, booking_id)
        if row["status"] != "requested":
            raise Conflict(f"A {row['status']} booking cannot be cancelled")
        self.db.update("advisory_bookings", {"status": "cancelled", "decided_at": iso()}, "id = ? AND status = 'requested'", (booking_id,))
        self._revoke(user_id, row["intake_consent_id"])
        self.services.audit.record("advisory.booking_cancelled", "booking", booking_id, actor_id=user_id)
        return self._booking_view(self._client_booking(user_id, booking_id), with_intake=True)

    # ------------------------------------------------------------------ adviser: requests
    def _adviser_booking(self, adviser: dict[str, Any], booking_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM advisory_bookings WHERE id = ? AND adviser_id = ?", (booking_id, adviser["id"]))
        if not row:
            raise NotFound("Booking not found")
        return row

    def adviser_bookings(self, adviser: dict[str, Any]) -> list[dict[str, Any]]:
        """List without intake data (no client data is read, so nothing to audit)."""
        rows = self.db.query("SELECT * FROM advisory_bookings WHERE adviser_id = ? ORDER BY created_at DESC", (adviser["id"],))
        return [self._booking_view(r, with_intake=False) for r in rows]

    def adviser_booking(self, adviser: dict[str, Any], booking_id: str) -> dict[str, Any]:
        """One request with the intake the client chose to share. Audited (client data)."""
        row = self._adviser_booking(adviser, booking_id)
        view = self._booking_view(row, with_intake=row["status"] in ("requested", "accepted"))
        if "intake" in view:
            self.services.audit.record(
                ACCESS_ACTION, "booking", booking_id, actor_id=adviser["user_id"], data={"resource": "intake", "booking_id": booking_id}
            )
        return view

    def decide(self, adviser: dict[str, Any], booking_id: str, decision: str, note: str) -> dict[str, Any]:
        if decision not in ("accept", "decline"):
            raise Invalid("decision: must be accept or decline")
        row = self._adviser_booking(adviser, booking_id)
        if row["status"] != "requested":
            raise Conflict(f"A {row['status']} booking cannot be {decision}ed")
        at = iso()
        with self.db.transaction():
            status = "accepted" if decision == "accept" else "declined"
            self.db.update(
                "advisory_bookings", {"status": status, "decided_at": at, "decision_note": note[:500] or None}, "id = ? AND status = 'requested'", (booking_id,)
            )
            if decision == "accept":
                engagement_id = new_id("eng")
                self.db.insert(
                    "advisory_engagements",
                    {
                        "id": engagement_id,
                        "booking_id": booking_id,
                        "client_user_id": row["client_user_id"],
                        "adviser_id": adviser["id"],
                        "status": "active",
                        "terms_notice": PRACTITIONER_NOTICE,
                        "created_at": at,
                    },
                )
                self.services.audit.record("advisory.engagement_created", "engagement", engagement_id, actor_id=adviser["user_id"], data={"booking_id": booking_id})
        self.services.audit.record(f"advisory.booking_{status}", "booking", booking_id, actor_id=adviser["user_id"])
        self._notify(
            row["client_user_id"],
            f"Your booking request was {status}",
            f"{adviser['name']} has {status} your booking request on tax.ng. Sign in to see the details.",
        )
        return self._booking_view(self._adviser_booking(adviser, booking_id), with_intake=False)

    # ------------------------------------------------------------------ engagements
    def _client_engagement(self, user_id: str, engagement_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM advisory_engagements WHERE id = ? AND client_user_id = ?", (engagement_id, user_id))
        if not row:
            raise NotFound("Engagement not found")
        return row

    def _adviser_engagement(self, adviser: dict[str, Any], engagement_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM advisory_engagements WHERE id = ? AND adviser_id = ?", (engagement_id, adviser["id"]))
        if not row:
            raise NotFound("Engagement not found")
        return row

    def client_engagements(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM advisory_engagements WHERE client_user_id = ? ORDER BY created_at DESC", (user_id,))
        out = []
        for r in rows:
            adviser = self.advisers.row(r["adviser_id"])
            out.append({**self._engagement_view(r), "adviser": {"id": adviser["id"], "name": adviser["name"], "firm": adviser["firm"]}})
        return out

    def adviser_engagements(self, adviser: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM advisory_engagements WHERE adviser_id = ? ORDER BY created_at DESC", (adviser["id"],))
        out = []
        for r in rows:
            booking = self.db.one("SELECT topic FROM advisory_bookings WHERE id = ?", (r["booking_id"],))
            out.append({**self._engagement_view(r), "topic": booking["topic"] if booking else ""})
        return out

    def grant(self, user_id: str, engagement_id: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self._client_engagement(user_id, engagement_id)
        if row["status"] != "active":
            raise Conflict("This engagement has ended")
        if body.get("consent") is not True:
            raise Invalid("consent: confirm that you allow this access")
        scope = body.get("scope") or list(ENGAGEMENT_SCOPES)
        if not isinstance(scope, list) or any(s not in ENGAGEMENT_SCOPES for s in scope):
            raise Invalid(f"scope: must be a list of {', '.join(ENGAGEMENT_SCOPES)}")
        if self._active_consent(engagement_id):
            raise Conflict("Access is already granted for this engagement")
        self._consent(user_id, "engagement", adviser_id=row["adviser_id"], engagement_id=engagement_id, booking_id=row["booking_id"], scope=sorted(scope))
        return self._engagement_view(row)

    def revoke(self, user_id: str, engagement_id: str) -> dict[str, Any]:
        row = self._client_engagement(user_id, engagement_id)
        consent = self._active_consent(engagement_id)
        if not consent:
            raise Conflict("No access is currently granted")
        self._revoke(user_id, consent["id"])
        return self._engagement_view(row)

    def end(self, user_id: str, engagement_id: str) -> dict[str, Any]:
        """The client or the adviser ends the engagement; access ends with it."""
        row = self.db.one("SELECT * FROM advisory_engagements WHERE id = ?", (engagement_id,))
        adviser = self.advisers.for_user(user_id)
        is_client = bool(row and row["client_user_id"] == user_id)
        is_adviser = bool(row and adviser and row["adviser_id"] == adviser["id"])
        if not row or not (is_client or is_adviser):
            raise NotFound("Engagement not found")
        if row["status"] != "active":
            raise Conflict("This engagement has already ended")
        consent = self._active_consent(engagement_id)
        if consent:
            self._revoke(user_id, consent["id"])
        self.db.update("advisory_engagements", {"status": "ended", "ended_at": iso(), "ended_by": user_id}, "id = ?", (engagement_id,))
        self.services.audit.record("advisory.engagement_ended", "engagement", engagement_id, actor_id=user_id, data={"by": "client" if is_client else "adviser"})
        return self._engagement_view(self.db.one("SELECT * FROM advisory_engagements WHERE id = ?", (engagement_id,)) or row)

    def adviser_report(self, adviser: dict[str, Any], engagement_id: str) -> dict[str, Any]:
        """ADV-03: delegated read of the client's report. Needs an active engagement and consent; audited."""
        row = self._adviser_engagement(adviser, engagement_id)
        if row["status"] != "active":
            raise Forbidden("This engagement has ended")
        consent = self._active_consent(engagement_id)
        if not consent or "health_check_report" not in json.loads(consent["scope_json"]):
            raise Forbidden("The client has not granted access to their health-check report")
        compliance = self.services.modules.get("compliance")
        reader = getattr(compliance, "report_for_delegate", None)
        report = reader(row["client_user_id"]) if reader else None
        self.services.audit.record(
            ACCESS_ACTION, "engagement", engagement_id, actor_id=adviser["user_id"],
            data={"resource": "health_check_report", "consent_id": consent["id"], "found": report is not None},
        )  # fmt: skip
        return {"engagement_id": engagement_id, "report": report, "consent": {"id": consent["id"], "granted_at": consent["granted_at"]}}

    def access_log(self, user_id: str, engagement_id: str) -> list[dict[str, Any]]:
        """The client's view of every adviser access and consent change for this engagement."""
        row = self._client_engagement(user_id, engagement_id)
        consent_ids = [c["id"] for c in self.db.query("SELECT id FROM advisory_consents WHERE engagement_id = ? OR booking_id = ?", (engagement_id, row["booking_id"]))]
        events = []
        for entity_id in [engagement_id, row["booking_id"], *consent_ids]:
            events.extend(self.services.audit.events(entity_id=entity_id))
        events.sort(key=lambda e: e["seq"], reverse=True)
        return [
            {"at": e["at"], "action": e["action"], "by": "you" if e["actor_id"] == user_id else "adviser", "detail": json.loads(e["data_json"])}
            for e in events
        ]

    # ------------------------------------------------------------------ user-level consents (ADV-05)
    def user_consents(self, user_id: str) -> dict[str, Any]:
        out = {}
        for kind in USER_CONSENT_KINDS:
            row = self.db.one(
                "SELECT id, granted_at FROM advisory_consents WHERE user_id = ? AND kind = ? AND revoked_at IS NULL ORDER BY granted_at DESC LIMIT 1",
                (user_id, kind),
            )
            out[kind] = {"granted": bool(row), "granted_at": row["granted_at"] if row else None, "text": CONSENT_TEXT[kind]}
        return out

    def set_user_consent(self, user_id: str, kind: str, granted: Any) -> dict[str, Any]:
        if kind not in USER_CONSENT_KINDS:
            raise NotFound("Unknown consent")
        if not isinstance(granted, bool):
            raise Invalid("granted: must be true or false")
        active = self.db.query("SELECT id FROM advisory_consents WHERE user_id = ? AND kind = ? AND revoked_at IS NULL", (user_id, kind))
        if granted and not active:
            self._consent(user_id, kind)
        if not granted:
            for row in active:
                self._revoke(user_id, row["id"])
        return self.user_consents(user_id)

    def suggestions(self, user_id: str) -> dict[str, Any]:
        """ADV-05: advisers matched to health-check findings, only with findings_matching consent."""
        if not self.user_consents(user_id)["findings_matching"]["granted"]:
            return {"consent_required": True, "items": [], "specialisms": []}
        summary = self._summary(user_id)
        latest = (summary or {}).get("latest_check")
        if not latest:
            return {"consent_required": False, "items": [], "specialisms": []}
        specs: list[str] = []
        for items in latest["findings_by_dimension"].values():
            for f in items:
                spec = f.get("specialism") or (f["tax"] if f["tax"] in SPECIALISMS else None)
                if f["status"] == "gap" and spec and spec not in specs:
                    specs.append(spec)
        self.services.audit.record("advisory.findings_used_for_matching", "user", user_id, actor_id=user_id, data={"specialisms": specs})
        listed = self.advisers.directory(None, None)["items"]
        ranked = sorted(
            (a for a in listed if set(a["specialisms"]) & set(specs)),
            key=lambda a: (-len(set(a["specialisms"]) & set(specs)), a["name"].lower(), a["id"]),
        )
        return {"consent_required": False, "items": ranked, "specialisms": specs}
