"""Channel-to-workspace directory mapping.

Maps Discord channel names to working directories using the convention:
    BASE_DIR / channel_name

Supports manual overrides via /workspace bind.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("discord_bot")


class WorkspaceManager:
    """Maps Discord channels to working directories."""

    def __init__(self, base_dir: str, overrides_file: Path):
        self._base_dir = Path(base_dir)
        self._file = overrides_file
        self._overrides: dict[int, str] = {}  # channel_id -> abs path
        self._load()

    # ------------------------------------------------------------------
    # Persistence (for manual overrides only)
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
            self._overrides = {int(k): v for k, v in raw.items()}
            logger.info("Loaded %d workspace override(s)", len(self._overrides))
        except Exception as e:
            logger.warning("Failed to load workspaces: %s", e)

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps(
                    {str(k): v for k, v in self._overrides.items()},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save workspaces: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_path(self, channel_id: int, channel_name: str) -> str:
        """Resolve working directory for a channel.

        Priority:
          1. Manual override (from /workspace bind)
          2. AUTO: BASE_DIR / channel_name (case-insensitive match on existing dirs)

        Creates the directory if it doesn't exist.
        """
        if channel_id in self._overrides:
            path = Path(self._overrides[channel_id])
        else:
            path = self._base_dir / channel_name
            if not path.exists() and self._base_dir.is_dir():
                # Discord channel names are lowercase: #sixdad -> BASE_DIR/SixDad
                for d in self._base_dir.iterdir():
                    if d.is_dir() and d.name.lower() == channel_name.lower():
                        path = d
                        break
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def is_override(self, channel_id: int) -> bool:
        """Return True if this channel has a manual override."""
        return channel_id in self._overrides

    def bind(self, channel_id: int, directory: str) -> None:
        """Manually bind a channel to a specific directory."""
        self._overrides[channel_id] = directory
        self._save()
        logger.info("Workspace bound: ch:%s -> %s", channel_id, directory)

    def unbind(self, channel_id: int) -> bool:
        """Remove manual override. Returns True if one existed."""
        if channel_id in self._overrides:
            del self._overrides[channel_id]
            self._save()
            logger.info("Workspace unbound: ch:%s", channel_id)
            return True
        return False

    @property
    def base_dir(self) -> str:
        return str(self._base_dir)

    def all_overrides(self) -> dict[int, str]:
        """Return a copy of all manual overrides."""
        return dict(self._overrides)
