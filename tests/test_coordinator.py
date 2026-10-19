"""Test the Munich Public Transport coordinators."""

from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from munich_transport.exceptions import ApiError, MunichTransportError, TransportError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.munich_public_transport.const import (
    DEFAULT_MESSAGES_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)
from custom_components.munich_public_transport.coordinator import (
    _sanitize_retry_after,
    _transient_update_failed,
)

NEXT_DEPARTURE = "sensor.munchner_freiheit_next_departure"
MESSAGES = "sensor.munchner_freiheit_messages"


@pytest.mark.parametrize(
    "error",
    [
        ApiError(503, "Service Unavailable"),
        ApiError(404, "Not Found"),
        TransportError("timeout"),
    ],
)
async def test_first_refresh_failure_retries_setup(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    error: MunichTransportError,
) -> None:
    """Test a failed first departure fetch defers setup."""
    mock_client.departures.side_effect = error
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_departures_unavailable_and_recover(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test departure sensors go unavailable on errors and come back."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    departures = mock_client.departures.return_value

    mock_client.departures.side_effect = TransportError("timeout")
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(NEXT_DEPARTURE).state == STATE_UNAVAILABLE

    mock_client.departures.side_effect = None
    mock_client.departures.return_value = departures
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(NEXT_DEPARTURE).state != STATE_UNAVAILABLE


async def test_messages_failure_does_not_block_setup(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test service messages are optional for setting up a station."""
    mock_client.messages.side_effect = ApiError(503, "Service Unavailable")
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(NEXT_DEPARTURE).state != STATE_UNAVAILABLE
    assert hass.states.get(MESSAGES).state == STATE_UNAVAILABLE

    mock_client.messages.side_effect = None
    freezer.tick(DEFAULT_MESSAGES_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(MESSAGES).state == "0"


async def test_messages_coordinator_shared_between_entries(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test all stations share one messages fetch, released with the last one."""
    other = MockConfigEntry(
        domain=mock_config_entry.domain,
        version=2,
        unique_id="de:09162:1",
        data={**mock_config_entry.data, "station_global_id": "de:09162:1"},
        options=mock_config_entry.options,
    )
    for entry in (mock_config_entry, other):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert mock_client.messages.await_count == 1

    for entry in (mock_config_entry, other):
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.domain not in hass.data


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(None, 60.0), (0.2, 1.0), (30.0, 30.0), (3600.0, 900.0)],
)
def test_sanitize_retry_after(retry_after: float | None, expected: float) -> None:
    """Test Retry-After values are defaulted and clamped."""
    assert _sanitize_retry_after(retry_after) == expected


def test_transient_update_failed_carries_retry_after() -> None:
    """Test rate limiting is passed to the coordinator as a retry delay."""
    failure = _transient_update_failed(ApiError(429, "Too Many", retry_after=120))

    assert isinstance(failure, UpdateFailed)
    assert failure.retry_after == 120.0
