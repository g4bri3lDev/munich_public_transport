"""Test migrating 0.0.7 (v1) and 1.x (v2) entries into one MVG entry."""

from collections.abc import Callable
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import StationDirectionOption
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.munich_public_transport.const import (
    CONF_DIRECTION_OPTION_IDS,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    SUBENTRY_TYPE_STATION,
)
from custom_components.munich_public_transport.migration import (
    _migrate_direction_option_ids,
)

from . import DIRECTION_OPTIONS, ENTRY_DATA, STATION, STATION_DATA

BONNER_PLATZ_DATA = {
    "name": "Bonner Platz",
    "station_global_id": "de:09162:410",
    "station_abbreviation": "BP",
    "station_place": "München",
}
SLUG = "munchner_freiheit"

type EntryFactory = Callable[..., MockConfigEntry]


def _sensor_id(entity_registry: er.EntityRegistry, unique_id: str) -> str | None:
    return entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)


@pytest.fixture
def v2_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> EntryFactory:
    """Return a factory for 1.x station entries with their registry entries."""

    def create(
        data: dict = ENTRY_DATA,
        direction_ids: tuple[str, ...] = ("SUBWAY:U6:H", "SUBWAY:U6:R"),
        *,
        disabled: bool = False,
    ) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            title=data["name"],
            unique_id=data["station_global_id"],
            data=data,
            options={CONF_DIRECTION_OPTION_IDS: list(direction_ids)},
            disabled_by=ConfigEntryDisabler.USER if disabled else None,
        )
        entry.add_to_hass(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, data["station_global_id"])},
            name=data["name"],
        )
        slug = data["name"].lower().replace(" ", "_").replace("ü", "u")
        suffixes = {
            "next_departure": "next_departure",
            "all_departures": "all_departures",
            "messages": "messages",
            # A leftover the 1.0 migration never remapped.
            f"{data['name']}_U6_Fröttmaning": "u6_frottmaning",
        }
        for direction_id in direction_ids:
            suffixes[direction_id] = direction_id.lower().replace(":", "_")
        for suffix, object_id in suffixes.items():
            entity_registry.async_get_or_create(
                "sensor",
                DOMAIN,
                f"{entry.entry_id}_{suffix}",
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=f"{slug}_{object_id}",
                disabled_by=(
                    er.RegistryEntryDisabler.CONFIG_ENTRY if disabled else None
                ),
            )
        return entry

    return create


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    [entry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.version == CONFIG_ENTRY_VERSION
    ]
    return entry


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v2_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    v2_entry: EntryFactory,
) -> None:
    """Test a 1.x entry becomes the MVG entry, keeping device and entity ids."""
    old = v2_entry()
    old_entry_id = old.entry_id
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, STATION.global_id), old_entry_id
    )
    departure_entity_id = _sensor_id(entity_registry, f"{old_entry_id}_SUBWAY:U6:H")

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id == old_entry_id
    assert (entry.title, dict(entry.data), dict(entry.options)) == ("MVG", {}, {})
    assert entry.unique_id is None
    [subentry] = entry.subentries.values()
    assert subentry.subentry_type == SUBENTRY_TYPE_STATION
    assert subentry.unique_id == STATION.global_id
    assert dict(subentry.data) == STATION_DATA

    moved = device_registry.async_get(device.id)
    assert moved.config_subentry_id == subentry.subentry_id

    # Successors keep their entity ids.
    gid = STATION.global_id
    assert _sensor_id(entity_registry, f"{gid}_SUBWAY:U6:H_departure") == (
        departure_entity_id
    )
    assert (
        _sensor_id(entity_registry, f"{gid}_disruptions") == f"sensor.{SLUG}_messages"
    )
    # Replaced by the action and the departure sensors, and the 1.0 leftover.
    for removed in ("all_departures", "next_departure"):
        assert hass.states.get(f"sensor.{SLUG}_{removed}") is None
        assert entity_registry.async_get(f"sensor.{SLUG}_{removed}") is None
    assert entity_registry.async_get(f"sensor.{SLUG}_u6_frottmaning") is None

    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {entity.config_subentry_id for entity in entities} == {subentry.subentry_id}
    assert hass.states.get(departure_entity_id).state == ("2026-10-19T12:03:00+00:00")


@pytest.mark.usefixtures("mock_client")
async def test_migrate_merges_stations(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    v2_entry: EntryFactory,
) -> None:
    """Test several 1.x entries end up as subentries of one MVG entry."""
    first = v2_entry()
    second = v2_entry(BONNER_PLATZ_DATA, ("SUBWAY:U3:H",))
    second_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "de:09162:410"), second.entry_id
    )

    entry = await _setup(hass)

    assert entry.entry_id == first.entry_id
    assert hass.config_entries.async_get_entry(second.entry_id) is None
    assert {subentry.title for subentry in entry.subentries.values()} == {
        "Münchner Freiheit",
        "Bonner Platz",
    }
    moved = device_registry.async_get(second_device.id)
    assert moved is not None
    assert moved.config_entry_id == entry.entry_id


async def test_migrate_disabled_station(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    mock_client: MagicMock,
    v2_entry: EntryFactory,
) -> None:
    """Test a disabled station stays off without disabling the MVG entry.

    The disabled entry is listed first, so this also checks it is not picked
    as the parent.
    """
    disabled = v2_entry(BONNER_PLATZ_DATA, ("SUBWAY:U3:H",), disabled=True)
    enabled = v2_entry()

    entry = await _setup(hass)

    assert entry.entry_id == enabled.entry_id
    assert entry.disabled_by is None
    assert hass.config_entries.async_get_entry(disabled.entry_id) is None
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, "de:09162:410"), entry.entry_id
    )
    assert device.disabled_by is dr.DeviceEntryDisabler.USER
    entity = entity_registry.async_get("sensor.bonner_platz_subway_u3_h")
    assert entity.disabled_by is er.RegistryEntryDisabler.DEVICE
    assert [station.name for station in entry.runtime_data.stations.values()] == [
        "Münchner Freiheit"
    ]
    assert "de:09162:410" not in {
        call.args[0] for call in mock_client.departures.await_args_list
    }


@pytest.mark.usefixtures("mock_client")
async def test_migrate_skips_station_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    v2_entry: EntryFactory,
) -> None:
    """Test a 1.x entry for a station the MVG entry has is dropped."""
    mock_config_entry.add_to_hass(hass)
    duplicate = v2_entry()

    entry = await _setup(hass)

    assert entry.entry_id == mock_config_entry.entry_id
    assert len(entry.subentries) == 1
    assert hass.config_entries.async_get_entry(duplicate.entry_id) is None


# --- 0.0.7 (v1) entries --------------------------------------------------

LEGACY_NAME = "Münchner Freiheit"
LEGACY_DATA = {
    "station_id": STATION.global_id,
    "station_name": LEGACY_NAME,
    "lines": ["U6", "52"],
    "directions": [
        "Klinikum Großhadern",
        "Garching, Forschungszentrum",
        "Tierpark (Alemannenstr)",
        "Fröttmaning",
    ],
    "departure_count": 10.0,
    "scan_interval": 1.0,
}
BUS_52 = StationDirectionOption(
    id="BUS:52:H",
    schedule_kind="BUS",
    line_label="52",
    direction_key="H",
    directions=("Tierpark",),
    raw_directions=("Tierpark (Alemannenstr.)",),
    schedule_codes=("H",),
)
# Legacy line sensors and the option each one should end up on.
LEGACY_LINE_SENSORS = {
    "U6_Klinikum Großhadern": "SUBWAY:U6:H",
    "U6_Garching, Forschungszentrum": "SUBWAY:U6:R",
    # Punctuation differs from the catalog's "Tierpark (Alemannenstr.)".
    "52_Tierpark (Alemannenstr)": "BUS:52:H",
    # The "Goetheplatz / Klinikum Großhadern" short-turn, a duplicate of H.
    "U6_Goetheplatz": None,
    # No catalog direction covers it.
    "U6_Fröttmaning": None,
}


@pytest.fixture
def v1_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> EntryFactory:
    """Return a factory for 0.0.7 entries with the registry they created."""

    def create(
        data: dict = LEGACY_DATA, options: dict | None = None
    ) -> MockConfigEntry:
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=1,
            title=LEGACY_NAME,
            data=data,
            options=options or {},
        )
        entry.add_to_hass(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{LEGACY_NAME}")},
            name=LEGACY_NAME,
        )
        for suffix in (
            "next_departure",
            "all_departures",
            "messages",
            *LEGACY_LINE_SENSORS,
        ):
            entity_registry.async_get_or_create(
                "sensor",
                DOMAIN,
                f"{entry.entry_id}_{LEGACY_NAME}_{suffix}",
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=f"{SLUG} {suffix}",
            )
        return entry

    return create


@pytest.mark.parametrize("direction_options", [[*DIRECTION_OPTIONS, BUS_52]])
@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    v1_entry: EntryFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test a 0.0.7 entry migrates through 1.x into the MVG entry."""
    old = v1_entry()
    entity_ids = {
        suffix: _sensor_id(entity_registry, f"{old.entry_id}_{LEGACY_NAME}_{suffix}")
        for suffix in LEGACY_LINE_SENSORS
    }

    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    [subentry] = entry.subentries.values()
    assert subentry.data[CONF_DIRECTION_OPTION_IDS] == [
        "BUS:52:H",
        "SUBWAY:U6:H",
        "SUBWAY:U6:R",
    ]
    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, STATION.global_id), entry.entry_id
    )
    for suffix, option_id in LEGACY_LINE_SENSORS.items():
        if option_id is None:
            assert entity_registry.async_get(entity_ids[suffix]) is None
        else:
            unique_id = f"{STATION.global_id}_{option_id}_departure"
            assert _sensor_id(entity_registry, unique_id) == entity_ids[suffix]
    assert "Could not migrate legacy MVG directions" in caplog.text
    assert "Fröttmaning" in caplog.text


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_prefers_options(
    hass: HomeAssistant, v1_entry: EntryFactory
) -> None:
    """Test lines and directions edited in the old options flow win over data."""
    v1_entry(options={"lines": "U6", "directions": ["Garching-Forschungszentrum"]})

    entry = await _setup(hass)

    [subentry] = entry.subentries.values()
    assert subentry.data[CONF_DIRECTION_OPTION_IDS] == ["SUBWAY:U6:R"]


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_with_rewrite_data(hass: HomeAssistant) -> None:
    """Test a v1 entry that already has rewrite data needs no lookup."""
    MockConfigEntry(domain=DOMAIN, version=1, data=ENTRY_DATA).add_to_hass(hass)

    entry = await _setup(hass)

    [subentry] = entry.subentries.values()
    assert subentry.unique_id == STATION.global_id


async def test_migrate_v1_lookup_failure_is_retried(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    v1_entry: EntryFactory,
    v2_entry: EntryFactory,
) -> None:
    """Test MVG being unreachable defers a 0.0.7 entry until it can be merged.

    Other stations are merged right away, and Home Assistant retries the
    deferred migration on its own.
    """
    mock_client.station.side_effect = MunichTransportError("boom")
    legacy = v1_entry()
    v2_entry(BONNER_PLATZ_DATA, ("SUBWAY:U3:H",))

    entry = await _setup(hass)

    assert [subentry.title for subentry in entry.subentries.values()] == [
        "Bonner Platz"
    ]
    assert legacy.state is ConfigEntryState.SETUP_RETRY
    assert dict(legacy.data) == LEGACY_DATA

    mock_client.station.side_effect = None
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    assert {subentry.title for subentry in entry.subentries.values()} == {
        "Bonner Platz",
        "Münchner Freiheit",
    }
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.runtime_data.stations) == 2


async def test_migrate_v1_without_station_id(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    mock_client: MagicMock,
) -> None:
    """Test a v1 entry without a station id raises a repair issue."""
    legacy = MockConfigEntry(
        domain=DOMAIN, version=1, title="Old", data={"station_name": "X"}
    )
    legacy.add_to_hass(hass)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert legacy.state is ConfigEntryState.MIGRATION_ERROR
    assert issue_registry.async_get_issue(
        DOMAIN, f"legacy_entry_without_station_{legacy.entry_id}"
    )
    mock_client.station.assert_not_awaited()


def test_migrate_direction_option_ids_ignores_other_lines() -> None:
    """Test a direction only selects options of a selected line."""
    assert (
        _migrate_direction_option_ids(
            DIRECTION_OPTIONS, lines=["U3"], directions=["Klinikum Großhadern"]
        )
        == []
    )
