"""Wires the platform and every module together once at startup.

Modules live in ``taxng/modules/<name>/``. At startup each module package is
imported; if it defines ``init(services)`` that is called (to register
adapters, hooks or analytics events), and its ``routes`` submodule is imported
so its ``@route`` handlers register. After every module has started, each
module's optional ``post_init(services)`` runs for cross-module wiring.
See docs/MODULES.md.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .ai import Assistant
from .db import Database
from .legal import Document, Library, SearchIndex
from .platform.adapters import AdapterRegistry
from .platform.audit import AuditLog
from .platform.auth import AuthService
from .platform.files import FileStore
from .platform.identity import IdentityService, ProductionKyc, SandboxKyc
from .platform.notify import Notifier, ProductionMessaging, SandboxMessaging
from .rules import ParameterTree
from .store import Store

MODULES_PACKAGE = "taxng.modules"


@dataclass
class Services:
    tree: ParameterTree
    library: Library
    index: SearchIndex
    assistant: Assistant
    db: Database
    store: Store
    adapters: AdapterRegistry
    notifier: Notifier
    auth: AuthService
    audit: AuditLog
    identity: IdentityService
    files: FileStore
    secret: str
    demo_mode: bool
    rules_dir: Path
    content_dir: Path
    # Extension points filled by modules' init(): e.g. hooks["api_key"].
    hooks: dict[str, Callable[..., Any]] = field(default_factory=dict)
    # Per-module service objects, keyed by module name.
    modules: dict[str, Any] = field(default_factory=dict)


def build_index(library: Library) -> SearchIndex:
    docs = [
        Document(p.id, "provision", p.title, " ".join([p.instrument, p.summary, *p.keywords, p.tax]))
        for p in library.provisions.values()
    ]
    docs += [Document(g.id, "guide", g.title, " ".join([g.summary, *g.body])) for g in library.guides.values()]
    return SearchIndex(docs)


def module_names() -> list[str]:
    package = importlib.import_module(MODULES_PACKAGE)
    return sorted(m.name for m in pkgutil.iter_modules(package.__path__) if m.ispkg)


def build_services(
    *,
    rules_dir: Path = config.RULES_DIR,
    content_dir: Path = config.CONTENT_DIR,
    database: str = config.DATABASE,
    secret: str = config.SECRET,
    data_dir: Path = config.DATA_DIR,
    demo_mode: bool = config.DEMO_MODE,
) -> Services:
    tree = ParameterTree.from_directory(rules_dir / "parameters")
    library = Library.load(content_dir, tree)
    index = build_index(library)
    db = Database(database)
    db.migrate()

    adapters = AdapterRegistry()
    adapters.register(SandboxMessaging, ProductionMessaging)
    adapters.register(SandboxKyc, ProductionKyc)
    notifier = Notifier(db, adapters.get("messaging"))

    services = Services(
        tree=tree,
        library=library,
        index=index,
        assistant=Assistant(tree, library, index),
        db=db,
        store=Store(db, secret),
        adapters=adapters,
        notifier=notifier,
        auth=AuthService(db, notifier, secret, admin_emails=config.ADMIN_EMAILS),
        audit=AuditLog(db),
        identity=IdentityService(db, adapters.get("kyc"), secret),
        files=FileStore(db, data_dir / "files", secret),
        secret=secret,
        demo_mode=demo_mode,
        rules_dir=rules_dir,
        content_dir=content_dir,
    )

    # Core routes first, then every module (init -> routes), then post_init once
    # all modules exist, for cross-module wiring such as payment handlers.
    importlib.import_module("taxng.api.handlers")
    importlib.import_module("taxng.platform.routes")
    loaded = []
    for name in module_names():
        module = importlib.import_module(f"{MODULES_PACKAGE}.{name}")
        init = getattr(module, "init", None)
        if callable(init):
            init(services)
        importlib.import_module(f"{MODULES_PACKAGE}.{name}.routes")
        loaded.append(module)
    for module in loaded:
        post_init = getattr(module, "post_init", None)
        if callable(post_init):
            post_init(services)
    importlib.import_module("taxng.ai.account_routes")
    return services
