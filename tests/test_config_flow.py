"""Test the Munich Public Transport config and options flows."""

from dataclasses import replace
from unittest.mock import MagicMock

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from munich_transport.exceptions import MunichTransportError, ParseError
from munich_transport.models import Location
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.munich_public_transport.const import (
    CONF_DIRECTION_OPTION_IDS,
    DOMAIN,
)

from . import ENTRY_DATA, STATION

LOCATION = Location(
    name=STATION.name,
    place=STATION.place,
    latitude=STATION.latitude,
    longitude=STATION.longitude,
    kind="STATION",
    global_id=STATION.global_id,
)

SUBWAY_SECTION = {"subway": {"direction_option_ids_subway": ["SUBWAY:U6:H"]}}


@pytest.fixture(autouse=True)
def mock_search(mock_client: MagicMock) -> MagicMock:
    """Return Münchner Freiheit for every station search."""
    mock_client.search_locations.return_value = [LOCATION]
    return mock_client


async def _start_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


async def _search(hass: HomeAssistant, flow_id: str) -> dict:
    return await hass.config_entries.flow.async_configure(
        flow_id, {"query": "  Münchner Freiheit  "}
    )


async def _select_station(hass: HomeAssistant, flow_id: str) -> dict:
    return await hass.config_entries.flow.async_configure(
        flow_id, {"selected_station": STATION.global_id}
    )


async def test_full_flow(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Test searching, picking a station and choosing directions."""
    flow_id = await _start_flow(hass)

    result = await _search(hass, flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_station"
    mock_client.search_locations.assert_awaited_once_with("Münchner Freiheit")

    result = await _select_station(hass, flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_directions"
    mock_client.station_direction_options_by_abbreviation.assert_awaited_once_with("MU")

    result = await hass.config_entries.flow.async_configure(flow_id, SUBWAY_SECTION)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Münchner Freiheit"
    assert result["data"] == ENTRY_DATA
    assert result["options"] == {CONF_DIRECTION_OPTION_IDS: ["SUBWAY:U6:H"]}
    assert result["result"].unique_id == STATION.global_id


async def test_station_without_abbreviation(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test direction options come from live departures without a catalog."""
    mock_client.station.return_value = replace(STATION, abbreviation=None)
    flow_id = await _start_flow(hass)
    await _search(hass, flow_id)

    result = await _select_station(hass, flow_id)

    assert result["step_id"] == "select_directions"
    mock_client.station_direction_options_by_abbreviation.assert_not_awaited()
    mock_client.departures.assert_awaited_once_with(STATION.global_id)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"other": {"direction_option_ids_other": ["UBAHN:U6:R"]}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_DIRECTION_OPTION_IDS: ["UBAHN:U6:R"]}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Departure-derived options use the transport type (UBAHN) as schedule "
        "kind, which _SECTION_LABELS only knows as SUBWAY, so they land in an "
        "untranslated 'other' section"
    ),
)
async def test_station_without_abbreviation_uses_subway_section(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Test departure-derived U-Bahn options are grouped like catalog ones."""
    mock_client.station.return_value = replace(STATION, abbreviation=None)
    flow_id = await _start_flow(hass)
    await _search(hass, flow_id)

    result = await _select_station(hass, flow_id)

    assert {str(key) for key in result["data_schema"].schema} == {"subway"}


@pytest.mark.parametrize(
    ("side_effect", "return_value", "error"),
    [
        (MunichTransportError("boom"), None, "cannot_connect"),
        (None, [], "no_stations_found"),
        (
            None,
            [
                Location(
                    name="Somewhere",
                    place=None,
                    latitude=0,
                    longitude=0,
                    kind="ADDRESS",
                )
            ],
            "no_stations_found",
        ),
    ],
)
async def test_search_errors_recover(
    hass: HomeAssistant,
    mock_client: MagicMock,
    side_effect: Exception | None,
    return_value: list[Location] | None,
    error: str,
) -> None:
    """Test search errors are shown and the flow recovers on retry."""
    mock_client.search_locations.side_effect = side_effect
    if return_value is not None:
        mock_client.search_locations.return_value = return_value
    flow_id = await _start_flow(hass)

    result = await _search(hass, flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    mock_client.search_locations.side_effect = None
    mock_client.search_locations.return_value = [LOCATION]
    result = await _search(hass, flow_id)
    assert result["step_id"] == "select_station"


@pytest.mark.parametrize(
    ("attribute", "side_effect", "return_value", "error"),
    [
        ("station", ParseError("bad"), None, "invalid_station"),
        ("station", MunichTransportError("boom"), None, "cannot_connect"),
        (
            "station_direction_options_by_abbreviation",
            MunichTransportError("boom"),
            None,
            "cannot_connect",
        ),
        ("station_direction_options_by_abbreviation", None, [], "no_direction_options"),
    ],
)
async def test_select_station_errors_recover(
    hass: HomeAssistant,
    mock_client: MagicMock,
    attribute: str,
    side_effect: Exception | None,
    return_value: list | None,
    error: str,
) -> None:
    """Test station lookup errors are shown and the flow recovers on retry."""
    mock = getattr(mock_client, attribute)
    original = mock.return_value
    mock.side_effect = side_effect
    if return_value is not None:
        mock.return_value = return_value
    flow_id = await _start_flow(hass)
    await _search(hass, flow_id)

    result = await _select_station(hass, flow_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_station"
    assert result["errors"] == {"base": error}

    mock.side_effect = None
    mock.return_value = original
    result = await _select_station(hass, flow_id)
    assert result["step_id"] == "select_directions"
    result = await hass.config_entries.flow.async_configure(flow_id, SUBWAY_SECTION)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == STATION.global_id


async def test_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a configured station aborts before any lookups."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _start_flow(hass)
    await _search(hass, flow_id)

    result = await _select_station(hass, flow_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the options flow preselects and updates direction choices."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {}
    defaults = {
        str(key): key.default()
        for key in result["data_schema"].schema["subway"].schema.schema
    }
    assert defaults == {"direction_option_ids_subway": ["SUBWAY:U6:H", "SUBWAY:U6:R"]}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], SUBWAY_SECTION
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_DIRECTION_OPTION_IDS: ["SUBWAY:U6:H"]}


async def test_options_flow_cannot_connect(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the options flow reports a failed direction lookup."""
    mock_config_entry.add_to_hass(hass)
    mock_client.station_direction_options_by_abbreviation.side_effect = (
        MunichTransportError("boom")
    )

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "When the direction lookup fails the form has no fields, so "
        "submitting it saves an empty selection and drops every sensor"
    ),
)
async def test_options_flow_cannot_connect_keeps_selection(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test submitting after a failed lookup does not wipe the selection."""
    mock_config_entry.add_to_hass(hass)
    mock_client.station_direction_options_by_abbreviation.side_effect = (
        MunichTransportError("boom")
    )
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert mock_config_entry.options[CONF_DIRECTION_OPTION_IDS] == [
        "SUBWAY:U6:H",
        "SUBWAY:U6:R",
    ]
