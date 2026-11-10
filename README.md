# Munich Public Transport (MVG) Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/g4bri3lDev/munich_public_transport?style=for-the-badge)](https://github.com/g4bri3lDev/munich_public_transport/releases)
[![GitHub issues](https://img.shields.io/github/issues/g4bri3lDev/munich_public_transport?style=for-the-badge)](https://github.com/g4bri3lDev/munich_public_transport/issues)
[![GitHub stars](https://img.shields.io/github/stars/g4bri3lDev/munich_public_transport?style=for-the-badge)](https://github.com/g4bri3lDev/munich_public_transport/stargazers)

Home Assistant custom integration for live departures and service messages of
Munich public transport (MVG).

This integration is not affiliated with, endorsed by, or sponsored by MVG, MVV,
or Stadtwerke München.

## Overview

The integration is one **MVG** entry with a **station** for every stop you
add. Each station is a device with a departure sensor for every line and
direction you pick, a disruption sensor for every line, and a count of the
station's service messages. A `munich_public_transport.get_departures` action
returns the full list of upcoming departures, with destinations, delays and
platforms, for dashboards and e-paper displays.

It is built on the standalone
[`munich-transport`](https://github.com/g4bri3lDev/munich-transport) Python
package.

## Use cases

- See when the next U-Bahn, tram or bus leaves on a dashboard, as "in 4 min".
- Draw a departure board on an e-paper display at the front door.
- Get notified when a line you use has a disruption.
- Start automations a few minutes before the train you want to catch.

## Installation

Requires Home Assistant `2026.10.0` or newer.

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=g4bri3lDev&repository=munich_public_transport&category=integration)

### Manual installation

1. Download the latest release from
   [GitHub releases](https://github.com/g4bri3lDev/munich_public_transport/releases).
2. Copy `custom_components/munich_public_transport` into the
   `custom_components` directory of your Home Assistant configuration.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** > **Devices & services** and click **Add integration**.
2. Search for **Munich Public Transport**.
3. Enter a station name, pick the station from the results, and select the
   lines and directions to create sensors for.

This creates the MVG entry with its first station. To add more, open the MVG
entry and click **Add station**. To change which lines and directions a
station has, open the station's **⋮** menu and click **Reconfigure**.

### Configuration parameters

| Step | Parameter | Description |
|---|---|---|
| Search | Station search | Part of a station name, such as `Münchner Freiheit`. |
| Select station | Station | The stop, among stations that share a name. |
| Lines and directions | per transport type | The line/direction pairings to create sensors for, such as `U6 → Klinikum Großhadern`. |
| Lines and directions | Look-ahead | Minutes from now to load departures for, up to 90. `0`, the default, keeps one request per update. A value below what one request already reaches changes nothing. See [Data updates](#data-updates). |

## Entities

Every station is a device with:

| Entity | Description |
|---|---|
| Disruptions | Number of active service messages about the station or its lines. |

for every selected line, for example `U6`:

| Entity | Description |
|---|---|
| `U6 disruption` | On while a service message names the line at this station. |

and for every selected line and direction, for example `U6 → Klinikum Großhadern`:

| Entity | Description | Enabled by default |
|---|---|---|
| `U6 → Klinikum Großhadern` | Timestamp of the next departure. | Yes |
| … following departure | Timestamp of the departure after next. | No |

Entity names and IDs use the regular terminus from MVG's schedule catalog, or
for lines outside it, such as the S-Bahn, the end station the line goes to in
MVV's timetable. Trains that split further down the line are named after
both halves, for example `S1 → Flughafen München / Freising`. Names stay the
same when trains turn short during construction.

Where split trains part, at Neufahrn for the S1 and at Dachau for the S2,
each branch is a direction of its own, for example `S1 → Flughafen München`
and `S1 → Freising`. A branch skips trains to the other branch; trains that
end before the split, for example during construction, count for both.

A line that is in neither, such as one MVG reports without any departure
during setup, is offered once for all its directions and named after the line
alone, for example `S7`.

Cancelled departures are skipped. Timestamps show as relative times such as
"in 4 min" in the dashboard. The live destination, delay, platform and the
full list of departures come from the `get_departures` action.

## Actions

### `munich_public_transport.get_departures`

Returns the upcoming departures and relevant service messages of a station.
It answers from the data the integration already fetched, so calling it adds
no requests to MVG.

| Field | Description |
|---|---|
| `device_id` | The station device. |

Every departure of the station's selected directions is included, cancelled
ones too, from the departures MVG reports: 30 for the whole station, plus
later ones when the station has a look-ahead. Each has `line`,
`transport_type`, `network`, `replacement_service`, `destination`,
`direction` (the selected direction id, such as `SUBWAY:U6:H`),
`direction_key`, `planned_departure`, `realtime_departure`,
`minutes_until_departure`, `delay`, `cancelled`, `realtime`, `platform`,
`platform_changed` and `occupancy`. Messages have
`title`, `description`, `type`, `lines`, `valid_from` and `valid_to`.

Replacement buses carry the label of the line they replace, so they count as
that line's departures, also for the departure sensors. `replacement_service`
is `true` for them and `transport_type` is `BUS`. MVG sometimes gives them the
opposite direction of the trains, so a bus can show up in the wrong direction;
filter them with `rejectattr('replacement_service')` where that matters.

## Examples

### Template sensor with the next three departures

```yaml
template:
  - triggers:
      - trigger: time_pattern
        minutes: /1
    actions:
      - action: munich_public_transport.get_departures
        data:
          device_id: YOUR_STATION_DEVICE_ID
        response_variable: board
    sensor:
      - name: Next departures
        state: >
          {{ board.departures | rejectattr('cancelled') | map(attribute='minutes_until_departure')
             | list | first(default='unknown') }}
        attributes:
          departures: >
            {{ (board.departures | rejectattr('cancelled') | list)[:3] }}
```

### Remind me to leave for the train

The departure sensors are timestamps, so a template trigger can fire a few
minutes before the next train:

```yaml
automation:
  - triggers:
      - trigger: template
        value_template: >
          {% set departure = states('sensor.munchner_freiheit_u6_klinikum_grosshadern')
             | as_datetime(None) %}
          {{ departure is not none and now() >= departure - timedelta(minutes=6) }}
    actions:
      - action: notify.mobile_app_phone
        data:
          message: Leave now for the U6 to Klinikum Großhadern.
```

### Notify about a disruption on your line

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.munchner_freiheit_u6_disruption
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: The U6 has a disruption at Münchner Freiheit.
```

## Data updates

Each station polls MVG's live departures every minute, and one request
every 30 minutes fetches the service messages for all stations. When MVG
answers with HTTP 429 or a 5xx status, the integration waits for the time MVG
asks for, up to 15 minutes, before trying again. Entities become unavailable
while MVG can't be reached and recover on their own.

MVG answers at most 30 departures per request, for all lines of the station
together, and it can include departures that already left. At busy stations
that reaches only about 15 to 20 minutes ahead, too little to plan a
transfer. A station's look-ahead asks MVG for later departures, starting
where the previous answer is complete to, until the look-ahead is covered.
That takes up to five more requests per update, so set it only on the
stations that need it. Change it with **Reconfigure**. If one of these
requests fails, the update fails as a whole, as when the first one does.

## Known limitations

- MVG's live departure API returns 30 departures per request. At busy
  stations such as Sendlinger Tor that covers only the next 20 minutes; a
  look-ahead extends it.
- The directions of lines outside MVG's schedule catalog, such as the S-Bahn
  and regional trains, come from MVV's timetable as of the installed release.
  A line missing from it gets its directions from departures sampled across
  the day while you set the station up, and a direction without a departure
  in those samples can't be selected until you reconfigure the station.
- The data comes from MVG's unofficial web API, which can change without
  notice.

## Upgrading from earlier versions

Stations from 1.x and from releases before the rewrite are migrated
automatically on the first start:

- All stations become subentries of one MVG entry. Device IDs are kept, and
  entities keep their entity IDs where there is a direct successor: the line
  sensors become the departure sensors and `messages` becomes `disruptions`.
- **States are now timestamps** instead of minutes, and sensors no longer
  carry departure data as attributes: the `departures` lists, details such as
  `destination`, `delay` and `platform`, and the `messages` list all come
  from the `get_departures` action now. The "All departures" and "Next
  departure" sensors are removed.
- Disruptions are one binary sensor per line, next to the station's
  "Disruptions" count.
- Legacy directions are matched against MVG's schedule catalog, including
  small spelling differences. Directions that no longer exist are removed and
  logged.
- A disabled station stays disabled: its device is disabled instead of the
  whole MVG entry.
- If MVG can't be reached during the upgrade, Home Assistant retries the
  migration of that station on its own.

## Troubleshooting

- **A station can't be found:** try a shorter or more specific name.
- **No lines or directions to select:** MVG may not publish a schedule catalog
  for that station or transport type.
- **Entities are unavailable:** MVG is unreachable or rate limiting. Check the
  log for `munich_public_transport`; the entities recover on their own.
- **Entity names say "unknown":** the schedule catalog was unreachable when the
  integration started. They update on the next reload.
- **Something else:** download the diagnostics from the MVG entry's **⋮** menu
  and attach them to an
  [issue](https://github.com/g4bri3lDev/munich_public_transport/issues).

## Removal

1. Go to **Settings** > **Devices & services** > **Munich Public Transport**.
2. To remove one station, open its **⋮** menu and click **Delete**. To remove
   everything, open the MVG entry's **⋮** menu and click **Delete**.
3. If you installed through HACS, remove the repository there as well.

## Development

The test suite runs on
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component),
managed with [uv](https://docs.astral.sh/uv/):

```bash
scripts/setup             # create the environment
scripts/test              # run against the latest pinned Home Assistant
scripts/test --min-ha     # run against the minimum supported version
scripts/lint              # ruff fix and format
uv run mypy               # strict type check
```

CI runs both Home Assistant versions, ruff and mypy on every pull request.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE)
for details.
