# MariaDB Export

Export Home Assistant recorder history from MariaDB or MySQL to CSV, JSON, or JSON Lines.

Files are written under the config directory, in `mariadb_export` unless you pick another folder. The integration only sends `SELECT` statements. Use a database account with `SELECT` grants.

## Setup

Add the repository to HACS as an integration, download **MariaDB Export**, and restart Home Assistant. Then add the integration.

Choose **Use the recorder database** to read the URL Home Assistant already uses, or enter a host, database, and read-only user. A read-only account is the safer choice:

```sql
CREATE USER 'ha_export'@'%' IDENTIFIED BY 'a long password';
GRANT SELECT ON homeassistant.* TO 'ha_export'@'%';
FLUSH PRIVILEGES;
```

## Export

Call `mariadb_export.export`. Omit the times to use a recent window, or set `start` and `end`. `end` is exclusive and times are UTC.

```yaml
action: mariadb_export.export
data:
  dataset: statistics
  start: "{{ (now() - timedelta(days=31)).isoformat() }}"
  entity_id:
    - sensor.living_room_temperature
  format: csv
response_variable: exported
```

Datasets: `states`, `events`, `statistics`, `statistics_short_term`, `recorder_runs`, and `custom`.

`custom` runs one `SELECT`. Put filters in the query. The response `path` is relative to your config directory. When `truncated` is true, call again with `after_time` and `after_id` set to the returned `last_time` and `last_id`.

The **Last export** sensor shows whether the latest export is idle, running, successful, or failed.
