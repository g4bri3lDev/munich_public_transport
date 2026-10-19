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
add. Each station is a device with sensors for its next departures and
disruptions, one set per line and direction you pick. A
`munich_public_transport.get_departures` action returns the full list of
upcoming departures for dashboards and e-paper displays.

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

## Entities

Every station is a device with:

| Entity | Description |
|---|---|
| Disruptions | Number of active service messages about the station or its lines. |

and for every selected line and direction, for example `U6 → Klinikum Großhadern`:

| Entity | Description | Enabled by default |
|---|---|---|
| `U6 → Klinikum Großhadern` | Timestamp of the next departure. | Yes |
| … destination | Where the next train actually goes; differs during short turns such as `Goetheplatz`. | Yes |
| … delay | Delay of the next departure in minutes. | Yes |
| … following departure | Timestamp of the departure after next. | No |
| … platform | Platform of the next departure. | No |
| … disruption | On while a service message names the line at this station. | Yes |

Entity names and IDs use the regular terminus from MVG's schedule catalog, so
they stay the same when trains turn short during construction. Cancelled
departures are skipped. Timestamps show as relative times such as "in 4 min"
in the dashboard.

## Actions

### `munich_public_transport.get_departures`

Returns the upcoming departures and relevant service messages of a station.
It answers from the data the integration already fetched, so calling it adds
no requests to MVG.

| Field | Description |
|---|---|
| `device_id` | The station device. |

Every departure of the station's selected directions is included, cancelled
ones too, up to the roughly 100 departures MVG reports. Each has `line`,
`transport_type`, `network`, `destination`, `direction` (the selected
direction id, such as `SUBWAY:U6:H`), `direction_key`, `planned_departure`,
`realtime_departure`, `minutes_until_departure`, `delay`, `cancelled`,
`realtime`, `platform`, `platform_changed` and `occupancy`. Messages have
`title`, `description`, `type`, `lines`, `valid_from` and `valid_to`.

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

### Notify about a disruption on your line

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.munchner_freiheit_u6_klinikum_grosshadern_disruption
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          message: The U6 to Klinikum Großhadern has a disruption.
```

### E-paper departure board

[`blueprints/automation/munich_public_transport/epaper_departure_board.yaml`](blueprints/automation/munich_public_transport/epaper_departure_board.yaml)
draws the next departures of a station on OpenEPaperLink tags every five
minutes.

## Data updates

Each station polls MVG's live departures every 45 seconds, and one request
every 30 minutes fetches the service messages for all stations. When MVG
answers with HTTP 429 or a 5xx status, the integration waits for the time MVG
asks for, up to 15 minutes, before trying again. Entities become unavailable
while MVG can't be reached and recover on their own.

## Known limitations

- MVG's live departure API returns about 100 departures per station. At busy
  stations such as Sendlinger Tor that covers only the next 40 minutes.
- S-Bahn lines are not in MVG's schedule catalog for most stations, so they
  can't be selected there.
- Stations without a schedule catalog get their selectable directions from the
  departures that are live while you set them up.
- The data comes from MVG's unofficial web API, which can change without
  notice.

## Upgrading from earlier versions

Stations from 1.x and from releases before the rewrite are migrated
automatically on the first start:

- All stations become subentries of one MVG entry. Device IDs are kept, and
  entities keep their entity IDs where there is a direct successor: the line
  sensors become the departure sensors and `messages` becomes `disruptions`.
- **States are now timestamps** instead of minutes, and the `departures`
  attributes are gone. Use the `get_departures` action instead; the
  "All departures" and "Next departure" sensors are removed.
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
