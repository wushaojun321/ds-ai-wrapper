"""Stack-based session manager with history.jsonl parsing."""

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

    # ------------------------------------------------------------------
    # history.jsonl parsing + projects directory scanning
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_display_from_session(filepath: Path) -> str:
        """Extract the first user message from a session .jsonl file as display text."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    text = ""
                    entry_type = entry.get("type")

                    # Bot 创建的会话：首行是 queue-operation enqueue，content 就是用户消息
                    if entry_type == "queue-operation" and entry.get("operation") == "enqueue":
                        text = entry.get("content", "")

                    # 标准 user 消息（排除 isMeta 系统消息）
                    elif entry_type == "user" and not entry.get("isMeta"):
                        msg = entry.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, str):
                                    text = block
                                    break
                                elif isinstance(block, dict) and block.get("type") == "text":
                                    text = block.get("text", "")
                                    break

                    text = text.strip()
                    if text:
                        return (text[:80] + "…") if len(text) > 80 else text
        except Exception as e:
            logger.debug("Failed to extract display from %s: %s", filepath.name, e)

        return "(no display)"

    @staticmethod
    def list_recent_sessions(
        history_file: Path, project: str, limit: int = 20
    ) -> list[dict]:
        """Parse history.jsonl + scan projects directory for recent sessions.

        Returns list of dicts: {session_id, display, timestamp}
        sorted by timestamp descending.
        """
        # session_id -> {display (first message), timestamp (latest)}
        sessions: dict[str, dict] = {}

        # ----- 1. 从 history.jsonl 读取（主要来源，display 更准确）-----
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # Filter by project
                        if entry.get("project") != project:
                            continue

                        sid = entry.get("sessionId")
                        if not sid:
                            continue

                        ts = entry.get("timestamp", 0)
                        # Timestamps in history.jsonl are in milliseconds
                        if ts > 1e12:
                            ts = ts / 1000

                        if sid not in sessions:
                            # First occurrence = display text
                            # history.jsonl 使用 "display" 字段；兼容旧格式 "prompt"
                            raw_display = entry.get("display") or entry.get("prompt", "")
                            display = (raw_display[:80] + "…") if len(raw_display) > 80 else raw_display
                            sessions[sid] = {
                                "session_id": sid,
                                "display": display or "(no display)",
                                "timestamp": ts,
                            }
                        else:
                            # Update to latest timestamp
                            if ts > sessions[sid]["timestamp"]:
                                sessions[sid]["timestamp"] = ts
            except Exception as e:
                logger.warning("Failed to parse history.jsonl: %s", e)

        # ----- 2. 扫描 projects 目录补全缺失的会话 -----
        try:
            projects_dir = history_file.parent / "projects"
            # 将 project 路径转为目录名: /home/evan/SixDad -> -home-evan-SixDad
            dir_name = project.replace("/", "-")
            proj_session_dir = projects_dir / dir_name

            if proj_session_dir.is_dir():
                for f in proj_session_dir.glob("*.jsonl"):
                    sid = f.stem
                    if sid in sessions:
                        continue  # history.jsonl 已有，跳过

                    # 从文件 mtime 获取时间戳
                    ts = f.stat().st_mtime

                    # 尝试从 jsonl 提取 display
                    display = SessionManager._extract_display_from_session(f)

                    sessions[sid] = {
                        "session_id": sid,
                        "display": display,
                        "timestamp": ts,
                    }

                logger.debug(
                    "Projects dir scan: found %d total sessions (%d from history.jsonl)",
                    len(sessions),
                    len([s for s in sessions.values() if s.get("_from_history")]),
                )
        except Exception as e:
            logger.warning("Failed to scan projects directory: %s", e)

        # ----- 3. 排序返回 -----
        result = sorted(sessions.values(), key=lambda x: x["timestamp"], reverse=True)
        return result[:limit]
