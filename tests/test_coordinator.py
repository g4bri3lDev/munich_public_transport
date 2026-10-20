"""Test the Munich Public Transport coordinators."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from munich_transport.exceptions import ApiError, MunichTransportError, TransportError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.munich_public_transport.coordinator import (
    _sanitize_retry_after,
    _update_failed,
)

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
