"""Test the Munich Public Transport coordinators."""

from typing import Any
from unittest.mock import MagicMock, call

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from munich_transport.exceptions import ApiError, MunichTransportError, TransportError
from munich_transport.models import Departure
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.munich_public_transport.const import CONF_LOOK_AHEAD
from custom_components.munich_public_transport.coordinator import (
    _sanitize_retry_after,
    _update_failed,
)

from . import STATION, STATION_DATA, SUBENTRY_ID, make_departure

DISRUPTIONS = "sensor.munchner_freiheit_disruptions"


@pytest.fixture
def departures_error() -> MunichTransportError:
    """Return the error the departure request fails with; parametrize it."""
    return TransportError("timeout")


@pytest.fixture
def departures_failing(
    mock_client: MagicMock, departures_error: MunichTransportError
) -> None:
    """Make every departure request fail."""
    mock_client.departures.side_effect = departures_error


@pytest.mark.usefixtures("departures_failing")
@pytest.mark.parametrize(
    "departures_error",
    [
        ApiError(503, "Service Unavailable", retry_after=30),
        ApiError(404, "Not Found"),
        TransportError("timeout"),
    ],
)
async def test_first_refresh_failure_retries_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a failed first departure fetch defers setup for every error kind."""
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.fixture
def messages_rate_limited(mock_client: MagicMock) -> None:
    """Make the service message request hit MVG's rate limit."""
    mock_client.messages.side_effect = ApiError(429, "Too Many Requests")


@pytest.mark.usefixtures("messages_rate_limited")
async def test_messages_rate_limit_keeps_stations_running(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test rate-limited messages only affect the disruption entities."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert hass.states.get(DISRUPTIONS).state == "unavailable"


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(None, 60.0), (0.2, 1.0), (30.0, 30.0), (3600.0, 900.0)],
)
def test_sanitize_retry_after(retry_after: float | None, expected: float) -> None:
    """Test Retry-After values are defaulted and clamped."""
    assert _sanitize_retry_after(retry_after) == expected


@pytest.mark.parametrize(
    ("error", "translation_key", "retry_after"),
    [
        (ApiError(429, "Too Many", retry_after=120), "temporarily_unavailable", 120.0),
        (ApiError(503, "Unavailable"), "temporarily_unavailable", 60.0),
        (ApiError(404, "Not Found"), "api_error", None),
        (TransportError("timeout"), "cannot_connect", None),
    ],
)
def test_update_failed(
    error: MunichTransportError, translation_key: str, retry_after: float | None
) -> None:
    """Test client errors become translated failures, deferring polls on 429/5xx."""
    failure = _update_failed(error)

    assert isinstance(failure, UpdateFailed)
    assert failure.translation_key == translation_key
    assert failure.retry_after == retry_after


type Minute = int | tuple[int, int]


def _departure(minute: Minute) -> Departure:
    """Build a departure from its planned minute, or (planned minute, delay)."""
    if isinstance(minute, int):
        return make_departure(minute)
    planned, delay = minute
    return make_departure(planned, delay=delay)


def _pages(*pages: list[Minute]) -> Any:
    """Answer departure requests with one page per offset, keyed by the offset.

    Each page lists its departures as minutes from now.
    """
    by_offset = {page[0]: page[1:] for page in pages}

    async def departures(global_id: str, *, offset_minutes: int = 0) -> list:
        return [_departure(minute) for minute in by_offset.get(offset_minutes, [])]

    return departures


def _station_departures(entry: MockConfigEntry) -> list[Departure]:
    return entry.runtime_data.stations[SUBENTRY_ID].coordinator.data


@pytest.fixture
def look_ahead_pages() -> list[list[Minute]]:
    """Return the pages MVG answers, each as [offset, *minutes]; parametrize."""
    return [[0, 3, 8]]


@pytest.fixture
def paged_client(mock_client: MagicMock, look_ahead_pages: list[list[Minute]]) -> None:
    """Make departure requests answer from look_ahead_pages."""
    mock_client.departures.side_effect = _pages(*look_ahead_pages)


async def test_no_look_ahead_makes_one_request(
    mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test a station without a look-ahead keeps to MVG's first response."""
    mock_client.departures.assert_awaited_once_with(STATION.global_id)


@pytest.mark.usefixtures("paged_client")
@pytest.mark.parametrize("station_data", [{**STATION_DATA, CONF_LOOK_AHEAD: 30}])
@pytest.mark.parametrize(
    ("look_ahead_pages", "offsets", "minutes"),
    [
        # Requests continue from the last planned departure, and the overlap
        # at that minute is merged.
        ([[0, 3, 8, 12], [12, 12, 20, 34]], [12], [3, 8, 12, 20, 34]),
        # Covered by the first response.
        ([[0, 3, 30, 31]], [], [3, 30, 31]),
        # A departure past an hour-long gap does not count as covered.
        ([[0, 3, 12, 600], [12, 12, 40]], [12], [3, 12, 600, 40]),
        # MVG cuts a response by planned time, so a delayed departure with a
        # late real time does not show how far it reaches.
        (
            [[0, 3, 8, (9, 30)], [9, 12, 20, 34]],
            [9],
            [3, 8, (9, 30), 12, 20, 34],
        ),
        # A response that reaches no further ends the look-ahead.
        ([[0, 3, 12], [12, 12]], [12], [3, 12]),
        # So does an empty one.
        ([[0, 3, 12]], [12], [3, 12]),
    ],
)
async def test_look_ahead_requests(
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
    offsets: list[int],
    minutes: list[Minute],
) -> None:
    """Test a look-ahead requests later departures until it is covered."""
    assert mock_client.departures.await_args_list == [
        call(STATION.global_id),
        *(call(STATION.global_id, offset_minutes=offset) for offset in offsets),
    ]
    assert _station_departures(init_integration) == [
        _departure(minute) for minute in minutes
    ]


@pytest.mark.usefixtures("paged_client")
@pytest.mark.parametrize("station_data", [{**STATION_DATA, CONF_LOOK_AHEAD: 90}])
@pytest.mark.parametrize(
    "look_ahead_pages",
    [[[0, 5], [5, 10], [10, 15], [15, 20], [20, 25], [25, 30], [30, 35]]],
)
async def test_look_ahead_request_limit(
    mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test a look-ahead takes at most six requests per update."""
    assert mock_client.departures.await_count == 6
    assert len(_station_departures(init_integration)) == 6


@pytest.mark.parametrize("station_data", [{**STATION_DATA, CONF_LOOK_AHEAD: 30}])
async def test_look_ahead_failure_fails_update(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Test a failed later request fails the update instead of keeping half."""
    mock_client.departures.side_effect = [
        [make_departure(3)],
        ApiError(503, "Service Unavailable"),
    ]
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
