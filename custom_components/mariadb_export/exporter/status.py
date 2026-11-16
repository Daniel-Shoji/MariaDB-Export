"""In-memory status of the latest export."""

from __future__ import annotations

from collections.abc import Callable

from .models import RunStatus


class ExportStatus:
    """Mutable status shared by the export action and the sensor."""

    def __init__(self) -> None:
        """Start idle, before any export has run."""

        self.state = RunStatus.IDLE
        self.rows: int | None = None
        self.dataset: str | None = None
        self.export_format: str | None = None
        self.file: str | None = None
        self.truncated = False
        self.error: str | None = None
        self.finished_at: str | None = None
        self.warnings: tuple[str, ...] = ()
        self.server_version: str | None = None
        self.last_id: int | None = None
        self.last_time: str | None = None
        self._listeners: list[Callable[[], None]] = []

    def listen(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener and return an unsubscribe callback."""

        self._listeners.append(listener)

        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    def notify(self) -> None:
        """Tell listeners that the status changed."""

        for listener in tuple(self._listeners):
            listener()

    def mark_running(self, dataset: str) -> None:
        """Record that an export has started."""

        self.state = RunStatus.RUNNING
        self.dataset = dataset
        self.error = None
        self.notify()

    def mark_success(
        self,
        *,
        rows: int,
        dataset: str,
        export_format: str,
        file: str,
        truncated: bool,
        warnings: tuple[str, ...],
        last_id: int | None,
        last_time: str | None,
        finished_at: str,
    ) -> None:
        """Record a finished export."""

        self.state = RunStatus.SUCCESS
        self.rows = rows
        self.dataset = dataset
        self.export_format = export_format
        self.file = file
        self.truncated = truncated
        self.error = None
        self.warnings = warnings
        self.last_id = last_id
        self.last_time = last_time
        self.finished_at = finished_at
        self.notify()

    def mark_error(self, message: str, *, finished_at: str) -> None:
        """Record a failed export and keep the previous success details."""

        self.state = RunStatus.ERROR
        self.error = message
        self.finished_at = finished_at
        self.notify()
