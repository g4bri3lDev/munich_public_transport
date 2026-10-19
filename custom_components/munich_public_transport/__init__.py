"""Munich Public Transport integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import Station, StationDirectionOption
from munich_transport.transport import AiohttpTransport

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_PLACE,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    PLATFORMS,
    SUBENTRY_TYPE_STATION,
)
from .coordinator import (
    MunichTransportConfigEntry,
    MunichTransportData,
    MunichTransportDepartureCoordinator,
    MunichTransportMessagesCoordinator,
    StationData,
)
from .migration import async_migrate_integration, async_migrate_station_entry
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and merge entries from earlier versions."""

    async_setup_services(hass)
    await async_migrate_integration(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry async_setup could not merge.

    That happens when MVG was unreachable while converting a 0.0.7 entry;
    the conversion raises ConfigEntryNotReady, so Home Assistant retries.
    """

    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version == CONFIG_ENTRY_VERSION:
        return True
    return await async_migrate_station_entry(hass, entry)


async def async_setup_entry(
    hass: HomeAssistant, entry: MunichTransportConfigEntry
) -> bool:
    """Set up the MVG entry and one departure coordinator per station."""

    client = MunichTransportClient(
        AiohttpTransport(session=async_get_clientsession(hass))
    )

    # Service messages are optional; stations work without them.
    messages_coordinator = MunichTransportMessagesCoordinator(hass, entry, client)
    await messages_coordinator.async_refresh()

    device_registry = dr.async_get(hass)
    stations: dict[str, StationData] = {}
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_STATION):
        global_id = subentry.data[CONF_STATION_GLOBAL_ID]
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, global_id), entry.entry_id
        )
        if device is not None and device.disabled:
            continue

        coordinator = MunichTransportDepartureCoordinator(
            hass, entry, client, global_id, subentry.data[CONF_NAME]
        )
        await coordinator.async_config_entry_first_refresh()
        stations[subentry.subentry_id] = StationData(
            subentry_id=subentry.subentry_id,
            global_id=global_id,
            name=subentry.data[CONF_NAME],
            coordinator=coordinator,
            directions=await _load_directions(client, subentry.data),
        )

    entry.runtime_data = MunichTransportData(
        client=client,
        messages_coordinator=messages_coordinator,
        stations=stations,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MunichTransportConfigEntry
) -> bool:
    """Unload the MVG entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: MunichTransportConfigEntry
) -> None:
    """Reload when stations are added, reconfigured or removed."""

    await hass.config_entries.async_reload(entry.entry_id)


async def _load_directions(
    client: MunichTransportClient,
    data: Mapping[str, Any],
) -> tuple[StationDirectionOption, ...]:
    """Resolve the station's selected direction ids against the catalog.

    Without the catalog the ids are still enough to match departures; only
    the terminus names in entity names are missing until the next reload.
    """

    selected_ids = sorted(set(data.get(CONF_DIRECTION_OPTION_IDS, ())))
    if not selected_ids:
        return ()

    try:
        options = await client.direction_options_for_station(
            Station(
                global_id=data[CONF_STATION_GLOBAL_ID],
                name=data[CONF_NAME],
                place=data.get(CONF_STATION_PLACE),
                latitude=0.0,
                longitude=0.0,
                abbreviation=data.get(CONF_STATION_ABBREVIATION),
            )
        )
    except MunichTransportError:
        options = []

    options_by_id = {option.id: option for option in options}
    directions: list[StationDirectionOption] = []
    for option_id in selected_ids:
        if option_id in options_by_id:
            directions.append(options_by_id[option_id])
            continue
        try:
            directions.append(StationDirectionOption.from_id(option_id))
        except ValueError:
            _LOGGER.warning("Ignoring unknown MVG direction %s", option_id)
    return tuple(directions)
