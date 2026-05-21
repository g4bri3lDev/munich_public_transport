"""Munich Public Transport integration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import Station, StationDirectionOption
from munich_transport.transport import AiohttpTransport

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_NAME,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_PLACE,
    DOMAIN,
    OLD_CONF_DIRECTIONS,
    OLD_CONF_LINES,
    OLD_CONF_STATION_ID,
    OLD_CONF_STATION_NAME,
    PLATFORMS,
)
from .coordinator import MunichTransportDepartureCoordinator
from .models import (
    DirectionSelection,
    direction_selection_from_option,
    fallback_direction_selection,
)

_LOGGER = logging.getLogger(__name__)

_DIRECTION_SUFFIX_TOKENS = {
    "bahnhof",
    "bf",
    "bhf",
    "hbf",
    "hauptbahnhof",
}


@dataclass(frozen=True, slots=True)
class MunichTransportRuntimeData:
    """Runtime objects shared by the integration platforms."""

    client: MunichTransportClient
    coordinator: MunichTransportDepartureCoordinator
    direction_selections: tuple[DirectionSelection, ...]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy config entries to the rewrite schema."""

    if CONF_STATION_GLOBAL_ID in entry.data:
        if entry.version != 2:
            hass.config_entries.async_update_entry(entry, version=2)
        return True

    old_station_id = entry.data.get(OLD_CONF_STATION_ID)
    if not isinstance(old_station_id, str):
        _LOGGER.error("Cannot migrate legacy MVG entry without station_id")
        return False

    session = async_get_clientsession(hass)
    client = MunichTransportClient(AiohttpTransport(session=session))

    try:
        station = await client.station(old_station_id)
        direction_options = await _station_direction_options(client, station)
    except MunichTransportError as err:
        _LOGGER.error("Cannot migrate legacy MVG entry: %s", err)
        return False

    migrated_direction_ids = _migrate_direction_option_ids(
        direction_options,
        lines=_string_list(
            entry.options.get(OLD_CONF_LINES, entry.data.get(OLD_CONF_LINES, ())),
        ),
        directions=_string_list(
            entry.options.get(
                OLD_CONF_DIRECTIONS,
                entry.data.get(OLD_CONF_DIRECTIONS, ()),
            ),
        ),
    )

    await _migrate_legacy_registries(
        hass,
        entry,
        old_station_name=str(entry.data.get(OLD_CONF_STATION_NAME, old_station_id)),
        station=station,
        direction_options=direction_options,
    )

    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_NAME: station.name
            or entry.data.get(OLD_CONF_STATION_NAME, old_station_id),
            CONF_STATION_GLOBAL_ID: station.global_id,
            CONF_STATION_ABBREVIATION: station.abbreviation,
            CONF_STATION_PLACE: station.place,
        },
        options={CONF_DIRECTION_OPTION_IDS: migrated_direction_ids},
        title=station.name or entry.title,
        unique_id=station.global_id,
        version=2,
    )
    return True


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


async def _station_direction_options(
    client: MunichTransportClient,
    station: Station,
) -> list[StationDirectionOption]:
    if station.abbreviation:
        return await client.station_direction_options_by_abbreviation(
            station.abbreviation,
        )
    return await client.station_direction_options(station.global_id)


async def _migrate_legacy_registries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    old_station_name: str,
    station: Station,
    direction_options: list[StationDirectionOption],
) -> None:
    device_registry = dr.async_get(hass)
    old_device = device_registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_{old_station_name}")},
    )
    new_device = device_registry.async_get_device(
        identifiers={(DOMAIN, station.global_id)},
    )
    if old_device is not None and new_device is None:
        device_registry.async_update_device(
            old_device.id,
            new_identifiers={(DOMAIN, station.global_id)},
            name=station.name or old_station_name,
        )

    entity_registry = er.async_get(hass)
    unique_id_map = _legacy_entity_unique_id_map(
        entry,
        old_station_name=old_station_name,
        direction_options=direction_options,
    )
    removed_unique_ids = {
        f"{entry.entry_id}_{old_station_name}_messages",
    }

    @callback
    def migrate_entity(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        if entity_entry.unique_id in removed_unique_ids:
            entity_registry.async_remove(entity_entry.entity_id)
            return None

        new_unique_id = unique_id_map.get(entity_entry.unique_id)
        if new_unique_id is None:
            return None

        existing_entity_id = entity_registry.async_get_entity_id(
            entity_entry.domain,
            DOMAIN,
            new_unique_id,
        )
        if (
            existing_entity_id is not None
            and existing_entity_id != entity_entry.entity_id
        ):
            entity_registry.async_remove(entity_entry.entity_id)
            return None

        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, migrate_entity)


def _legacy_entity_unique_id_map(
    entry: ConfigEntry,
    *,
    old_station_name: str,
    direction_options: list[StationDirectionOption],
) -> dict[str, str]:
    unique_id_map = {
        f"{entry.entry_id}_{old_station_name}_next_departure": (
            f"{entry.entry_id}_next_departure"
        ),
        f"{entry.entry_id}_{old_station_name}_all_departures": (
            f"{entry.entry_id}_all_departures"
        ),
    }

    for option in direction_options:
        new_unique_id = f"{entry.entry_id}_{option.id}"
        for direction in (*option.directions, *option.raw_directions):
            for variant in _legacy_direction_variants(direction):
                unique_id_map[
                    f"{entry.entry_id}_{old_station_name}_{option.line_label}_{variant}"
                ] = new_unique_id

    return unique_id_map


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


def _migrate_direction_option_ids(
    options: list[StationDirectionOption],
    *,
    lines: list[str],
    directions: list[str],
) -> list[str]:
    if not lines or not directions:
        return []

    selected_lines = set(lines)
    selected_directions = {
        _normalize_direction(direction): direction for direction in directions
    }
    option_ids: list[str] = []
    matched_directions: set[str] = set()

    for option in options:
        if option.line_label not in selected_lines:
            continue

        matches = {
            selected_direction
            for selected_direction in selected_directions
            if any(
                _directions_match(selected_direction, option_direction)
                for option_direction in (*option.directions, *option.raw_directions)
            )
        }
        if matches:
            option_ids.append(option.id)
            matched_directions.update(matches)

    unmatched = sorted(
        selected_directions[direction]
        for direction in selected_directions.keys() - matched_directions
    )
    if unmatched:
        _LOGGER.warning(
            "Could not migrate legacy MVG directions for lines %s: %s",
            ", ".join(sorted(selected_lines)),
            ", ".join(unmatched),
        )

    return sorted(dict.fromkeys(option_ids))


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list | tuple | set):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalize_direction(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def _directions_match(selected_direction: str, option_direction: str) -> bool:
    selected_tokens = _direction_tokens(selected_direction)
    option_tokens = _direction_tokens(option_direction)
    if not selected_tokens or not option_tokens:
        return False

    return _contains_token_sequence(option_tokens, selected_tokens) or (
        _contains_token_sequence(selected_tokens, option_tokens)
    )


def _direction_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _normalize_direction(value).split()
        if token not in _DIRECTION_SUFFIX_TOKENS
    )


def _contains_token_sequence(
    tokens: tuple[str, ...],
    search_tokens: tuple[str, ...],
) -> bool:
    search_length = len(search_tokens)
    if search_length > len(tokens):
        return False
    return any(
        tokens[index : index + search_length] == search_tokens
        for index in range(len(tokens) - search_length + 1)
    )


def _legacy_direction_variants(direction: str) -> set[str]:
    variants = {direction}
    for part in direction.split("/"):
        part = part.strip()
        if not part:
            continue
        variants.add(part)
        stripped_part = _strip_direction_suffix(part)
        if stripped_part:
            variants.add(stripped_part)
    return variants


def _strip_direction_suffix(direction: str) -> str:
    parts = direction.split()
    while parts:
        suffix = re.sub(r"[^\w\s]", "", parts[-1].casefold())
        if suffix not in _DIRECTION_SUFFIX_TOKENS:
            break
        parts.pop()
    return " ".join(parts)
