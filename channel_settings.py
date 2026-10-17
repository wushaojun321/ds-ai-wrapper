"""Per-channel agent settings (model, thinking level) with persistence."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("discord_bot")


class ChannelSettings:
    def __init__(self, settings_file: Path):
        self._file = settings_file
        self._data: dict[int, dict] = {}
        if self._file.exists():
            try:
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                self._data = {int(k): v for k, v in raw.items()}
            except Exception as e:
                logger.warning("Failed to load channel settings: %s", e)

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps({str(k): v for k, v in self._data.items()}, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save channel settings: %s", e)

    def get(self, channel_id: int, key: str) -> str | None:
        return self._data.get(channel_id, {}).get(key)

    def set(self, channel_id: int, key: str, value: str | None) -> None:
        entry = self._data.setdefault(channel_id, {})
        if value:
            entry[key] = value
        else:
            entry.pop(key, None)
        self._save()
