"""Config flow for MariaDB Export."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .connection import (
    manual_entry_data,
    recorder_entry_data,
    resolve_connection,
    title_for,
    unique_id_for,
)
from .const import (
    CONF_DATABASE,
    CONF_DEFAULT_FORMAT,
    CONF_DEFAULT_LIMIT,
    CONF_EXPORT_DIR,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SOURCE,
    CONF_SSL,
    CONF_STATEMENT_TIMEOUT,
    CONF_UNIX_SOCKET,
    CONF_USERNAME,
    DEFAULT_OPTIONS,
    DOMAIN,
    MAX_LIMIT,
    MAX_STATEMENT_TIMEOUT,
    SOURCE_MANUAL,
    SOURCE_RECORDER,
)
from .exporter.form import connection_from_fields
from .exporter.models import (
    ConnectionConfig,
    ExportError,
    ExportFormat,
    InvalidAuth,
    InvalidConnection,
    NotMariaDBError,
    UnknownDatabase,
)
from .exporter.paths import validate_export_dir
from .exporter.session import ping_database
from .exporter.urls import parse_db_url
from .recorder_url import recorder_database_url
from .types import MariaDBConfigEntry

_MENU = [SOURCE_RECORDER, SOURCE_MANUAL]


class MariaDBExportConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a MariaDB database to export."""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: MariaDBConfigEntry,
    ) -> MariaDBExportOptionsFlow:
        """Create the options flow."""

        return MariaDBExportOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the recorder database or a manual connection."""

        return self.async_show_menu(step_id="user", menu_options=_MENU)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a new connection for an existing entry."""

        return self.async_show_menu(step_id="reconfigure", menu_options=_MENU)

    async def async_step_recorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the database Home Assistant is already using."""

        url = recorder_database_url(self.hass)
        if not url:
            return self.async_abort(reason="recorder_missing")
        try:
            config = parse_db_url(url)
        except NotMariaDBError as err:
            # Default Home Assistant uses SQLite. Keep the user in the form
            # instead of closing the dialog on an untranslated abort key.
            self._recorder_scheme = err.scheme
            return await self.async_step_manual()
        except ExportError:
            return self.async_abort(reason="invalid_url")
        placeholders = _recorder_placeholders(config)
        if user_input is None:
            return self.async_show_form(
                step_id="recorder",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )
        error = await self._async_test(config)
        if error is not None:
            return self.async_show_form(
                step_id="recorder",
                data_schema=vol.Schema({}),
                errors={"base": error},
                description_placeholders=placeholders,
            )
        return await self._async_finish(config, SOURCE_RECORDER)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter a host, database, and account."""

        errors: dict[str, str] = {}
        scheme = getattr(self, "_recorder_scheme", None)
        if user_input is None and scheme:
            errors["base"] = "not_mariadb"
        if user_input is not None:
            try:
                config = connection_from_fields(
                    host=user_input.get(CONF_HOST),
                    port=user_input.get(CONF_PORT),
                    database=user_input.get(CONF_DATABASE),
                    username=user_input.get(CONF_USERNAME),
                    password=user_input.get(CONF_PASSWORD, ""),
                    unix_socket=user_input.get(CONF_UNIX_SOCKET, ""),
                    ssl=user_input.get(CONF_SSL, False),
                )
            except InvalidConnection as err:
                errors[err.field] = err.code
            else:
                error = await self._async_test(config)
                if error is None:
                    return await self._async_finish(config, SOURCE_MANUAL)
                errors["base"] = error
        suggested = user_input
        if suggested is None:
            suggested = (
                self._manual_suggestion()
                if self.source == SOURCE_RECONFIGURE
                else {CONF_PORT: 3306, CONF_SSL: False}
            )
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                _manual_schema(), suggested
            ),
            errors=errors,
            description_placeholders={"scheme": scheme or "the current recorder"},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a repair when MariaDB rejects the account."""

        if entry_data.get(CONF_SOURCE) == SOURCE_RECORDER:
            return await self.async_step_reauth_recorder()
        return await self.async_step_reauth_manual()

    async def async_step_reauth_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a replacement password."""

        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                current = resolve_connection(entry.data, None)
                config = connection_from_fields(
                    host=current.host,
                    port=current.port,
                    database=current.database,
                    username=current.username,
                    password=user_input.get(CONF_PASSWORD, ""),
                    unix_socket=current.unix_socket or "",
                    ssl=current.ssl,
                )
            except InvalidConnection as err:
                errors[err.field] = err.code
            else:
                error = await self._async_test(config)
                if error is None:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_PASSWORD: config.password},
                    )
                errors["base"] = error
        return self.async_show_form(
            step_id="reauth_manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth_recorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry the recorder account after its password is fixed."""

        errors: dict[str, str] = {}
        if user_input is not None:
            url = recorder_database_url(self.hass)
            if not url:
                return self.async_abort(reason="recorder_missing")
            try:
                config = parse_db_url(url)
            except NotMariaDBError as err:
                return self.async_abort(
                    reason="not_mariadb",
                    description_placeholders={"scheme": err.scheme},
                )
            except ExportError:
                return self.async_abort(reason="invalid_url")
            error = await self._async_test(config)
            if error is None:
                return self.async_update_reload_and_abort(self._get_reauth_entry())
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_recorder",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def _async_test(self, config: ConnectionConfig) -> str | None:
        try:
            await self.hass.async_add_executor_job(ping_database, config)
        except InvalidAuth:
            return "invalid_auth"
        except UnknownDatabase:
            return "unknown_database"
        except ExportError:
            return "cannot_connect"
        return None

    async def _async_finish(
        self, config: ConnectionConfig, source: str
    ) -> ConfigFlowResult:
        unique_id = unique_id_for(source, config)
        title = title_for(source, config)
        data = (
            recorder_entry_data()
            if source == SOURCE_RECORDER
            else manual_entry_data(config)
        )
        await self.async_set_unique_id(unique_id)
        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_configured(reload_on_update=False)
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                title=title,
                data=data,
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=title, data=data, options=dict(DEFAULT_OPTIONS)
        )

    def _manual_suggestion(self) -> dict[str, Any]:
        entry = self._get_reconfigure_entry()
        try:
            config = resolve_connection(entry.data, recorder_database_url(self.hass))
        except ExportError:
            return {CONF_PORT: 3306, CONF_SSL: False}
        suggestion = {
            CONF_HOST: "" if config.unix_socket else config.host,
            CONF_PORT: config.port,
            CONF_DATABASE: config.database,
            CONF_USERNAME: config.username,
            CONF_UNIX_SOCKET: config.unix_socket or "",
            CONF_SSL: config.ssl,
        }
        if entry.data.get(CONF_SOURCE) == SOURCE_MANUAL:
            suggestion[CONF_PASSWORD] = config.password
        return suggestion


class MariaDBExportOptionsFlow(OptionsFlow):
    """Choose the export folder, format, and limits."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit export options."""

        errors: dict[str, str] = {}
        if user_input is not None:
            export_dir = str(user_input[CONF_EXPORT_DIR]).strip()
            try:
                validate_export_dir(Path(self.hass.config.config_dir), export_dir)
                limit = int(user_input[CONF_DEFAULT_LIMIT])
                timeout = int(user_input[CONF_STATEMENT_TIMEOUT])
            except ExportError:
                errors["base"] = "invalid_export_dir"
            except (TypeError, ValueError):
                errors["base"] = "invalid_limit"
            else:
                if limit < 1 or limit > MAX_LIMIT:
                    errors[CONF_DEFAULT_LIMIT] = "invalid_limit"
                elif timeout < 0 or timeout > MAX_STATEMENT_TIMEOUT:
                    errors[CONF_STATEMENT_TIMEOUT] = "invalid_timeout"
                else:
                    return self.async_create_entry(
                        data={
                            CONF_EXPORT_DIR: export_dir,
                            CONF_DEFAULT_FORMAT: user_input[CONF_DEFAULT_FORMAT],
                            CONF_DEFAULT_LIMIT: limit,
                            CONF_STATEMENT_TIMEOUT: timeout,
                        }
                    )
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(_options_schema(), current),
            errors=errors,
        )


def _manual_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST): TextSelector(),
            vol.Required(CONF_PORT): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode=NumberSelectorMode.BOX,
                    step=1,
                )
            ),
            vol.Required(CONF_DATABASE): TextSelector(),
            vol.Required(CONF_USERNAME): TextSelector(),
            vol.Optional(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_UNIX_SOCKET): TextSelector(),
            vol.Required(CONF_SSL): BooleanSelector(),
        }
    )


def _options_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EXPORT_DIR): TextSelector(),
            vol.Required(CONF_DEFAULT_FORMAT): SelectSelector(
                SelectSelectorConfig(
                    options=[item.value for item in ExportFormat],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_DEFAULT_LIMIT): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=MAX_LIMIT,
                    mode=NumberSelectorMode.BOX,
                    step=1,
                )
            ),
            vol.Required(CONF_STATEMENT_TIMEOUT): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=MAX_STATEMENT_TIMEOUT,
                    mode=NumberSelectorMode.BOX,
                    step=1,
                    unit_of_measurement="s",
                )
            ),
        }
    )


def _recorder_placeholders(config: ConnectionConfig) -> dict[str, str]:
    return {
        "host": config.display_host,
        "database": config.database,
        "username": config.username,
    }
