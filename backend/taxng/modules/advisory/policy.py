"""Advisory reference data, consent wording and notices (ADV-01 to ADV-05, GOV-04).

Consent texts are stored with every consent record, so a later wording change
never alters what a user agreed to.
"""

from __future__ import annotations

import datetime as dt

# Product policy, not a tax figure: register checks are repeated every year (ADV-01).
REVERIFY_AFTER = dt.timedelta(days=365)

SPECIALISMS: dict[str, str] = {
    "pit": "Personal income tax and self-assessment",
    "paye": "PAYE and payroll",
    "vat": "VAT",
    "wht": "Withholding tax",
    "cit": "Companies income tax and development levy",
    "cgt": "Capital gains",
    "stamp_duty": "Stamp duties",
    "transfer_pricing": "Transfer pricing",
    "international": "International and cross-border tax",
    "disputes": "Tax audits, objections and appeals",
    "nonprofit": "Nonprofits and exempt bodies",
}

STATES = (
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
    "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi",
    "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
)  # fmt: skip

# GOV-04: the platform introduces; the practitioner of record advises.
PRACTITIONER_NOTICE = (
    "Advice is given by the adviser named here, as practitioner of record, under their own engagement terms. "
    "tax.ng (Astound Innovation Hub) introduces you and provides the tools. It does not give the advice and is "
    "not a party to the engagement."
)

CONSENT_TEXT: dict[str, str] = {
    # ADV-02: before the booking, separate from marketing and from engagement consent.
    "pre_engagement": (
        "I agree to share the information I selected with this adviser so they can consider my booking request. "
        "This does not sign me up for marketing and does not give the adviser access to my health-check report."
    ),
    # ADV-03: scoped, revocable delegated read access.
    "engagement": (
        "I allow this adviser to read my latest tax health-check report for this engagement only. "
        "I can withdraw this at any time, and every access is logged."
    ),
    "marketing": "I agree to receive offers about adviser services from tax.ng. I can withdraw this at any time.",
    # ADV-05: findings are used for matching only with this consent, and never for advertising.
    "findings_matching": (
        "I allow tax.ng to use my health-check findings to suggest advisers to me. "
        "My findings are never used for advertising. I can withdraw this at any time."
    ),
}

ENGAGEMENT_SCOPES = {"health_check_report": "Latest tax health-check report (read only)"}
USER_CONSENT_KINDS = ("marketing", "findings_matching")
