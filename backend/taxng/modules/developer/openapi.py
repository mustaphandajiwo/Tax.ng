"""Declared spec for the public API (/api/v1) and the OpenAPI 3.1 document built from it.

``OPERATIONS`` is the single list of documented operations. public_api.py
implements each one, and tests/modules/test_developer.py checks that every
documented method and path is routed.
"""

from __future__ import annotations

from typing import Any

from ...calculators import CALCULATORS
from .service import SCOPES

API_VERSION = "1.0.0"
ERROR_CODES = {
    "unauthorized": "401: missing, unknown or revoked API key",
    "insufficient_scope": "403: the key lacks the scope this operation needs",
    "forbidden": "403: not allowed",
    "not_found": "404: no such resource for this key's organisation",
    "conflict": "409: the request clashes with the resource's current state",
    "idempotency_conflict": "409: the Idempotency-Key was reused with a different request",
    "invalid_input": "422: field-level errors in `fields`",
    "rule_not_in_force": "422: no rule is in force for the requested date",
    "rate_limited": "429: too many requests; see Retry-After",
    "integration_not_configured": "503: the production integration is not configured",
}


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


OPERATIONS: list[dict[str, Any]] = [
    {"method": "get", "path": "/api/v1/openapi.json", "id": "getOpenApi", "summary": "This OpenAPI document", "tag": "meta", "scope": None, "response": None},
    {"method": "get", "path": "/api/v1/key", "id": "getKey", "summary": "The calling API key: organisation, scopes and rate limit", "tag": "meta", "scope": "", "response": "Key"},
    {
        "method": "post",
        "path": "/api/v1/calculate/{calculator}",
        "id": "calculate",
        "summary": "Run a tax calculator (rules-engine result with steps, citations and rules version)",
        "tag": "calculators",
        "scope": "calculators:read",
        "path_params": {"calculator": {"type": "string", "enum": sorted(CALCULATORS)}},
        "request": "CalculatorInput",
        "response": "CalculationResult",
    },
    {
        "method": "get",
        "path": "/api/v1/parameters/{name}",
        "id": "getParameter",
        "summary": "An effective-dated rules parameter, as in force on a date",
        "tag": "rules",
        "scope": "rules:read",
        "path_params": {"name": {"type": "string", "example": "vat.standard_rate"}},
        "query_params": {"on": {"type": "string", "format": "date", "description": "Date (YYYY-MM-DD). Defaults to today."}},
        "response": "Parameter",
    },
    {
        "method": "get",
        "path": "/api/v1/einvoices",
        "id": "listEInvoices",
        "summary": "List e-invoices for the key's organisation",
        "tag": "einvoices",
        "scope": "einvoices:read",
        "query_params": {"status": {"type": "string", "enum": ["draft", "validated", "submitted", "accepted", "rejected", "cancelled"]}},
        "response": "EInvoiceList",
    },
    {
        "method": "post",
        "path": "/api/v1/einvoices",
        "id": "createEInvoice",
        "summary": "Create a draft e-invoice (VAT per line computed by the rules engine)",
        "tag": "einvoices",
        "scope": "einvoices:write",
        "idempotent": True,
        "request": "EInvoiceInput",
        "response": "EInvoice",
        "status": "201",
    },
    {
        "method": "get",
        "path": "/api/v1/einvoices/{invoice_id}",
        "id": "getEInvoice",
        "summary": "An e-invoice with its status, IRN, QR payload and event log",
        "tag": "einvoices",
        "scope": "einvoices:read",
        "path_params": {"invoice_id": {"type": "string"}},
        "response": "EInvoice",
    },
    {
        "method": "post",
        "path": "/api/v1/einvoices/{invoice_id}/submit",
        "id": "submitEInvoice",
        "summary": "Validate and submit an e-invoice to NRS. Status arrives asynchronously.",
        "tag": "einvoices",
        "scope": "einvoices:write",
        "idempotent": True,
        "path_params": {"invoice_id": {"type": "string"}},
        "response": "Submission",
    },
]

SCHEMAS: dict[str, Any] = {
    "Error": {
        "type": "object",
        "required": ["error", "correlation_id"],
        "properties": {
            "error": {"type": "string", "enum": sorted(ERROR_CODES)},
            "message": {"type": "string"},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Field path to message, e.g. lines.0.quantity"},
            "correlation_id": {"type": "string"},
        },
    },
    "Key": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "prefix": {"type": "string"},
            "org_id": {"type": "string"},
            "scopes": {"type": "array", "items": {"type": "string", "enum": sorted(SCOPES)}},
            "rate_per_minute": {"type": "integer"},
            "mode": {"type": "string", "enum": ["sandbox", "production"]},
        },
    },
    "CalculatorInput": {
        "type": "object",
        "description": "Calculator-specific fields, the same as the web calculators. Money as decimal strings.",
        "additionalProperties": True,
    },
    "CalculationResult": {
        "type": "object",
        "required": ["calculator", "outputs", "steps", "citations", "rules_version", "review_status"],
        "properties": {
            "calculator": {"type": "string"},
            "regime": {"type": "string"},
            "period": {"type": "string"},
            "inputs": {"type": "object"},
            "outputs": {"type": "object", "additionalProperties": {"type": "string"}},
            "steps": {"type": "array", "items": {"type": "object"}},
            "citations": {"type": "array", "items": {"type": "object"}},
            "review_status": {"type": "string"},
            "rules_version": {"type": "string"},
            "engine_version": {"type": "string"},
        },
    },
    "Parameter": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "on": {"type": "string", "format": "date"},
            "description": {"type": "string"},
            "unit": {"type": ["string", "null"]},
            "value": {},
            "scale": {"type": "array", "items": {"type": "object", "properties": {"threshold": {"type": "string"}, "rate": {"type": "string"}}}},
            "in_force": {"type": "boolean"},
            "review_status": {"type": "string"},
            "reference": {},
            "rules_version": {"type": "string"},
        },
    },
    "EInvoiceLineInput": {
        "type": "object",
        "required": ["description", "quantity", "unit_price"],
        "properties": {
            "description": {"type": "string"},
            "quantity": {"type": "string", "example": "2"},
            "unit_price": {"type": "string", "example": "50000.00"},
            "vat_category": {"type": "string", "enum": ["standard", "zero_rated", "exempt"], "default": "standard"},
        },
    },
    "EInvoiceInput": {
        "type": "object",
        "required": ["invoice_number", "issue_date", "buyer_name", "buyer_tin", "lines"],
        "properties": {
            "invoice_number": {"type": "string", "maxLength": 50},
            "issue_date": {"type": "string", "format": "date"},
            "due_date": {"type": "string", "format": "date"},
            "buyer_name": {"type": "string"},
            "buyer_tin": {"type": "string", "description": "12345678-0001 or a 10-digit TIN"},
            "buyer_email": {"type": "string"},
            "currency": {"type": "string", "enum": ["NGN"]},
            "notes": {"type": "string"},
            "lines": {"type": "array", "items": _ref("EInvoiceLineInput"), "minItems": 1},
            "declared_totals": {"type": "object", "properties": {"net": {"type": "string"}, "vat": {"type": "string"}, "gross": {"type": "string"}}},
        },
    },
    "EInvoice": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["invoice", "credit_note"]},
            "invoice_number": {"type": "string"},
            "status": {"type": "string", "enum": ["draft", "validated", "submitted", "accepted", "rejected", "cancelled"]},
            "lines": {"type": "array", "items": {"type": "object"}},
            "totals": {"type": "object", "properties": {"net": {"type": "string"}, "vat": {"type": "string"}, "gross": {"type": "string"}}},
            "errors": {"type": "object", "additionalProperties": {"type": "string"}},
            "irn": {"type": ["string", "null"]},
            "qr_payload": {"type": ["string", "null"]},
            "rejection_reason": {"type": ["string", "null"]},
            "mode": {"type": "string", "enum": ["sandbox", "production"]},
            "events": {"type": "array", "items": {"type": "object"}},
        },
    },
    "EInvoiceList": {"type": "object", "properties": {"items": {"type": "array", "items": _ref("EInvoice")}, "counts": {"type": "object"}, "mode": {"type": "string"}}},
    "Submission": {"type": "object", "properties": {"invoice": _ref("EInvoice"), "mode": {"type": "string"}, "replayed": {"type": "boolean"}}},
}

_ERROR_RESPONSES = {
    "401": "unauthorized",
    "403": "insufficient_scope",
    "404": "not_found",
    "409": "conflict",
    "422": "invalid_input",
    "429": "rate_limited",
}


def _operation(op: dict[str, Any]) -> dict[str, Any]:
    params: list[dict[str, Any]] = [
        {"name": n, "in": "path", "required": True, "schema": s} for n, s in (op.get("path_params") or {}).items()
    ]
    params += [
        {"name": n, "in": "query", "required": False, "schema": {k: v for k, v in s.items() if k != "description"}, "description": s.get("description", "")}
        for n, s in (op.get("query_params") or {}).items()
    ]
    params.append({"name": "X-Correlation-Id", "in": "header", "required": False, "schema": {"type": "string", "maxLength": 64}, "description": "Echoed back; generated if absent."})
    if op.get("idempotent"):
        params.append({"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string", "maxLength": 100}, "description": "Repeat a request safely: the same key and body return the stored response."})
    status = op.get("status", "200")
    ok: dict[str, Any] = {"description": "OK"}
    if op.get("response"):
        ok["content"] = {"application/json": {"schema": _ref(op["response"])}}
    else:
        ok["content"] = {"application/json": {"schema": {"type": "object"}}}
    out: dict[str, Any] = {
        "operationId": op["id"],
        "summary": op["summary"],
        "tags": [op["tag"]],
        "parameters": params,
        "responses": {status: ok},
    }
    if op.get("request"):
        out["requestBody"] = {"required": True, "content": {"application/json": {"schema": _ref(op["request"])}}}
    if op["scope"] is None:
        out["security"] = []
    else:
        out["security"] = [{"apiKey": []}]
        out["x-required-scope"] = op["scope"] or None
        for code, error in _ERROR_RESPONSES.items():
            out["responses"][code] = {"description": ERROR_CODES.get(error, error), "content": {"application/json": {"schema": _ref("Error")}}}
    return out


def document(mode: str) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for op in OPERATIONS:
        paths.setdefault(op["path"], {})[op["method"]] = _operation(op)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "tax.ng public API",
            "version": API_VERSION,
            "description": (
                "Calculators, rules parameters and e-invoices for Nigerian tax. Owned by Astound Innovation Hub. "
                f"This environment runs in {mode} mode: e-invoices are not sent to NRS. "
                "Authenticate with `Authorization: Bearer <API key>`. Errors use one shape (see Error) and every "
                "response carries X-Correlation-Id. Rate limits are per key (token bucket) with X-RateLimit-Limit, "
                "X-RateLimit-Remaining and Retry-After headers."
            ),
        },
        "servers": [{"url": "/", "description": f"{mode} environment"}],
        "tags": [{"name": t} for t in ("meta", "calculators", "rules", "einvoices")],
        "paths": paths,
        "components": {
            "securitySchemes": {"apiKey": {"type": "http", "scheme": "bearer", "bearerFormat": "tax.ng API key (tng_test_...)"}},
            "schemas": SCHEMAS,
        },
        "x-scopes": SCOPES,
        "x-error-codes": ERROR_CODES,
    }
