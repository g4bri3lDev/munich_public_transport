"""Migrate earlier config entries into one MVG entry with station subentries."""

from __future__ import annotations

import logging
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import UNDEFINED
from munich_transport.client import MunichTransportClient
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import StationDirectionOption
from munich_transport.schedules import direction_names_match
from munich_transport.transport import AiohttpTransport

from .const import (
    CONF_DIRECTION_OPTION_IDS,
    CONF_STATION_ABBREVIATION,
    CONF_STATION_GLOBAL_ID,
    CONF_STATION_PLACE,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    ENTRY_TITLE,
    OLD_CONF_DIRECTIONS,
    OLD_CONF_LINES,
    OLD_CONF_STATION_ID,
    OLD_CONF_STATION_NAME,
    STATION_DATA_KEYS,
    SUBENTRY_TYPE_STATION,
)

_LOGGER = logging.getLogger(__name__)

_LEGACY_STATION_SENSORS = ("next_departure", "all_departures", "messages")


async def async_migrate_integration(hass: HomeAssistant) -> None:
    """Merge per-station entries into one MVG entry with station subentries.

    Runs before any entry is set up. An entry that cannot be migrated yet is
    left alone; Home Assistant then calls async_migrate_entry for it, which
    retries through async_migrate_station_entry.
    """

    # An enabled entry becomes the parent, so a disabled station does not
    # disable the whole integration.
    for entry in sorted(
        hass.config_entries.async_entries(DOMAIN),
        key=lambda entry: entry.disabled_by is not None,
    ):
        if entry.version >= CONFIG_ENTRY_VERSION:
            continue
        try:
            await async_migrate_station_entry(hass, entry)
        except (ConfigEntryError, ConfigEntryNotReady) as err:
            _LOGGER.debug("Deferring migration of %s: %s", entry.title, err)


async def async_migrate_station_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Convert one per-station entry and merge it into the MVG entry.

    Returns True when the entry became the MVG entry itself. When it was
    merged into an existing MVG entry it is removed, and False is returned
    so it is not set up in the meantime.
    """

    if entry.version == 1:
        await _async_migrate_v1_entry(hass, entry)

    global_id = entry.data[CONF_STATION_GLOBAL_ID]
    parent = next(
        (
            other
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.version == CONFIG_ENTRY_VERSION
        ),
        None,
    )
    if parent is not None and any(
        subentry.unique_id == global_id for subentry in parent.subentries.values()
    ):
        _LOGGER.warning("Removing duplicate MVG entry for %s", entry.title)
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return False

    subentry = ConfigSubentry(
        data=MappingProxyType(
            {
                **{key: entry.data.get(key) for key in STATION_DATA_KEYS},
                CONF_DIRECTION_OPTION_IDS: list(
                    entry.options.get(CONF_DIRECTION_OPTION_IDS, ())
                ),
            }
        ),
        subentry_type=SUBENTRY_TYPE_STATION,
        title=entry.data[CONF_NAME],
        unique_id=global_id,
    )

    if parent is None:
        hass.config_entries.async_update_entry(
            entry,
            data={},
            options={},
            title=ENTRY_TITLE,
            unique_id=None,
            version=CONFIG_ENTRY_VERSION,
        )
        hass.config_entries.async_add_subentry(entry, subentry)
        _move_station_registries(hass, entry, entry, subentry, disable=False)
        return True

    # Adding a subentry fires the update listener of a loaded parent, whose
    # reload would create the station's entities before the old ones are
    # moved over. Unload it first and reload once the registries are merged.
    reload_parent = parent.state is ConfigEntryState.LOADED
    if reload_parent:
        await hass.config_entries.async_unload(parent.entry_id)
    hass.config_entries.async_add_subentry(parent, subentry)
    _move_station_registries(
        hass, entry, parent, subentry, disable=entry.disabled_by is not None
    )
    if reload_parent:
        hass.config_entries.async_schedule_reload(parent.entry_id)
    # Removing the entry awaits its unload, which cannot happen while it is
    # being migrated, so it runs in the background.
    hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
    return False


@callback
def _move_station_registries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    parent: ConfigEntry,
    subentry: ConfigSubentry,
    *,
    disable: bool,
) -> None:
    """Move a station entry's device and entities into the parent's subentry.

    Device and entity ids are kept, so automations and dashboards survive.
    A disabled station keeps its entities but has its device disabled, so it
    stays switched off without disabling the whole MVG entry.
    """

    global_id = subentry.data[CONF_STATION_GLOBAL_ID]

    # Entities first: moving a device removes the entities still attached to
    # its old entry and subentry.
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        new_unique_id = _station_unique_id(entry.entry_id, global_id, entity.unique_id)
        if new_unique_id is None:
            entity_registry.async_remove(entity.entity_id)
            continue
        disabled_by = entity.disabled_by
        if disabled_by is er.RegistryEntryDisabler.CONFIG_ENTRY:
            disabled_by = er.RegistryEntryDisabler.DEVICE if disable else None
        entity_registry.async_update_entity(
            entity.entity_id,
            config_entry_id=parent.entry_id,
            config_subentry_id=subentry.subentry_id,
            new_unique_id=new_unique_id,
            disabled_by=disabled_by,
        )

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        device_registry.async_update_device(
            device.id,
            new_config_entry_id=parent.entry_id,
            new_config_subentry_id=subentry.subentry_id,
            disabled_by=dr.DeviceEntryDisabler.USER if disable else UNDEFINED,
        )


def _station_unique_id(entry_id: str, global_id: str, unique_id: str) -> str | None:
    """Map a 1.x unique id to its subentry successor, or None to remove it."""

    suffix = unique_id.removeprefix(f"{entry_id}_")
    if suffix == unique_id:
        return None
    if suffix == "messages":
        return f"{global_id}_disruptions"
    if suffix.count(":") == 2:
        # A line/direction sensor; its successor is the departure sensor.
        return f"{global_id}_{suffix}_departure"
    # all_departures and next_departure are replaced by the get_departures
    # action and the departure sensors, and anything else is a legacy
    # leftover that never got migrated.
    return None


async def _async_migrate_v1_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Convert a pre-rewrite entry to the per-station rewrite schema."""

    if CONF_STATION_GLOBAL_ID in entry.data:
        hass.config_entries.async_update_entry(entry, version=2)
        return

    old_station_id = entry.data.get(OLD_CONF_STATION_ID)
    if not isinstance(old_station_id, str):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"legacy_entry_without_station_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="legacy_entry_without_station",
            translation_placeholders={"title": entry.title},
        )
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="legacy_entry_without_station",
            translation_placeholders={"title": entry.title},
        )

    client = MunichTransportClient(
        AiohttpTransport(session=async_get_clientsession(hass))
    )
    try:
        station = await client.station(old_station_id)
        direction_options = await client.direction_options_for_station(station)
    except MunichTransportError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="migration_cannot_connect",
            translation_placeholders={"title": entry.title},
        ) from err

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

    old_station_name = str(entry.data.get(OLD_CONF_STATION_NAME, old_station_id))
    _migrate_legacy_registries(
        hass,
        entry,
        old_station_name=old_station_name,
        station_global_id=station.global_id,
        station_name=station.name or old_station_name,
        direction_options=direction_options,
    )

    hass.config_entries.async_update_entry(
        entry,
        data={
            CONF_NAME: station.name or old_station_name,
            CONF_STATION_GLOBAL_ID: station.global_id,
            CONF_STATION_ABBREVIATION: station.abbreviation,
            CONF_STATION_PLACE: station.place,
        },
        options={CONF_DIRECTION_OPTION_IDS: migrated_direction_ids},
        title=station.name or entry.title,
        unique_id=station.global_id,
        version=2,
    )


@callback
def _migrate_legacy_registries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    old_station_name: str,
    station_global_id: str,
    station_name: str,
    direction_options: list[StationDirectionOption],
) -> None:
    """Rekey a pre-rewrite entry's device and entities to the 1.x scheme."""

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if (DOMAIN, f"{entry.entry_id}_{old_station_name}") in device.identifiers:
            device_registry.async_update_device(
                device.id,
                new_identifiers={(DOMAIN, station_global_id)},
                name=station_name,
            )

    entity_registry = er.async_get(hass)
    legacy_prefix = f"{entry.entry_id}_{old_station_name}_"
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if not entity_entry.unique_id.startswith(legacy_prefix):
            continue
        suffix = entity_entry.unique_id.removeprefix(legacy_prefix)
        new_unique_id: str | None = (
            f"{entry.entry_id}_{suffix}"
            if suffix in _LEGACY_STATION_SENSORS
            else _legacy_line_unique_id(entry, suffix, direction_options)
        )

        if new_unique_id is None:
            # A legacy direction no catalog option covers would otherwise keep
            # its old unique id and linger as an orphaned entity.
            _LOGGER.info(
                "Removing legacy MVG entity %s without a matching direction",
                entity_entry.entity_id,
            )
            entity_registry.async_remove(entity_entry.entity_id)
            continue

        existing_entity_id = entity_registry.async_get_entity_id(
            entity_entry.domain, DOMAIN, new_unique_id
        )
        if existing_entity_id not in (None, entity_entry.entity_id):
            # Two legacy spellings of one direction, e.g. a short-turn.
            entity_registry.async_remove(entity_entry.entity_id)
            continue

        entity_registry.async_update_entity(
            entity_entry.entity_id, new_unique_id=new_unique_id
        )


def _legacy_line_unique_id(
    entry: ConfigEntry,
    line_and_direction: str,
    direction_options: list[StationDirectionOption],
) -> str | None:
    """Map a legacy "<line>_<direction>" sensor to its direction option."""

    line_label, separator, direction = line_and_direction.partition("_")
    if not separator:
        return None

    for option in direction_options:
        if option.line_label == line_label and any(
            direction_names_match(direction, option_direction)
            for option_direction in (*option.directions, *option.raw_directions)
        ):
            return f"{entry.entry_id}_{option.id}"
    return None


def _migrate_direction_option_ids(
    options: list[StationDirectionOption],
    *,
    lines: list[str],
    directions: list[str],
) -> list[str]:
    """Select the options the old line and direction filters covered.

    The old integration filtered lines and directions independently, so a
    direction selects it on every selected line that serves it.
    """

    if not lines or not directions:
        return []

    selected_lines = set(lines)
    option_ids: list[str] = []
    matched_directions: set[str] = set()

    for option in options:
        if option.line_label not in selected_lines:
            continue

        matches = {
            direction
            for direction in directions
            if any(
                direction_names_match(direction, option_direction)
                for option_direction in (*option.directions, *option.raw_directions)
            )
        }
        if matches:
            option_ids.append(option.id)
            matched_directions.update(matches)

    unmatched = sorted(set(directions) - matched_directions)
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
