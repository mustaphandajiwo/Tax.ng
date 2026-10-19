"""Localisation (CH-04, CH-05): UI string catalogues and guide summary translations.

English (``content/i18n/en.yaml``) is the source catalogue and is always
served. Other catalogues may hold draft strings marked ``status: draft``.
Drafts are never served. A string reaches users only after this workflow:

    staff submits a translation -> a legal_reviewer or editor (not the submitter)
    approves it -> GET /api/i18n/{lang} serves it

A language is selectable once at least one of its strings is approved; keys
without an approved translation fall back to English and are listed as such.
Guide summary translations follow the same workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ...legal.corpus import ContentError, _check_no_figures
from ...platform.access import NotFoundError
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id

if TYPE_CHECKING:
    from ...services import Services

SOURCE_LANG = "en"
MAX_STRING = 500
MAX_SUMMARY = 600


def load_catalogues(content_dir: Path) -> dict[str, dict[str, Any]]:
    base = content_dir / "i18n"
    catalogues: dict[str, dict[str, Any]] = {}
    for path in sorted(base.glob("*.yaml")) if base.is_dir() else []:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        lang = raw["lang"]
        strings = raw.get("strings") or {}
        drafts: dict[str, str] = {}
        if lang == SOURCE_LANG:
            for key, text in strings.items():
                if not isinstance(text, str):
                    raise ContentError(f"i18n en: {key} must be plain text")
                _check_no_figures(f"i18n en {key}", text)
        else:
            for key, entry in strings.items():
                if not isinstance(entry, dict) or entry.get("status") != "draft":
                    # Content may only propose drafts; approval is recorded by a reviewer.
                    raise ContentError(f"i18n {lang}: {key} must be a draft entry with status: draft")
                drafts[key] = str(entry["text"])
        catalogues[lang] = {
            "lang": lang,
            "name": raw["name"],
            "native_name": raw.get("native_name", raw["name"]),
            "note": raw.get("note", ""),
            "strings": strings if lang == SOURCE_LANG else {},
            "drafts": drafts,
        }
    if SOURCE_LANG not in catalogues:
        raise ContentError("i18n: the English source catalogue is missing")
    english = catalogues[SOURCE_LANG]["strings"]
    for lang, cat in catalogues.items():
        unknown = set(cat["drafts"]) - set(english)
        if unknown:
            raise ContentError(f"i18n {lang}: unknown keys {sorted(unknown)}")
    return catalogues


class Localisation:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db
        self.catalogues = load_catalogues(services.content_dir)

    @property
    def english(self) -> dict[str, str]:
        return self.catalogues[SOURCE_LANG]["strings"]

    def _lang(self, lang: str, *, allow_source: bool = False) -> dict[str, Any]:
        cat = self.catalogues.get(lang)
        if cat is None or (lang == SOURCE_LANG and not allow_source):
            raise Invalid("lang: unknown or not translatable")
        return cat

    def approved(self, lang: str) -> dict[str, str]:
        rows = self.db.query(
            "SELECT key, text FROM i18n_submissions WHERE lang = ? AND status = 'approved' ORDER BY reviewed_at, rowid", (lang,)
        )
        return {r["key"]: r["text"] for r in rows if r["key"] in self.english}  # later approvals win

    # ---------------------------------------------------------------- public
    def languages(self) -> list[dict[str, Any]]:
        total = len(self.english)
        out = [{"lang": SOURCE_LANG, "name": "English", "native_name": "English", "approved": total, "total": total, "status": "source"}]
        for lang, cat in self.catalogues.items():
            if lang == SOURCE_LANG:
                continue
            count = len(self.approved(lang))
            if count:
                out.append({"lang": lang, "name": cat["name"], "native_name": cat["native_name"], "approved": count, "total": total, "status": "reviewed"})
        return out

    def pending_languages(self) -> list[dict[str, Any]]:
        return [
            {"lang": lang, "name": cat["name"], "native_name": cat["native_name"], "drafts": len(cat["drafts"]), "approved": len(self.approved(lang))}
            for lang, cat in self.catalogues.items()
            if lang != SOURCE_LANG
        ]

    def catalogue(self, lang: str) -> dict[str, Any]:
        if lang == SOURCE_LANG:
            return {"lang": lang, "status": "source", "strings": dict(self.english), "fallback_keys": []}
        if lang not in self.catalogues:
            raise NotFoundError("Unknown language")
        approved = self.approved(lang)
        if not approved:
            raise NotFoundError("No reviewed translations for this language yet")
        strings = {**self.english, **approved}
        return {
            "lang": lang,
            "status": "reviewed",
            "strings": strings,
            "fallback_keys": sorted(k for k in self.english if k not in approved),
        }

    # ----------------------------------------------------------------- staff
    def staff_view(self, lang: str) -> dict[str, Any]:
        cat = self._lang(lang)
        approved = self.approved(lang)
        pending = {
            r["key"]: r
            for r in self.db.query(
                "SELECT id, key, text, submitted_by, submitted_at FROM i18n_submissions WHERE lang = ? AND status = 'submitted' "
                "ORDER BY submitted_at, rowid",
                (lang,),
            )
        }
        return {
            "lang": lang,
            "name": cat["name"],
            "note": cat["note"],
            "items": [
                {
                    "key": key,
                    "english": text,
                    "draft": cat["drafts"].get(key),
                    "approved": approved.get(key),
                    "pending": pending.get(key),
                }
                for key, text in self.english.items()
            ],
        }

    def submit_string(self, staff_id: str, lang: str, key: str, text: str) -> dict[str, Any]:
        self._lang(lang)
        if key not in self.english:
            raise Invalid("key: unknown string key")
        text = text.strip()
        if not 1 <= len(text) <= MAX_STRING:
            raise Invalid(f"text: enter between 1 and {MAX_STRING} characters")
        try:
            _check_no_figures("text", text)
        except ContentError:
            raise Invalid("text: translations may not state figures; figures come from the rules engine") from None
        sub_id = new_id("i18n")
        self.db.insert(
            "i18n_submissions",
            {"id": sub_id, "lang": lang, "key": key, "text": text, "status": "submitted", "submitted_by": staff_id, "submitted_at": iso()},
        )
        self.services.audit.record("i18n.submitted", "i18n_submission", sub_id, actor_id=staff_id, data={"lang": lang, "key": key})
        return {"id": sub_id, "status": "submitted"}

    def _review(self, table: str, entity: str, reviewer_id: str, sub_id: str, decision: str, note: str) -> dict[str, Any]:
        row = self.db.one(f"SELECT * FROM {table} WHERE id = ?", (sub_id,))  # table is a fixed internal name
        if row is None:
            raise NotFoundError("Submission not found")
        if row["status"] != "submitted":
            raise Conflict(f"This submission is already {row['status']}")
        if row["submitted_by"] == reviewer_id:
            raise Conflict("A different reviewer must approve or reject your own submission")
        self.db.update(
            table,
            {"status": decision, "reviewed_by": reviewer_id, "reviewed_at": iso(), "review_note": note.strip()[:500] or None},
            "id = ? AND status = 'submitted'",
            (sub_id,),
        )
        self.services.audit.record(f"{entity}.{decision}", entity, sub_id, actor_id=reviewer_id, data={"lang": row["lang"]})
        return {"id": sub_id, "status": decision}

    def review_string(self, reviewer_id: str, sub_id: str, decision: str, note: str = "") -> dict[str, Any]:
        return self._review("i18n_submissions", "i18n_submission", reviewer_id, sub_id, decision, note)

    # ---------------------------------------------------- guide summaries
    def submit_guide(self, staff_id: str, guide_id: str, lang: str, summary: str) -> dict[str, Any]:
        self._lang(lang)
        if guide_id not in self.services.library.guides:
            raise Invalid("guide_id: unknown guide")
        summary = " ".join(summary.split())
        if not 3 <= len(summary) <= MAX_SUMMARY:
            raise Invalid(f"summary: enter between 3 and {MAX_SUMMARY} characters")
        try:
            _check_no_figures("summary", summary)
        except ContentError:
            raise Invalid("summary: translations may not state figures; figures come from the rules engine") from None
        sub_id = new_id("gtr")
        self.db.insert(
            "guide_translations",
            {"id": sub_id, "guide_id": guide_id, "lang": lang, "summary": summary, "status": "submitted", "submitted_by": staff_id, "submitted_at": iso()},
        )
        self.services.audit.record("guide_translation.submitted", "guide_translation", sub_id, actor_id=staff_id, data={"lang": lang, "guide_id": guide_id})
        return {"id": sub_id, "status": "submitted"}

    def review_guide(self, reviewer_id: str, sub_id: str, decision: str, note: str = "") -> dict[str, Any]:
        return self._review("guide_translations", "guide_translation", reviewer_id, sub_id, decision, note)

    def guide_submissions(self, status: str | None) -> list[dict[str, Any]]:
        sql = "SELECT id, guide_id, lang, summary, status, submitted_by, submitted_at, reviewed_by, reviewed_at FROM guide_translations"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        rows = self.db.query(sql + " ORDER BY submitted_at DESC, rowid DESC LIMIT 200", params)
        for r in rows:
            g = self.services.library.guides.get(r["guide_id"])
            r["guide_title"] = g.title if g else r["guide_id"]
            r["english_summary"] = g.summary if g else ""
        return rows

    def guide_translations(self, guide_id: str) -> dict[str, Any]:
        guide = self.services.library.guides.get(guide_id)
        if guide is None:
            raise NotFoundError("Unknown guide")
        items: dict[str, dict[str, Any]] = {}
        for lang, value in (guide.translations or {}).items():
            summary = value.get("summary") if isinstance(value, dict) else value
            if summary:
                items[lang] = {"lang": lang, "summary": str(summary), "approved_at": None, "source": "content"}
        for r in self.db.query(
            "SELECT lang, summary, reviewed_at FROM guide_translations WHERE guide_id = ? AND status = 'approved' ORDER BY reviewed_at, rowid",
            (guide_id,),
        ):
            items[r["lang"]] = {"lang": r["lang"], "summary": r["summary"], "approved_at": r["reviewed_at"], "source": "review"}
        names = {lang: cat["name"] for lang, cat in self.catalogues.items()}
        return {
            "guide_id": guide_id,
            "english_summary": guide.summary,
            "items": [{**v, "name": names.get(k, k)} for k, v in sorted(items.items())],
        }
