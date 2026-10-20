"""Base entities for Munich Public Transport."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from munich_transport.models import StationDirectionOption

from .const import ATTRIBUTION, DOMAIN
from .coordinator import StationData


class MunichTransportEntity[CoordinatorT: DataUpdateCoordinator[Any]](
    CoordinatorEntity[CoordinatorT]
):
    """An entity on a station device, for the station, a line or a direction.

    Generic over the coordinator, since departure entities follow their
    station's coordinator and disruption entities the shared messages one.
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CoordinatorT,
        station: StationData,
        description: EntityDescription,
        *,
        scope: str | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> None:
        """Initialize the entity.

        `scope` narrows the unique id to a line or direction of the station,
        and `placeholders` fill the translated name.
        """

        super().__init__(coordinator)
        self.entity_description = description
        self._station = station

        prefix = station.global_id if scope is None else f"{station.global_id}_{scope}"
        self._attr_unique_id = f"{prefix}_{description.key}"
        if placeholders:
            self._attr_translation_placeholders = dict(placeholders)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station.global_id)},
            name=station.name,
            manufacturer="MVG",
            model="Station",
            entry_type=DeviceEntryType.SERVICE,
        )


def direction_label(direction: StationDirectionOption) -> str:
    """Return the stable "<line> → <terminus>" label for a direction."""

    return f"{direction.line_label} → {direction.normal_terminus or 'unknown'}"


@callback
def async_remove_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    station: StationData,
    domain: str,
    entities: Iterable[Entity],
) -> None:
    """Remove a station's registry entries a platform no longer creates.

    Deselecting a direction reloads the entry without its entities, which
    would otherwise linger as orphans in the entity registry.
    """

    current = {entity.unique_id for entity in entities}
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            registry_entry.domain == domain
            and registry_entry.config_subentry_id == station.subentry_id
            and registry_entry.unique_id not in current
        ):
            entity_registry.async_remove(registry_entry.entity_id)
