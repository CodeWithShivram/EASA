from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import sqlite

from app.db.types import UtcDateTime, utc_now

DIALECT = sqlite.dialect()


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_bind_converts_aware_values_to_utc() -> None:
    plus_five_thirty = timezone(timedelta(hours=5, minutes=30))
    value = datetime(2026, 11, 14, 12, 0, tzinfo=plus_five_thirty)

    bound = UtcDateTime().process_bind_param(value, DIALECT)

    assert bound == datetime(2026, 11, 14, 6, 30, tzinfo=UTC)
    assert bound is not None
    assert bound.tzinfo == UTC


def test_bind_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="naive"):
        UtcDateTime().process_bind_param(datetime(2026, 11, 14, 12, 0), DIALECT)


def test_naive_database_values_are_returned_as_utc() -> None:
    result = UtcDateTime().process_result_value(datetime(2026, 11, 14, 12, 0), DIALECT)

    assert result == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def test_none_passes_through() -> None:
    assert UtcDateTime().process_bind_param(None, DIALECT) is None
    assert UtcDateTime().process_result_value(None, DIALECT) is None
