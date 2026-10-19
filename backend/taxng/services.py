"""Wires the domain modules together once at startup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config
from .ai import Assistant
from .legal import Document, Library, SearchIndex
from .rules import ParameterTree
from .store import Store


@dataclass
class Services:
    tree: ParameterTree
    library: Library
    index: SearchIndex
    assistant: Assistant
    store: Store


def build_index(library: Library) -> SearchIndex:
    docs = [
        Document(p.id, "provision", p.title, " ".join([p.instrument, p.summary, *p.keywords, p.tax]))
        for p in library.provisions.values()
    ]
    docs += [
        Document(g.id, "guide", g.title, " ".join([g.summary, *g.body]))
        for g in library.guides.values()
    ]
    return SearchIndex(docs)


def build_services(
    *,
    rules_dir: Path = config.RULES_DIR,
    content_dir: Path = config.CONTENT_DIR,
    database: str = config.DATABASE,
    secret: str = config.SECRET,
) -> Services:
    tree = ParameterTree.from_directory(rules_dir / "parameters")
    library = Library.load(content_dir, tree)
    index = build_index(library)
    return Services(
        tree=tree,
        library=library,
        index=index,
        assistant=Assistant(tree, library, index),
        store=Store(database, secret),
    )
