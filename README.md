# MariaDB Export

MariaDB Export is a [Home Assistant](https://www.home-assistant.io/) custom integration, built for [HACS](https://www.hacs.xyz/), that writes recorder history out of MariaDB or MySQL.

It reads states, events, hourly statistics, 5-minute statistics, and recorder runs. It can also run one read-only `SELECT` against the same database. Files land in your config directory as CSV, JSON, or JSON Lines. Nothing in this integration writes to the recorder tables.

Home Assistant 2025.1 or newer is required. The integration targets the current recorder schema (entity ids in `states_meta`, attributes in `state_attributes`, times as UTC Unix timestamps) and older schemas that still store `entity_id` and attributes on `states`.

## Install with HACS

1. Publish this repository on GitHub, or use your fork.
2. In HACS, open **Integrations**, then **Custom repositories**.
3. Add the repository URL and choose category **Integration**.
4. Download **MariaDB Export**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration** and choose **MariaDB Export**.

The manifest links to `https://github.com/Daniel-Shoji/ha-mariadb-export`. If you publish under a different name, change `documentation`, `issue_tracker`, and `codeowners` in `custom_components/mariadb_export/manifest.json` before you tag a release.

## Install by hand

Copy `custom_components/mariadb_export` into your Home Assistant `config/custom_components` directory. Restart, then add the integration. Home Assistant installs `PyMySQL` from the manifest.

## Connect

Use a dedicated account that can only read the recorder database:

```sql
CREATE USER 'ha_export'@'%' IDENTIFIED BY 'a long password';
GRANT SELECT ON homeassistant.* TO 'ha_export'@'%';
FLUSH PRIVILEGES;
```

The config flow can also use the recorder URL that is already in Home Assistant. That password is read when an export runs and is not copied into this integration. The recorder account can write, so the read-only user above is the better choice.

On the options screen you can change:

- the folder inside the config directory (default `mariadb_export`)
- the default file format
- the row limit used when an action omits one (default 250000, maximum 2000000)
- the statement timeout in seconds (`0` leaves the query uncapped)

The **Last export** sensor reports `idle`, `running`, `success`, or `error`, plus the file path, row count, and whether the file was cut off by the limit.

## Export history

Developer tools and automations call `mariadb_export.export`. Times are UTC. If you omit both start and end, the action uses a recent window: 1 day of states or events, 31 days of hourly statistics, 2 days of 5-minute statistics, or 365 days of recorder runs. The end is exclusive.

```yaml
action: mariadb_export.export
data:
  dataset: states
  start: "{{ now() - timedelta(hours=24) }}"
  entity_id:
    - sensor.living_room_temperature
  changed_only: true
  format: csv
response_variable: exported
```

`changed_only` keeps rows where the state value changed and leaves out attribute-only updates. In the current schema, `last_changed_ts` is null when it is the same as `last_updated_ts`; the CSV still fills `last_changed` with that time and keeps the raw `last_changed_ts` empty so you can tell the two cases apart.

Hourly statistics for the last month:

```yaml
action: mariadb_export.export
data:
  dataset: statistics
  start: "{{ (now() - timedelta(days=31)).isoformat() }}"
  entity_id:
    - sensor.living_room_temperature
  format: csv
```

For statistics, `entity_id` is accepted as the statistic id. `state_changed` is stored in `states`, not in `events`.

A custom read:

```yaml
action: mariadb_export.export
data:
  dataset: custom
  format: jsonl
  query: >
    SELECT statistic_id, unit_of_measurement
    FROM statistics_meta
    ORDER BY statistic_id
```

The response looks like this:

```yaml
path: mariadb_export/states_20260101T000000Z_20260102T000000Z_20260102T120000123456Z.csv
rows: 1200
truncated: false
last_id: 88421
last_time: "2026-01-01T23:59:10+00:00"
bytes: 240115
dataset: states
format: csv
warnings: []
```

`path` is relative to the Home Assistant config directory. When `truncated` is true, call the action again with the same start and end, and set `after_time` and `after_id` to `last_time` and `last_id`.

The same payload is fired on `mariadb_export_completed`.

Custom SQL has to be one `SELECT` or `WITH` query. `INSERT`, `UPDATE`, `DELETE`, `INTO OUTFILE`, `SLEEP`, and a second statement are rejected before they are sent. That check is a backstop. The read-only account is what actually protects the database. Words such as `update` and `delete` are rejected even inside an otherwise valid `SELECT`, including when they are used as identifiers.

## Files

| Dataset | What it contains |
| --- | --- |
| `states` | One row per recorded state. `entity_id`, `state`, optional attribute JSON, and UTC times. |
| `events` | Recorder events other than `state_changed`, with optional event data. |
| `statistics` | Hourly long-term statistics, including `mean`, `min`, `max`, `state`, and `sum`. |
| `statistics_short_term` | The same columns, for 5-minute statistics. |
| `recorder_runs` | When Home Assistant started and stopped. |
| `custom` | The columns returned by your `SELECT`. |

`mean_type` is written as `none`, `arithmetic`, or `circular`, with the original integer in `mean_type_value`. Context ids are included only when **Include context** is on, as hexadecimal strings.

## Develop

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The export engine under `custom_components/mariadb_export/exporter` has no Home Assistant import, and the tests cover it without a running database. GitHub Actions also runs hassfest and the HACS validation action.
