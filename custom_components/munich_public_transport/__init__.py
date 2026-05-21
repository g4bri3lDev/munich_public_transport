"""Munich Public Transport integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import MunichTransportError
from munich_transport.transport import AiohttpTransport

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_NAME,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import MunichTransportDepartureCoordinator
from .models import (
    DirectionSelection,
    direction_selection_from_option,
    fallback_direction_selection,
)


@dataclass(frozen=True, slots=True)
class MunichTransportRuntimeData:
    """Runtime objects shared by the integration platforms."""

    client: MunichTransportClient
    coordinator: MunichTransportDepartureCoordinator
    direction_selections: tuple[DirectionSelection, ...]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Munich Public Transport from a config entry."""

    session = async_get_clientsession(hass)
    client = MunichTransportClient(AiohttpTransport(session=session))

    direction_selections = await _load_direction_selections(client, entry)
    coordinator = MunichTransportDepartureCoordinator(
        hass=hass,
        config_entry=entry,
        client=client,
        station_global_id=entry.data[CONF_STATION_GLOBAL_ID],
        station_name=entry.data[CONF_NAME],
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = MunichTransportRuntimeData(
        client=client,
        coordinator=coordinator,
        direction_selections=direction_selections,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def _load_direction_selections(
    client: MunichTransportClient,
    entry: ConfigEntry,
) -> tuple[DirectionSelection, ...]:
    selected_ids = set(entry.options.get(CONF_DIRECTION_OPTION_IDS, ()))
    if not selected_ids:
        return ()

    options_by_id = {}
    abbreviation = entry.data.get(CONF_STATION_ABBREVIATION)

    try:
        if abbreviation:
            options = await client.station_direction_options_by_abbreviation(
                abbreviation,
            )
        else:
            options = await client.station_direction_options(
                entry.data[CONF_STATION_GLOBAL_ID],
            )
    except MunichTransportError:
        options = ()

    options_by_id = {option.id: option for option in options}
    return tuple(
        direction_selection_from_option(options_by_id[option_id])
        if option_id in options_by_id
        else fallback_direction_selection(option_id)
        for option_id in sorted(selected_ids)
    )
