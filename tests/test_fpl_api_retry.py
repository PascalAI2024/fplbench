"""_get_json retry behaviour. A single 503 from the FPL API killed the whole
2026-09-04 pre-deadline board build, so all four paths are pinned here."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.track_team import MAX_ATTEMPTS, _get_json

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.reason = "Service Unavailable" if status_code == 503 else "OK"
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} {self.reason}", response=self)


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.track_team.time.sleep", lambda _seconds: None)


def _stub(monkeypatch: pytest.MonkeyPatch, responses: list) -> list[int]:
    calls: list[int] = []

    def fake_get(url: str, **_kwargs: object):
        calls.append(1)
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("scripts.track_team.requests.get", fake_get)
    return calls


def test_recovers_after_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact 2026-09-04 failure: 503s that would have succeeded on retry."""
    calls = _stub(
        monkeypatch,
        [_Response(503), _Response(503), _Response(200, {"events": [{"id": 1}]})],
    )
    assert _get_json(URL) == {"events": [{"id": 1}]}
    assert len(calls) == 3


def test_retries_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub(
        monkeypatch,
        [requests.ConnectionError("reset"), _Response(200, {"ok": True})],
    )
    assert _get_json(URL) == {"ok": True}
    assert len(calls) == 2


def test_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrying must not mask a sustained outage — it still has to raise."""
    calls = _stub(monkeypatch, [_Response(503)] * MAX_ATTEMPTS)
    with pytest.raises(requests.HTTPError):
        _get_json(URL)
    assert len(calls) == MAX_ATTEMPTS


def test_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 is not transient; burning four attempts on it just wastes time."""
    calls = _stub(monkeypatch, [_Response(404)])
    with pytest.raises(requests.HTTPError):
        _get_json(URL)
    assert len(calls) == 1
