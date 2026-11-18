# From setup to your first export

This is the path from an empty Home Assistant to a file of recorder history. The integration is [MariaDB Export](https://github.com/Daniel-Shoji/MariaDB-Export).

## 1. Add the repository in HACS

1. Open HACS, then **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Paste this URL:

   `https://github.com/Daniel-Shoji/MariaDB-Export`

4. Category: **Integration**.
5. Download **MariaDB Export**.
6. Restart Home Assistant when HACS asks you to.

## 2. Start the setup dialog

Go to **Settings → Devices & services → Add integration** and choose **MariaDB Export**.

The first screen has two choices:

| Choice | When to use it |
| --- | --- |
| Use the recorder database | Home Assistant is already writing history to MariaDB or MySQL. |
| Enter a MariaDB connection | Home Assistant is still on SQLite, or you want a separate read-only user. |

A new Home Assistant uses SQLite. Choosing **Use the recorder database** then opens the connection form and explains that. It does not close the dialog.

## 3. Fill in the connection

| Field | What to type |
| --- | --- |
| Host | `core-mariadb` for the official MariaDB add-on. An address such as `192.168.1.20` for a database on another computer. Leave blank only when you use a Unix socket. |
| Port | `3306`, unless you changed the server port. |
| Database | `homeassistant`, unless you named the recorder database something else. |
| Username | The MariaDB user that can read that database, for example `ha_export`. |
| Password | That user's password. Leave it empty only when the account has no password. |
| Unix socket | Leave empty for a normal host and port. On the same machine as MariaDB, a path such as `/run/mysqld/mysqld.sock`. |
| Use SSL | Off for a local add-on. On only when that server requires encryption. |

Create the read-only user in MariaDB first:

```sql
CREATE USER 'ha_export'@'%' IDENTIFIED BY 'a long password';
GRANT SELECT ON homeassistant.* TO 'ha_export'@'%';
FLUSH PRIVILEGES;
```

Submit. A successful test adds the integration. The **Last export** sensor stays idle until you run an export.

## 4. Create an export

Open **Developer tools → Actions**. Choose **MariaDB Export: Export data**.

For the last 31 days of hourly statistics:

```yaml
action: mariadb_export.export
data:
  dataset: statistics
  start: "{{ (now() - timedelta(days=31)).isoformat() }}"
  format: csv
```

Run the action. The response `path` is relative to your config directory, usually:

`mariadb_export/statistics_....csv`

Open that file from the File editor, Samba, or the Studio Code Server add-on.

Other datasets are `states`, `events`, `statistics_short_term`, `recorder_runs`, and `custom` for one `SELECT`. Leave start and end empty to use a recent window. When `truncated` is true, run the action again with the same start and end, and set `after_time` and `after_id` to the returned `last_time` and `last_id`.
