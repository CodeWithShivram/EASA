"""Data access for support tickets. Reads are scoped to the tenant, and usually to the reporter."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.tickets import SupportTicket, TicketPriority, TicketStatus

# Attempts at taking the next ticket number when two writers race for it.
NUMBER_ATTEMPTS = 3


class TicketRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_own(
        self, tenant_id: uuid.UUID, reporter_id: uuid.UUID, number: int
    ) -> SupportTicket | None:
        return self._session.scalars(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.reporter_id == reporter_id,
                SupportTicket.number == number,
            )
        ).one_or_none()

    def get_in_tenant(self, tenant_id: uuid.UUID, number: int) -> SupportTicket | None:
        """Any reporter's ticket; only for callers allowed to read all tickets."""
        return self._session.scalars(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id, SupportTicket.number == number
            )
        ).one_or_none()

    def create(
        self,
        tenant_id: uuid.UUID,
        reporter_id: uuid.UUID,
        *,
        title: str,
        description: str,
        status: TicketStatus,
        priority: TicketPriority,
    ) -> SupportTicket:
        """Insert with the next free number in the tenant and commit."""
        for attempt in range(1, NUMBER_ATTEMPTS + 1):
            last = self._session.scalar(
                select(func.max(SupportTicket.number)).where(SupportTicket.tenant_id == tenant_id)
            )
            ticket = SupportTicket(
                tenant_id=tenant_id,
                reporter_id=reporter_id,
                number=(last or 0) + 1,
                title=title,
                description=description,
                status=status,
                priority=priority,
            )
            self._session.add(ticket)
            try:
                self._session.commit()
            except IntegrityError:
                self._session.rollback()
                if attempt == NUMBER_ATTEMPTS:
                    raise
                continue
            return ticket
        raise AssertionError("unreachable")  # pragma: no cover

    def count(self, tenant_id: uuid.UUID) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(SupportTicket)
                .where(SupportTicket.tenant_id == tenant_id)
            )
            or 0
        )
