"""Publishing module: contributor portal, editorial workflow, sponsored publishing,
display advertising and newsletter editions (PRD sections 6 and 7, Annex A8, Annex B).

Contract (``services.modules["publishing"]``):

* ``newsletter_items(limit=10) -> list[dict]``: recent published articles as
  cards, each carrying ``sponsored``, ``label`` and ``sponsor``.
* ``labels_for(article_id) -> dict``: the label set for one article.
* ``audience_status() -> {subscribers, threshold, open}`` (SPON-04).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...services import Services


class PublishingModule:
    def __init__(self, services: Services) -> None:
        self._services = services

    def newsletter_items(self, limit: int = 10) -> list[dict[str, Any]]:
        from .newsletter import newsletter_items

        return newsletter_items(self._services, limit)

    def labels_for(self, article_id: str) -> dict[str, Any]:
        from .service import get_article, labels

        return labels(self._services, get_article(self._services, article_id))

    def audience_status(self) -> dict[str, Any]:
        from .commerce import audience_status

        return audience_status(self._services)


def init(services: Services) -> None:
    from .commerce import ensure_payment_handlers

    services.modules["publishing"] = PublishingModule(services)
    # Billing may be absent; checkout retries registration and degrades if so.
    ensure_payment_handlers(services)
