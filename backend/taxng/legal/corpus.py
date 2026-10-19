"""Legal library, reform guides and news, loaded from ``content/`` (LAW-01 to LAW-05).

In production these come from the headless CMS (ADR-05) and the ingestion
pipeline (Annex A7). The loader validates the same fields a reviewer relies on.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..rules import ParameterTree

_FIGURE = re.compile(r"₦|\d\s*%|\bper\s*cent\b", re.IGNORECASE)


class ContentError(ValueError):
    pass


@dataclass(frozen=True)
class Provision:
    id: str
    instrument: str
    section: str
    title: str
    tax: str
    effective_from: dt.date
    effective_to: dt.date | None
    summary: str
    keywords: tuple[str, ...]
    parameters: tuple[str, ...]
    review_status: str

    def in_force(self, on: dt.date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on < self.effective_to)


@dataclass(frozen=True)
class Guide:
    id: str
    title: str
    summary: str
    applies_from: dt.date
    calculator: str | None
    provisions: tuple[str, ...]
    parameters: tuple[str, ...]
    body: tuple[str, ...]
    translations: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsItem:
    id: str
    date: dt.date
    section: str
    headline: str
    standfirst: str
    source_name: str
    source_url: str
    sample: bool


def _date(value: Any) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def _load_all(content_dir: Path, name: str) -> list[dict[str, Any]]:
    """Core file plus any ``<name>.d/*.yaml`` additions, in file-name order."""
    items: list[dict[str, Any]] = list(yaml.safe_load((content_dir / f"{name}.yaml").read_text()) or [])
    extra_dir = content_dir / f"{name}.d"
    if extra_dir.is_dir():
        for path in sorted(extra_dir.glob("*.yaml")):
            items.extend(yaml.safe_load(path.read_text()) or [])
    return items


def _check_no_figures(where: str, text: str) -> None:
    """Content must not state figures; they come from the rules engine (CALC-07)."""
    if _FIGURE.search(text):
        raise ContentError(f"{where} states a figure; link a parameter instead")


@dataclass
class Library:
    provisions: dict[str, Provision]
    guides: dict[str, Guide]
    news: list[NewsItem]

    @classmethod
    def load(cls, content_dir: Path, tree: ParameterTree) -> "Library":
        provisions: dict[str, Provision] = {}
        for raw in _load_all(content_dir, "provisions"):
            p = Provision(
                id=raw["id"],
                instrument=raw["instrument"],
                section=raw["section"],
                title=raw["title"],
                tax=raw["tax"],
                effective_from=_date(raw["effective_from"]),
                effective_to=_date(raw["effective_to"]) if raw.get("effective_to") else None,
                summary=raw["summary"],
                keywords=tuple(str(k) for k in raw.get("keywords", [])),
                parameters=tuple(raw.get("parameters", [])),
                review_status=raw["review_status"],
            )
            if p.id in provisions:
                raise ContentError(f"Duplicate provision id {p.id}")
            _check_no_figures(f"provision {p.id}", p.summary)
            for name in p.parameters:
                if not tree.has(name):
                    raise ContentError(f"provision {p.id} links unknown parameter {name}")
            provisions[p.id] = p

        guides: dict[str, Guide] = {}
        for raw in _load_all(content_dir, "guides"):
            g = Guide(
                id=raw["id"],
                title=raw["title"],
                summary=raw["summary"],
                applies_from=_date(raw["applies_from"]),
                calculator=raw.get("calculator"),
                provisions=tuple(raw.get("provisions", [])),
                parameters=tuple(raw.get("parameters", [])),
                body=tuple(raw.get("body", [])),
                translations=raw.get("translations") or {},
            )
            for part in (g.summary, *g.body):
                _check_no_figures(f"guide {g.id}", part)
            for pid in g.provisions:
                if pid not in provisions:
                    raise ContentError(f"guide {g.id} cites unknown provision {pid}")
            guides[g.id] = g

        news = [
            NewsItem(
                id=raw["id"],
                date=_date(raw["date"]),
                section=raw["section"],
                headline=raw["headline"],
                standfirst=raw["standfirst"],
                source_name=raw["source_name"],
                source_url=raw["source_url"],
                sample=bool(raw.get("sample", False)),
            )
            for raw in _load_all(content_dir, "news")
        ]
        news.sort(key=lambda n: n.date, reverse=True)
        return cls(provisions, guides, news)
