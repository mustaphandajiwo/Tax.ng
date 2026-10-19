"""Advisory module facade, published as ``services.modules["advisory"]``.

Holds the two domain services (:class:`~.advisers.Advisers` and
:class:`~.bookings.Bookings`) and the per-instance billing wiring state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from .advisers import Advisers
from .bookings import Bookings

if TYPE_CHECKING:
    from ...services import Services


class AdvisoryService:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.advisers = Advisers(services)
        self.bookings = Bookings(services, self.advisers)
        self.payment_handler_registered = False

    def adviser_for(self, user_id: str) -> dict[str, Any]:
        """The caller's adviser listing; advisers act only on their own requests and engagements."""
        row = self.advisers.for_user(user_id)
        if not row:
            raise NotFound("You do not have an adviser listing")
        return row
