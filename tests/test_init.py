"""Test the Munich Public Transport integration setup and unload."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a v2 entry sets up its sensors and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    unique_ids = {
        entry.unique_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }
    entry_id = mock_config_entry.entry_id
    assert unique_ids == {
        f"{entry_id}_next_departure",
        f"{entry_id}_all_departures",
        f"{entry_id}_messages",
        f"{entry_id}_SUBWAY:U6:H",
        f"{entry_id}_SUBWAY:U6:R",
    }
    mock_client.departures.assert_awaited_with("de:09162:500")

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
