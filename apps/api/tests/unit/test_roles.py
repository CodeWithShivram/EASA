import pytest

from app.core.roles import EMPLOYEE_LEVELS, Role, can_assign_level, visible_levels


@pytest.mark.parametrize(
    ("role", "levels"),
    [
        ("employee", ("employee",)),
        ("manager", ("employee", "manager")),
        ("administrator", ("employee", "manager", "administrator")),
        (None, ("employee",)),  # internal jobs without a role see the least
        ("owner", ("employee",)),  # an unknown role never sees more
    ],
)
def test_visible_levels(role: str | None, levels: tuple[str, ...]) -> None:
    assert visible_levels(role) == levels


def test_the_default_level_is_the_most_restrictive() -> None:
    assert EMPLOYEE_LEVELS == ("employee",)


@pytest.mark.parametrize(
    ("role", "level", "allowed"),
    [
        ("manager", Role.EMPLOYEE, True),
        ("manager", Role.MANAGER, True),
        ("manager", Role.ADMINISTRATOR, False),
        ("administrator", Role.ADMINISTRATOR, True),
        ("employee", Role.MANAGER, False),
        (None, Role.MANAGER, False),
    ],
)
def test_nobody_restricts_a_document_above_their_own_role(
    role: str | None, level: Role, allowed: bool
) -> None:
    assert can_assign_level(role, level) is allowed
