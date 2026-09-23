from datetime import datetime
from pathlib import Path


class ActivityLog:
    """Kalıcı, sade metin işlem günlüğü."""

    def __init__(self) -> None:
        self.path = Path(__file__).resolve().parents[2] / "logs" / "sync.log"

    def write(self, level: str, message: str) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_if_needed()
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} | {level.upper():7} | {message}"
        with self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
        return line

    def clear(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def _rotate_if_needed(self, max_bytes: int = 2 * 1024 * 1024) -> None:
        if not self.path.exists() or self.path.stat().st_size < max_bytes:
            return
        archive = self.path.with_name(f"sync-{datetime.now():%Y%m%d-%H%M%S}.log")
        self.path.replace(archive)

    def read_tail(self, line_count: int = 1000) -> str:
        if not self.path.exists():
            return ""
        with self.path.open("r", encoding="utf-8", errors="replace") as file:
            lines = file.readlines()
        return "".join(lines[-line_count:])
