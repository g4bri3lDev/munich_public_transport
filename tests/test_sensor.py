"""Test the Munich Public Transport sensors."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from munich_transport.exceptions import MunichTransportError
from munich_transport.models import Disruption, Line
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    snapshot_platform,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.munich_public_transport.const import DEFAULT_SCAN_INTERVAL

from . import STATION, U6, make_departure

NOW = datetime.fromisoformat("2026-10-19T12:00:00+00:00")
U3 = Line(label="U3", transport_type="UBAHN", network="swm")


@pytest.fixture(autouse=True)
async def munich_time_zone(hass: HomeAssistant) -> None:
    """Render local times the way users of a Munich integration see them."""
    await hass.config.async_set_time_zone("Europe/Berlin")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the sensor entities and their attributes."""
    freezer.move_to(NOW)
    mock_client.departures.return_value = [
        make_departure(
            8, destination="Garching, Forschungszentrum", direction_key="R", now=NOW
        ),
        make_departure(3, delay=2, now=NOW),
        # Not selected, so it must not show up in any sensor.
        make_departure(
            1, line=U3, destination="Moosach Bf", direction_key="R", now=NOW
        ),
    ]

    await _setup(hass, mock_config_entry)

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_line_sensor_name_follows_destination(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a short-turn departure is reflected in the line sensor's name."""
    await _setup(hass, mock_config_entry)
    entity_id = "sensor.munchner_freiheit_u6_klinikum_grosshadern"
    assert (
        hass.states.get(entity_id).name == "Münchner Freiheit U6 → Klinikum Großhadern"
    )

    mock_client.departures.return_value = [make_departure(4, destination="Goetheplatz")]
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.name == "Münchner Freiheit U6 → Goetheplatz"
    assert state.attributes["destination"] == "Goetheplatz"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The entity id is derived from the live name at creation, so a "
        "short-turn departure at setup time bakes its destination into the "
        "entity id instead of the stable catalog terminus"
    ),
)
async def test_line_sensor_entity_id_uses_terminus(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the entity id stays stable when set up during a short turn."""
    mock_client.departures.return_value = [make_departure(4, destination="Goetheplatz")]

    await _setup(hass, mock_config_entry)

    assert hass.states.get("sensor.munchner_freiheit_u6_klinikum_grosshadern")


async def test_no_departures(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test sensors report unknown when nothing departs."""
    mock_client.departures.return_value = []

    await _setup(hass, mock_config_entry)

    state = hass.states.get("sensor.munchner_freiheit_next_departure")
    assert state.state == STATE_UNKNOWN
    assert state.attributes["icon"] == "mdi:train-car"
    state = hass.states.get("sensor.munchner_freiheit_all_departures")
    assert state.state == STATE_UNKNOWN
    assert state.attributes["departures"] == []
    assert state.attributes["icon"] == "mdi:train-car-multiple"


async def test_line_sensors_without_catalog(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test line sensors are still created when the catalog is unreachable."""
    mock_client.station_direction_options_by_abbreviation.side_effect = (
        MunichTransportError("boom")
    )
    mock_client.departures.return_value = []

    await _setup(hass, mock_config_entry)

    state = hass.states.get("sensor.munchner_freiheit_u6_unknown")
    assert state is not None
    assert state.attributes["line"] == "U6"
    assert state.attributes["direction_key"] == "H"
    assert state.attributes["direction_variants"] == []


def _disruption(
    title: str,
    *,
    lines: tuple[Line, ...] = (),
    stations: tuple[str, ...] = (),
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> Disruption:
    return Disruption(
        title=title,
        description_html=f"<p>{title}</p>",
        kind="INCIDENT",
        valid_from=valid_from,
        valid_to=valid_to,
        lines=lines,
        station_global_ids=stations,
    )


async def test_messages_sensor(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test only active messages for this station or its lines are counted."""
    freezer.move_to(NOW)
    hour = timedelta(hours=1)
    mock_client.messages.return_value = [
        _disruption("This station", stations=(STATION.global_id,), lines=(U3,)),
        _disruption("Other station", stations=("de:09162:1",), lines=(U6,)),
        _disruption("Selected line", lines=(U6,), valid_to=NOW + hour),
        _disruption("Other line", lines=(U3,)),
        _disruption("Network wide", valid_from=NOW - hour),
        _disruption("Expired", lines=(U6,), valid_to=NOW - hour),
        _disruption("Upcoming", lines=(U6,), valid_from=NOW + hour),
    ]

    await _setup(hass, mock_config_entry)

    state = hass.states.get("sensor.munchner_freiheit_messages")
    assert state.state == "3"
    messages = state.attributes["messages"]
    assert [message["title"] for message in messages] == [
        "This station",
        "Selected line",
        "Network wide",
    ]
    assert messages[0]["lines"] == ["U3"]
    assert messages[0]["validity"] == "No specific time"
    assert messages[1]["validity"] == "Until 19.10.2026 15:00"
    assert messages[2]["lines"] == ["All lines"]
    assert messages[2]["validity"] == "From 19.10.2026 13:00"


@pytest.mark.parametrize(
    ("valid_from", "valid_to", "expected"),
    [
        (
            "2026-10-19T10:00:00+00:00",
            "2026-10-19T14:00:00+00:00",
            "19.10.2026 12:00 - 16:00",
        ),
        (
            "2026-10-19T10:00:00+00:00",
            "2026-10-21T10:00:00+00:00",
            "19.10.2026 12:00 - 21.10.2026 12:00",
        ),
    ],
)
async def test_message_validity_ranges(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    valid_from: str,
    valid_to: str,
    expected: str,
) -> None:
    """Test validity ranges render in local time, collapsing same-day dates."""
    freezer.move_to(NOW)
    mock_client.messages.return_value = [
        _disruption(
            "Range",
            valid_from=datetime.fromisoformat(valid_from),
            valid_to=datetime.fromisoformat(valid_to),
        )
    ]

    await _setup(hass, mock_config_entry)

    state = hass.states.get("sensor.munchner_freiheit_messages")
    assert state.attributes["messages"][0]["validity"] == expected
