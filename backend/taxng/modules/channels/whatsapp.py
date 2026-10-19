"""WhatsApp bot (CH-02).

Inbound messages arrive at a signed webhook. The bot understands a few
commands and otherwise hands the text to Tax AI, whose citation and figure
guards still apply:

    PAYE 500000 | PAYE 6m | tax 450k monthly   -> PIT calculator (rules engine)
    VAT 100000 [inclusive]                     -> VAT calculator
    help | menu                                -> command list
    stop | start                               -> opt out of / back in to alerts
    anything else                              -> services.assistant.answer()

No figure is written in this file: every amount in a reply comes from a
calculator result or from Tax AI's guarded answer.

Privacy: the phone number is reduced to an HMAC (``phone_hash``) under a
channel-specific key as soon as it arrives. Only the hash, the message kind and,
for free-text questions, a short snippet are logged, and log rows expire after
RETENTION_DAYS.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ... import config
from ...ai.assistant import REGIME_LABELS
from ...calculators import CALCULATORS
from ...format import naira, percent
from ...platform.errors import Invalid
from ...platform.util import canonical_json, iso, new_id, now, sign, verify_signature

if TYPE_CHECKING:
    from ...services import Services

SIGNATURE_HEADER = "x-taxng-signature"
RATE_LIMIT = 8  # inbound messages per sender per window
RATE_WINDOW = dt.timedelta(minutes=1)
RETENTION_DAYS = 30
RETENTION_NOTE = (
    f"WhatsApp logs keep a one-way hash of the phone number, the message type and, for questions, a short snippet. "
    f"Rows are deleted after {RETENTION_DAYS} days."
)
MAX_AI_CHARS = 900
SNIPPET_CHARS = 80

_MULT = {"k": 10**3, "thousand": 10**3, "m": 10**6, "million": 10**6, "bn": 10**9, "billion": 10**9}
_CALC = re.compile(
    r"^\s*(?P<cmd>paye|pit|tax|salary|income|vat)\b\s*(?:on|for|of|is)?\s*(?:₦|ngn|n(?=\d))?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>million|thousand|billion|bn|k|m)?\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_MONTHLY = re.compile(r"\b(monthly|per month|a month|every month|pm)\b|/\s*month", re.IGNORECASE)
_YEAR = re.compile(r"\b(20[1-3]\d)\b")
_INCLUSIVE = re.compile(r"\b(incl|inclusive|including vat|vat inclusive|gross)\b", re.IGNORECASE)
_STOP = {"stop", "unsubscribe", "stop all", "opt out", "optout"}
_START = {"start", "subscribe", "opt in", "optin"}
_HELP = {"help", "menu", "hi", "hello", "?"}


def webhook_secret(services: Services) -> str:
    return sign(services.secret, "channels.whatsapp.webhook.v1")


def sign_payload(services: Services, raw: str) -> str:
    return sign(webhook_secret(services), raw)


def signed_message(request: Any) -> str:
    """The exact bytes to verify: the raw body when the HTTP adapter provides it.

    ``Request`` currently carries only the parsed body, so until the shared
    change in the report lands, senders sign the canonical JSON of the body.
    """
    raw = getattr(request, "raw_body", None)
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        return raw
    return canonical_json(request.body)


def verify_webhook(services: Services, request: Any) -> bool:
    signature = request.headers.get(SIGNATURE_HEADER, "")
    if signature.startswith("sha256="):
        signature = signature[7:]
    return verify_signature(webhook_secret(services), signed_message(request), signature)


def normalise_phone(raw: str) -> str:
    digits = re.sub(r"[\s\-()]", "", str(raw or ""))
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise Invalid("from: phone number must contain digits only")
    if digits.startswith("0") and len(digits) == 11:  # Nigerian local format 0XXXXXXXXXX
        digits = "234" + digits[1:]
    if not 10 <= len(digits) <= 15:
        raise Invalid("from: phone number is not a valid international number")
    return digits


def parse_amount(num: str, mult: str | None) -> Decimal | None:
    try:
        value = Decimal(num.replace(",", ""))
    except InvalidOperation:
        return None
    return value * _MULT.get((mult or "").lower(), 1)


class WhatsAppBot:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db
        self._phone_key = sign(services.secret, "channels.whatsapp.phone.v1")
        host = config.PUBLIC_HOST or "tax.ng"
        self.base_url = host if host.startswith("http") else f"https://{host}"

    @property
    def adapter(self) -> Any:
        return self.services.adapters.get("whatsapp")

    def phone_hash(self, phone: str) -> str:
        return sign(self._phone_key, normalise_phone(phone))

    # -------------------------------------------------------------- replies
    def _citation(self, ids: list[str]) -> str | None:
        if not ids:
            return None
        preferred = sorted(ids, key=lambda i: (not i.endswith(".rates"), i))[0]
        p = self.services.library.provisions.get(preferred)
        return f"{p.title} ({p.instrument}, {p.section})" if p else preferred

    def reply_pit(self, amount: Decimal, monthly: bool, year: int | None) -> str:
        annual = amount * 12 if monthly else amount
        payload: dict[str, Any] = {"annual_gross_income": str(annual)}
        if year:
            payload["tax_year"] = year
        result = CALCULATORS["pit"](payload, self.services.tree).to_dict()
        out = result["outputs"]
        lines = [
            f"PAYE estimate, {result['period'].lower()} ({REGIME_LABELS.get(result['regime'], result['regime'])})",
            f"Gross income: {naira(Decimal(result['inputs']['annual_gross_income']))} a year",
        ]
        if monthly:
            lines.append("Note: monthly amount converted to annual (x 12).")
        lines += [
            f"Annual tax: {naira(Decimal(out['annual_tax']))}",
            f"Monthly PAYE: {naira(Decimal(out['monthly_tax']))}",
            f"Effective rate: {out['effective_rate_percent']}%",
        ]
        cite = self._citation(result["citations"])
        if cite:
            lines.append(f"Source: {cite}")
        lines.append("Assumes no deductions or rent relief. Add them in the calculator:")
        lines.append(f"{self.base_url}/#/calculators/pit")
        lines.append("General information, not tax advice. Rules are pending legal sign-off.")
        return "\n".join(lines)

    def reply_vat(self, amount: Decimal, inclusive: bool) -> str:
        result = CALCULATORS["vat"]({"amount": str(amount), "amount_includes_vat": inclusive}, self.services.tree).to_dict()
        out = result["outputs"]
        lines = [
            f"VAT on a standard-rated supply ({result['period'].lower()})",
            f"Net amount: {naira(Decimal(out['net_amount']))}",
            f"VAT at {percent(Decimal(out['rate']))}: {naira(Decimal(out['vat']))}",
            f"Total: {naira(Decimal(out['gross_amount']))}",
        ]
        if inclusive:
            lines.append("Note: the amount you sent was treated as including VAT.")
        cite = self._citation(result["citations"])
        if cite:
            lines.append(f"Source: {cite}")
        lines.append(f"Zero-rated or exempt supply? Use the calculator: {self.base_url}/#/calculators/vat")
        lines.append("General information, not tax advice. Rules are pending legal sign-off.")
        return "\n".join(lines)

    def reply_ai(self, text: str) -> str:
        result = self.services.assistant.answer(text)
        answer = result["answer"].strip()
        if len(answer) > MAX_AI_CHARS:
            cut = answer[:MAX_AI_CHARS]
            end = max(cut.rfind(". "), cut.rfind(".\n"))
            answer = (cut[: end + 1] if end > MAX_AI_CHARS // 3 else cut.rstrip()) + " ..."
        lines = [answer]
        cites = [f"{c['title']} ({c['instrument']})" for c in result["citations"][:2]]
        if cites:
            lines.append("Sources: " + "; ".join(cites))
        if result["escalate"]:
            lines.append("For your own situation, speak to a tax professional.")
        lines.append(f"Read more: {self.base_url}/#/ask")
        lines.append("General information, not tax advice.")
        return "\n\n".join(lines[:1]) + "\n\n" + "\n".join(lines[1:])

    @staticmethod
    def reply_help() -> str:
        return "\n".join(
            [
                "tax.ng on WhatsApp. Send:",
                "PAYE 500000 (annual pay) or PAYE 450k monthly",
                "VAT 100000 (add VAT) or VAT 107500 inclusive (extract VAT)",
                "Any tax question in plain words, for example: what is rent relief?",
                "STOP to stop alerts, START to turn them back on.",
                "General information, not tax advice.",
            ]
        )

    def classify(self, text: str) -> tuple[str, str]:
        """Returns (kind, reply)."""
        clean = " ".join(text.strip().split())
        lowered = clean.lower().strip(".!")
        if lowered in _HELP:
            return "help", self.reply_help()
        m = _CALC.match(clean)
        if m:
            amount = parse_amount(m.group("num"), m.group("mult"))
            rest = m.group("rest") or ""
            if amount is not None and amount > 0:
                if m.group("cmd").lower() == "vat":
                    return "vat", self.reply_vat(amount, bool(_INCLUSIVE.search(rest)))
                year = _YEAR.search(rest)
                return "paye", self.reply_pit(amount, bool(_MONTHLY.search(rest)), int(year.group(1)) if year else None)
        if len(clean) < 3:
            return "help", self.reply_help()
        return "ai", self.reply_ai(clean)

    # -------------------------------------------------------------- storage
    def purge_expired(self) -> int:
        cutoff = iso(now() - dt.timedelta(days=RETENTION_DAYS))
        return self.db.execute("DELETE FROM wa_messages WHERE created_at < ?", (cutoff,)).rowcount

    def _log(self, phone_hash: str, direction: str, kind: str, snippet: str = "", provider_id: str | None = None) -> None:
        self.db.insert(
            "wa_messages",
            {
                "id": new_id("wam"),
                "phone_hash": phone_hash,
                "direction": direction,
                "kind": kind,
                "snippet": snippet[:SNIPPET_CHARS],
                "provider_message_id": provider_id,
                "created_at": iso(),
            },
        )

    def _deliver(self, phone: str, phone_hash: str, body: str) -> None:
        self.adapter.send(self.services.notifier, f"wa:{phone_hash[:16]}", normalise_phone(phone), body)

    def handle_inbound(self, phone: str, text: str, provider_message_id: str | None = None) -> dict[str, Any]:
        text = str(text or "")[:1000]
        h = self.phone_hash(phone)
        self.purge_expired()
        if provider_message_id and self.db.one("SELECT 1 FROM wa_messages WHERE provider_message_id = ?", (provider_message_id,)):
            return {"status": "duplicate", "mode": self.adapter.mode}
        stamp = iso()
        self.db.execute(
            "INSERT INTO wa_contacts (phone_hash, first_seen_at, last_seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(phone_hash) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            (h, stamp, stamp),
        )
        recent = self.db.scalar(
            "SELECT COUNT(*) FROM wa_messages WHERE phone_hash = ? AND direction = 'in' AND created_at >= ?",
            (h, iso(now() - RATE_WINDOW)),
        )
        if recent >= RATE_LIMIT:
            self._log(h, "in", "rate_limited", provider_id=provider_message_id)
            return {"status": "rate_limited", "mode": self.adapter.mode, "reply": None}

        lowered = " ".join(text.lower().split()).strip(".!")
        if lowered in _STOP:
            self.db.update("wa_contacts", {"opted_out_at": stamp}, "phone_hash = ?", (h,))
            kind, reply = "stop", "You will not receive alerts from tax.ng any more. You can still ask questions. Send START to turn alerts back on."
            self.services.audit.record("whatsapp.opt_out", "wa_contact", h[:16])
        elif lowered in _START:
            self.db.update("wa_contacts", {"opted_out_at": None}, "phone_hash = ?", (h,))
            kind, reply = "start", "Alerts from tax.ng are on. Send STOP at any time to turn them off."
            self.services.audit.record("whatsapp.opt_in", "wa_contact", h[:16])
        else:
            kind, reply = self.classify(text)

        self._log(h, "in", kind, text if kind == "ai" else "", provider_message_id)
        self._deliver(phone, h, reply)
        self._log(h, "out", kind)
        self.services.store.record_event("whatsapp_message", {"kind": kind})
        return {"status": "replied", "kind": kind, "reply": reply, "mode": self.adapter.mode}

    def send_alert(self, phone: str, body: str) -> dict[str, Any]:
        """A message the user did not ask for. Only to contacts who wrote first and have not opted out."""
        h = self.phone_hash(phone)
        contact = self.db.one("SELECT opted_out_at FROM wa_contacts WHERE phone_hash = ?", (h,))
        if contact is None:
            return {"status": "not_opted_in", "mode": self.adapter.mode}
        if contact["opted_out_at"]:
            return {"status": "suppressed_opted_out", "mode": self.adapter.mode}
        self._deliver(phone, h, body)
        self._log(h, "out", "alert")
        return {"status": "sent", "mode": self.adapter.mode}

    def log(self, limit: int = 50) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT substr(phone_hash, 1, 12) AS sender, direction, kind, snippet, created_at FROM wa_messages "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (min(limit, 200),),
        )
        return {
            "items": rows,
            "contacts": self.db.scalar("SELECT COUNT(*) FROM wa_contacts"),
            "opted_out": self.db.scalar("SELECT COUNT(*) FROM wa_contacts WHERE opted_out_at IS NOT NULL"),
            "retention_note": RETENTION_NOTE,
            "adapter": self.adapter.info(),
        }
