from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class BackgroundTaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    completed = Signal()


class BackgroundTask(QRunnable):
    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function
        self.signals = BackgroundTaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.function())
        except Exception as error:
            self.signals.failed.emit(error)
        finally:
            self.signals.completed.emit()
