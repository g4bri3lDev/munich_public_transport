"""Test the Munich Public Transport integration setup and unload."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from munich_transport.exceptions import MunichTransportError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from . import STATION, SUBENTRY_ID


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
    # One per station, three per direction, one per line.
    assert len(entities) == 1 + 2 * 3 + 1
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
