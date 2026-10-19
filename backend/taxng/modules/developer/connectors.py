"""ERP connector SDK (EINV-03, Annex A9).

A connector does three things:

* ``fetch(source)``: get raw records (rows) from somewhere.
* ``map(records, profile)``: turn rows into tax.ng e-invoice payloads.
* ``reconcile(services, org_id, source)``: compare what was imported with what
  was submitted to and accepted by NRS.

``FileConnector`` reads CSV or JSON exports. ``LiveApiConnector`` stands for a
direct ERP API sync, which needs licensed API access and raises
``NotConfigured``. Mapping profiles are data in content/developer/erp_mappings.yaml.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from typing import TYPE_CHECKING, Any

import yaml

from ...platform.adapters import NotConfigured
from ...platform.errors import Invalid

if TYPE_CHECKING:
    from ...services import Services

FIELDS = ("external_id", "invoice_number", "issue_date", "due_date", "buyer_name", "buyer_tin", "description", "quantity", "unit_price", "vat_category", "invoice_total")
HEADER_FIELDS = ("external_id", "invoice_number", "issue_date", "due_date", "buyer_name", "buyer_tin", "invoice_total")
MAX_ROWS = 5000


def load_profiles(services: Services) -> dict[str, dict[str, Any]]:
    path = services.content_dir / "developer" / "erp_mappings.yaml"
    if not path.exists():
        return {}
    profiles = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("profiles", {})
    for pid, p in profiles.items():
        missing = [f for f in ("external_id", "invoice_number", "description", "quantity", "unit_price") if f not in p.get("columns", {})]
        if missing:
            raise ValueError(f"ERP profile {pid}: missing column mapping for {missing[0]}")
    return profiles


def source_for(profile_id: str) -> str:
    return f"erp:{profile_id}"


class Connector:
    """Base class for ERP connectors."""

    id = "base"
    label = "Connector"

    def fetch(self, source: dict[str, Any]) -> list[dict[str, str]]:
        raise NotImplementedError

    def map(self, records: list[dict[str, str]], profile: dict[str, Any]) -> list[dict[str, Any]]:
        columns: dict[str, str] = profile["columns"]
        codes = {str(k).strip().lower(): v for k, v in (profile.get("vat_codes") or {}).items()}
        invoices: dict[str, dict[str, Any]] = {}
        previous: dict[str, str] = {}
        for record in records:
            row = {field: str(record.get(col, "") or "").strip() for field, col in columns.items()}
            if profile.get("fill_down"):
                if row.get("external_id"):
                    previous = {f: row.get(f, "") for f in HEADER_FIELDS}
                else:
                    row.update({f: v for f, v in previous.items() if not row.get(f)})
            ext = row.get("external_id", "")
            if not ext:
                continue
            inv = invoices.get(ext)
            if inv is None:
                inv = {
                    "external_id": ext,
                    "invoice_number": row.get("invoice_number") or ext,
                    "issue_date": self._date(row.get("issue_date", ""), profile),
                    "due_date": self._date(row.get("due_date", ""), profile),
                    "buyer_name": row.get("buyer_name", ""),
                    "buyer_tin": row.get("buyer_tin", ""),
                    "lines": [],
                }
                if row.get("invoice_total"):
                    inv["declared_totals"] = {"gross": row["invoice_total"]}
                invoices[ext] = inv
            code = row.get("vat_category", "")
            inv["lines"].append(
                {
                    "description": row.get("description", ""),
                    "quantity": row.get("quantity", ""),
                    "unit_price": row.get("unit_price", ""),
                    "vat_category": codes.get(code.lower(), code) if code else "standard",
                }
            )
        return list(invoices.values())

    @staticmethod
    def _date(raw: str, profile: dict[str, Any]) -> str:
        if not raw:
            return ""
        for fmt in profile.get("date_formats") or ["%Y-%m-%d"]:
            try:
                return dt.datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return raw  # left as is so validation reports it against issue_date

    def reconcile(self, services: Services, org_id: str, source: str) -> dict[str, Any]:
        einvoicing = services.modules.get("einvoicing")
        if einvoicing is None:
            raise NotConfigured("einvoicing module is not installed")
        return einvoicing.source_report(org_id, source)


class FileConnector(Connector):
    """CSV or JSON export file. ``source = {"format": "csv"|"json", "text": str}``."""

    id = "file"
    label = "File import (CSV or JSON)"

    def fetch(self, source: dict[str, Any]) -> list[dict[str, str]]:
        fmt, text = source.get("format"), source.get("text", "")
        if not text.strip():
            raise Invalid("content: the file is empty")
        if fmt == "csv":
            try:
                rows = list(csv.DictReader(io.StringIO(text)))
            except csv.Error as exc:
                raise Invalid(f"content: could not read the CSV ({exc})") from None
        elif fmt == "json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise Invalid("content: not valid JSON") from None
            if isinstance(data, dict):
                data = data.get("rows") or data.get("invoices") or []
            if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
                raise Invalid("content: JSON must be an array of row objects")
            rows = [{str(k): "" if v is None else str(v) for k, v in r.items()} for r in data]
        else:
            raise Invalid("format: must be csv or json")
        if len(rows) > MAX_ROWS:
            raise Invalid(f"content: at most {MAX_ROWS} rows per import")
        return rows


class LiveApiConnector(Connector):
    """Direct sync from the ERP's API. Not available until licensed API access is in place."""

    id = "live"
    label = "Live ERP sync"

    def __init__(self, profile_id: str, profile: dict[str, Any]) -> None:
        self.profile_id, self.profile = profile_id, profile

    def fetch(self, source: dict[str, Any]) -> list[dict[str, str]]:
        needs = self.profile.get("live_sync") or "licensed API access"
        raise NotConfigured(f"{self.profile.get('label', self.profile_id)} live sync is not configured: {needs}")
