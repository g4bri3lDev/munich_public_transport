"""Test migrating legacy (v1) Munich Public Transport entries."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import StationDirectionOption
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.munich_public_transport import (
    _directions_match,
    _migrate_direction_option_ids,
)
from custom_components.munich_public_transport.const import (
    CONF_DIRECTION_OPTION_IDS,
    DOMAIN,
)

from . import DIRECTION_OPTIONS, ENTRY_DATA, STATION

LEGACY_NAME = "Münchner Freiheit"

# The shape the pre-rewrite integration stored. "Fröttmaning" is a short-turn
# destination that no catalog direction lists, like on the live system.
LEGACY_DATA = {
    "station_id": STATION.global_id,
    "station_name": LEGACY_NAME,
    "lines": ["U6"],
    "directions": [
        "Klinikum Großhadern",
        "Garching, Forschungszentrum",
        "Fröttmaning",
    ],
    "departure_count": 10.0,
    "scan_interval": 1.0,
}

LEGACY_SUFFIXES = {
    "next_departure": "next_departure",
    "all_departures": "all_departures",
    "messages": "messages",
    "U6_Klinikum Großhadern": "SUBWAY:U6:H",
    "U6_Garching, Forschungszentrum": "SUBWAY:U6:R",
    # Matches the "Goetheplatz / Klinikum Großhadern" short-turn variant, so it
    # collides with the Klinikum Großhadern entity above.
    "U6_Goetheplatz": "SUBWAY:U6:H",
    "U6_Fröttmaning": None,
}


@pytest.fixture
def legacy_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> MockConfigEntry:
    """Add a v1 entry with the device and entities the old integration made."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, title=LEGACY_NAME, data=LEGACY_DATA
    )
    entry.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{LEGACY_NAME}")},
        name=LEGACY_NAME,
    )
    for suffix in LEGACY_SUFFIXES:
        entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_{LEGACY_NAME}_{suffix}",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"{LEGACY_NAME} {suffix}",
        )
    return entry


async def test_migrate_legacy_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
    legacy_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a v1 entry is rewritten and its registry entries are carried over."""
    entity_ids = {
        suffix: entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{legacy_entry.entry_id}_{LEGACY_NAME}_{suffix}"
        )
        for suffix in LEGACY_SUFFIXES
    }

    assert await hass.config_entries.async_setup(legacy_entry.entry_id)
    await hass.async_block_till_done()

    assert legacy_entry.state is ConfigEntryState.LOADED
    assert legacy_entry.version == 2
    assert legacy_entry.unique_id == STATION.global_id
    assert legacy_entry.title == STATION.name
    assert dict(legacy_entry.data) == ENTRY_DATA
    assert legacy_entry.options == {
        CONF_DIRECTION_OPTION_IDS: ["SUBWAY:U6:H", "SUBWAY:U6:R"]
    }
    mock_client.station.assert_awaited_with(STATION.global_id)

    # The legacy device is rekeyed in place rather than replaced.
    devices = dr.async_entries_for_config_entry(device_registry, legacy_entry.entry_id)
    assert [(device.identifiers, device.name) for device in devices] == [
        ({(DOMAIN, STATION.global_id)}, STATION.name)
    ]

    # Entity ids survive, so dashboards and history keep working.
    for suffix in ("next_departure", "all_departures", "messages"):
        entity = entity_registry.async_get(entity_ids[suffix])
        assert entity.unique_id == f"{legacy_entry.entry_id}_{suffix}"
    for suffix in ("U6_Klinikum Großhadern", "U6_Garching, Forschungszentrum"):
        entity = entity_registry.async_get(entity_ids[suffix])
        assert entity.unique_id == f"{legacy_entry.entry_id}_{LEGACY_SUFFIXES[suffix]}"

    # The short-turn duplicate is dropped instead of clashing on unique id.
    assert entity_registry.async_get(entity_ids["U6_Goetheplatz"]) is None

    assert "Could not migrate legacy MVG directions" in caplog.text
    assert "Fröttmaning" in caplog.text


async def test_migrate_removes_unmatched_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
    legacy_entry: MockConfigEntry,
) -> None:
    """Test entities for directions that cannot be migrated are removed.

    Before this was fixed they kept their old unique id and lingered as
    orphans, like sensor.dietlindenstrasse_u6_frottmaning on a live system.
    """
    assert await hass.config_entries.async_setup(legacy_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{legacy_entry.entry_id}_{LEGACY_NAME}_U6_Fröttmaning"
        )
        is None
    )


async def test_migrate_entity_with_punctuation_difference(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
) -> None:
    """Test entities are remapped with the same fuzzy match as the selection.

    The old integration stored "Tierpark (Alemannenstr)" while the catalog
    spells it "Tierpark (Alemannenstr.)", as for bus 52 at Sendlinger Tor.
    The direction was selected but its entity was removed and recreated
    under a new entity id, losing its history.
    """
    bus_52 = StationDirectionOption(
        id="BUS:52:H",
        schedule_kind="BUS",
        line_label="52",
        direction_key="H",
        directions=("Tierpark",),
        raw_directions=("Tierpark (Alemannenstr.)",),
        schedule_codes=("H",),
    )
    mock_client.station_direction_options_by_abbreviation.return_value = [bus_52]
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            **LEGACY_DATA,
            "lines": ["52"],
            "directions": ["Tierpark (Alemannenstr)"],
        },
    )
    entry.add_to_hass(hass)
    entity_id = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_{LEGACY_NAME}_52_Tierpark (Alemannenstr)",
        config_entry=entry,
    ).entity_id

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options == {CONF_DIRECTION_OPTION_IDS: ["BUS:52:H"]}
    entity = entity_registry.async_get(entity_id)
    assert entity is not None
    assert entity.unique_id == f"{entry.entry_id}_BUS:52:H"


async def test_migrate_prefers_legacy_options(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test lines and directions edited in the old options flow win over data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data=LEGACY_DATA,
        options={"lines": "U6", "directions": ["Garching-Forschungszentrum"]},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options == {CONF_DIRECTION_OPTION_IDS: ["SUBWAY:U6:R"]}


async def test_migrate_without_selection(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test a legacy entry without lines migrates to an empty selection."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data={**LEGACY_DATA, "lines": []})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.options == {CONF_DIRECTION_OPTION_IDS: []}


async def test_migrate_lookup_failure(
    hass: HomeAssistant, mock_client: MagicMock, legacy_entry: MockConfigEntry
) -> None:
    """Test a failed station lookup leaves the v1 entry untouched."""
    mock_client.station.side_effect = MunichTransportError("boom")

    assert not await hass.config_entries.async_setup(legacy_entry.entry_id)
    await hass.async_block_till_done()

    assert legacy_entry.state is ConfigEntryState.MIGRATION_ERROR
    assert legacy_entry.version == 1
    assert dict(legacy_entry.data) == LEGACY_DATA


async def test_migrate_without_station_id(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test a v1 entry without a station id cannot be migrated."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data={"station_name": "X"})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    mock_client.station.assert_not_awaited()


async def test_migrate_new_data_with_old_version(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test an entry that already has rewrite data only gets its version bumped."""
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert dict(entry.data) == ENTRY_DATA
    mock_client.station.assert_not_awaited()


@pytest.mark.parametrize(
    ("selected", "option", "expected"),
    [
        ("Garching, Forschungszentrum", "Garching-Forschungszentrum", True),
        ("Giesing", "Giesing Bf.", True),
        ("Moosach Bahnhof", "Moosach Bf", True),
        ("Goetheplatz", "Goetheplatz / Klinikum Großhadern", True),
        ("Klinikum", "Klinikum Großhadern", True),
        ("Fröttmaning", "Garching, Forschungszentrum", False),
        ("Hbf", "Hauptbahnhof", False),
    ],
)
def test_directions_match(selected: str, option: str, expected: bool) -> None:
    """Test legacy direction names are matched against catalog directions."""
    assert _directions_match(selected, option) is expected


def test_migrate_direction_option_ids_ignores_other_lines() -> None:
    """Test a direction only matches options of a selected line."""
    assert (
        _migrate_direction_option_ids(
            DIRECTION_OPTIONS, lines=["U3"], directions=["Klinikum Großhadern"]
        )
        == []
    )
