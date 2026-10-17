"""Stack-based per-channel session manager."""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("discord_bot")


class SessionManager:
    """Manage per-channel session stacks with persistence."""

    def __init__(self, sessions_file: Path):
        self._file = sessions_file
        self._data: dict[int, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load sessions: %s", e)
            return

        # Auto-migrate from old format {"channel_id": "uuid"}
        for k, v in raw.items():
            cid = int(k)
            if isinstance(v, str):
                # Old format — convert to stack
                self._data[cid] = {
                    "current_index": 0,
                    "stack": [
                        {
                            "session_id": v,
                            "display": "(migrated)",
                            "created_at": int(time.time()),
                        }
                    ],
                }
                logger.info("[ch:%s] Migrated old session format", cid)
            elif isinstance(v, dict):
                self._data[cid] = v
            else:
                logger.warning("[ch:%s] Skipping unknown format", cid)

        logger.info("Loaded %d channel session(s)", len(self._data))
        # Persist migration if any old-format entries were converted
        self._save()

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps(
                    {str(k): v for k, v in self._data.items()},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save sessions: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_current(self, channel_id: int) -> str | None:
        """Return current session_id for a channel, or None."""
        entry = self._data.get(channel_id)
        if not entry or not entry["stack"]:
            return None
        idx = entry["current_index"]
        if 0 <= idx < len(entry["stack"]):
            return entry["stack"][idx]["session_id"]
        return None

    def push_new(self, channel_id: int, session_id: str, display: str) -> None:
        """Push a new session onto the stack and make it current."""
        item = {
            "session_id": session_id,
            "display": display[:120],
            "created_at": int(time.time()),
        }
        if channel_id not in self._data:
            self._data[channel_id] = {"current_index": 0, "stack": [item]}
        else:
            stack = self._data[channel_id]["stack"]
            stack.insert(0, item)  # newest on top
            self._data[channel_id]["current_index"] = 0
        self._save()
        logger.info("[ch:%s] Pushed session %s", channel_id, session_id)

    def back(self, channel_id: int, n: int = 1) -> str | None:
        """Move current_index forward by n (toward older sessions). Return new session_id or None."""
        entry = self._data.get(channel_id)
        if not entry or not entry["stack"]:
            return None
        new_idx = entry["current_index"] + n
        if new_idx >= len(entry["stack"]):
            return None  # can't go back further
        entry["current_index"] = new_idx
        self._save()
        sid = entry["stack"][new_idx]["session_id"]
        logger.info("[ch:%s] Back %d → session %s (idx %d)", channel_id, n, sid, new_idx)
        return sid

    def switch_to(self, channel_id: int, session_id: str) -> bool:
        """Switch current to a specific session_id in the stack. Returns True if found."""
        entry = self._data.get(channel_id)
        if not entry:
            return False
        for i, item in enumerate(entry["stack"]):
            if item["session_id"] == session_id:
                entry["current_index"] = i
                self._save()
                logger.info("[ch:%s] Switched to session %s (idx %d)", channel_id, session_id, i)
                return True
        return False

    def get_stack(self, channel_id: int) -> list[dict]:
        """Return the full stack for a channel (newest first)."""
        entry = self._data.get(channel_id)
        if not entry:
            return []
        return list(entry["stack"])

    def get_current_index(self, channel_id: int) -> int:
        """Return current_index for a channel."""
        entry = self._data.get(channel_id)
        if not entry:
            return 0
        return entry["current_index"]

    def clear(self, channel_id: int) -> None:
        """Mark channel to start a fresh session next time, without losing history."""
        entry = self._data.get(channel_id)
        if entry:
            # Set index to -1 to signal "no current session"
            entry["current_index"] = -1
            self._save()
        logger.info("[ch:%s] Session cleared (stack preserved)", channel_id)
