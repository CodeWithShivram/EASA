"""Synthetic support tickets for development and tests (``python -m app.cli seed-tickets``)."""

import uuid

from sqlalchemy.orm import Session

from app.db.tickets import TicketPriority, TicketStatus
from app.repositories.tickets import TicketRepository

# A second synthetic user in the same tenant, so isolation between reporters
# can be seen: the development user must not be able to read these tickets.
OTHER_REPORTER = uuid.UUID("00000000-0000-4000-8000-0000000000c3")

# (title, description, status, priority) - all fictional.
_OWN = [
    (
        "Laptop will not connect to VPN",
        "Since this morning the VPN client shows error 809 when connecting from home.",
        TicketStatus.OPEN,
        TicketPriority.HIGH,
    ),
    (
        "Request a second monitor",
        "I would like a second monitor for my home office setup.",
        TicketStatus.IN_PROGRESS,
        TicketPriority.LOW,
    ),
    (
        "Expense claim stuck in approval",
        "My March travel expense claim has been pending for two weeks.",
        TicketStatus.OPEN,
        TicketPriority.NORMAL,
    ),
    (
        "Password manager access",
        "I need access to the shared team vault in Vaultline.",
        TicketStatus.RESOLVED,
        TicketPriority.NORMAL,
    ),
    (
        "Desk booking app crashes",
        "The desk booking app closes when I select the third floor.",
        TicketStatus.CLOSED,
        TicketPriority.LOW,
    ),
]
_OTHER = [
    (
        "Salary review question",
        "Confidential question about my salary band for the review.",
        TicketStatus.OPEN,
        TicketPriority.NORMAL,
    ),
    (
        "Parking permit renewal",
        "My parking permit expires next week.",
        TicketStatus.OPEN,
        TicketPriority.LOW,
    ),
]


def seed_tickets(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Create the synthetic tickets once; returns how many were created (0 if seeded)."""
    repository = TicketRepository(session)
    if repository.count(tenant_id):
        return 0
    created = 0
    for reporter, rows in ((user_id, _OWN), (OTHER_REPORTER, _OTHER)):
        for title, description, status, priority in rows:
            repository.create(
                tenant_id,
                reporter,
                title=title,
                description=description,
                status=status,
                priority=priority,
            )
            created += 1
    return created
