from app.services.health import DependencyUnavailableError, HealthService


class StubProbe:
    """Test double for the database probe."""

    def __init__(self, *, available: bool) -> None:
        self.available = available
        self.calls = 0

    def ping(self) -> None:
        self.calls += 1
        if not self.available:
            raise DependencyUnavailableError("database")


def test_ready_when_database_is_reachable() -> None:
    probe = StubProbe(available=True)

    report = HealthService(database=probe).check_readiness()

    assert report.database == "ok"
    assert report.is_ready
    assert probe.calls == 1


def test_not_ready_when_database_is_unreachable() -> None:
    report = HealthService(database=StubProbe(available=False)).check_readiness()

    assert report.database == "unavailable"
    assert not report.is_ready
