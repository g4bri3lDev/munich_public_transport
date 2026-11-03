"""Test the Munich Public Transport integration setup and unload."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from munich_transport.exceptions import MunichTransportError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import LEGACY_STATION_DATA, STATION, STATION_DATA, SUBENTRY_ID


async def test_setup_and_unload(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
    station_device: dr.DeviceEntry,
) -> None:
    """Test the entry sets up a station device with its entities."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert station_device.config_subentry_id == SUBENTRY_ID
    entities = er.async_entries_for_config_entry(
        entity_registry, init_integration.entry_id
    )
    assert {entity.config_subentry_id for entity in entities} == {SUBENTRY_ID}
    # One per station, two per direction, one per line.
    assert len(entities) == 1 + 2 * 2 + 1
    mock_client.departures.assert_awaited_with(STATION.global_id)

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_mvg_is_down(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a failed first departure fetch defers setup."""
    mock_client.departures.side_effect = MunichTransportError("boom")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_disabled_station_is_not_polled(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    mock_client: MagicMock,
    init_integration: MockConfigEntry,
    station_device: dr.DeviceEntry,
) -> None:
    """Test a station whose device is disabled gets no coordinator."""
    device_registry.async_update_device(
        station_device.id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    mock_client.departures.reset_mock()

    assert init_integration.runtime_data.stations == {}
    mock_client.departures.assert_not_awaited()


async def test_stored_directions_need_no_lookup(
    mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test stored directions are used without asking MVG for them."""
    assert init_integration.state is ConfigEntryState.LOADED
    mock_client.direction_options_for_station.assert_not_called()


@pytest.mark.parametrize("station_data", [LEGACY_STATION_DATA])
async def test_directions_saved_as_ids_are_stored_once(
    mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test directions saved as ids only are looked up once and stored.

    Storing them must not reload the entry, which would set it up twice.
    """
    assert init_integration.state is ConfigEntryState.LOADED
    assert dict(init_integration.subentries[SUBENTRY_ID].data) == STATION_DATA
    mock_client.direction_options_for_station.assert_awaited_once()
    mock_client.departures.assert_awaited_once()


@pytest.mark.parametrize(
    "station_data",
    [
        {
            **LEGACY_STATION_DATA,
            "direction_options": [{"id": "SUBWAY:U6:H"}],
        }
    ],
)
async def test_invalid_stored_directions_are_looked_up(
    mock_client: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test unreadable stored directions are replaced by looked-up ones."""
    assert dict(init_integration.subentries[SUBENTRY_ID].data) == STATION_DATA
