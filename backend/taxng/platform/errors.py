"""Error types every module raises; the router maps them to HTTP responses."""

from __future__ import annotations


class Invalid(ValueError):
    """Bad input for one field. Message format: ``"field: what is wrong"`` (HTTP 422)."""


class Conflict(RuntimeError):
    """The request clashes with current state, e.g. approving an unsubmitted return (HTTP 409)."""
