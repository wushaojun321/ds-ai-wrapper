"""Wrapper around the pi coding agent CLI (JSON event stream mode)."""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger("discord_bot")

PI_CMD = os.getenv("PI_CMD", "pi")
PI_PROVIDER = os.getenv("PI_PROVIDER", "openrouter")
PI_MODEL = os.getenv("PI_MODEL", "deepseek/deepseek-v4.1-flash")
PI_THINKING = os.getenv("PI_THINKING", "")  # empty = pi default
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "1800"))

# Proxy vars are stripped from the agent env: model APIs are reached directly,
# only the Discord connection goes through a proxy (see DISCORD_PROXY).
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@dataclass
class Step:
    """One tool call, for progress display."""
    tool: str
    summary: str
    done: bool = False
    error: bool = False


@dataclass
class Progress:
    """Live state of a run, updated as events arrive."""
    steps: list[Step] = field(default_factory=list)
    text: str = ""          # assistant text of the current turn (streaming)
    thinking: bool = False
    retry: str = ""
    compacting: bool = False


@dataclass
class RunResult:
    text: str
    session_id: str | None
    error: str | None = None
    aborted: bool = False
    cost: float = 0.0
    context_tokens: int = 0
    model: str = ""
    steps: int = 0


def summarize_args(tool: str, args: dict) -> str:
    """Short one-line description of a tool call."""
    if not isinstance(args, dict):
        return ""
    for key in ("command", "path", "file_path", "query", "url", "pattern"):
        if args.get(key):
            s = args[key]
            break
    else:
        s = json.dumps(args, ensure_ascii=False)
    s = " ".join(str(s).split())
    return (s[:80] + "…") if len(s) > 80 else s


def _text_of(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
    )


class PiAgent:
    """Encapsulate pi CLI invocations and its session files."""

    def __init__(self, sessions_root: Path, cmd: str = PI_CMD, timeout: int = COMMAND_TIMEOUT):
        self.cmd = cmd
        self.timeout = timeout
        self.provider = PI_PROVIDER
        self.default_model = PI_MODEL
        self.default_thinking = PI_THINKING
        self._root = sessions_root
        self._procs: dict[int, asyncio.subprocess.Process] = {}  # channel_id -> running proc
        self._stopped: set[int] = set()

    # ------------------------------------------------------------------
    # Session storage — one directory per workspace
    # ------------------------------------------------------------------
    def session_dir(self, cwd: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", cwd).strip("-") or "root"
        d = self._root / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def find_session_file(self, cwd: str, session_id: str) -> Path | None:
        matches = sorted(self.session_dir(cwd).glob(f"*_{session_id}*.jsonl"))
        return matches[-1] if matches else None

    def list_sessions(self, cwd: str, limit: int = 75) -> list[dict]:
        """Return [{session_id, display, timestamp}] newest first."""
        result = []
        for f in self.session_dir(cwd).glob("*.jsonl"):
            sid, display, name = None, "", ""
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if e.get("type") == "session":
                            sid = e.get("id")
                        elif e.get("type") == "session_info":
                            name = e.get("name") or name
                        elif not display and e.get("type") == "message" \
                                and e.get("message", {}).get("role") == "user":
                            display = _text_of(e["message"]).strip()
            except Exception as ex:
                logger.debug("Failed to read session %s: %s", f.name, ex)
                continue
            if not sid:
                continue
            display = name or display or "(no display)"
            result.append({
                "session_id": sid,
                "display": (display[:80] + "…") if len(display) > 80 else display,
                "timestamp": f.stat().st_mtime,
            })
        result.sort(key=lambda x: x["timestamp"], reverse=True)
        return result[:limit]

    def read_messages(self, cwd: str, session_id: str) -> list[tuple[str, str]] | None:
        """Return [(role, text)] for user/assistant messages, or None if not found."""
        f = self.find_session_file(cwd, session_id)
        if not f:
            return None
        out = []
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "message":
                    continue
                msg = e.get("message", {})
                if msg.get("role") in ("user", "assistant"):
                    text = _text_of(msg).strip()
                    if text:
                        out.append((msg["role"], text))
        return out

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def is_running(self, channel_id: int) -> bool:
        return channel_id in self._procs

    def stop(self, channel_id: int) -> bool:
        proc = self._procs.get(channel_id)
        if not proc:
            return False
        self._stopped.add(channel_id)
        proc.terminate()
        return True

    async def run(
        self,
        prompt: str,
        *,
        cwd: str,
        channel_id: int,
        session_id: str | None = None,
        fork_from: str | None = None,
        continue_latest: bool = False,
        model: str | None = None,
        thinking: str | None = None,
        files: list[str] | None = None,
        on_progress: Callable[[Progress], Awaitable[None]] | None = None,
    ) -> RunResult:
        """Run one prompt. Exactly one of session_id / fork_from / continue_latest
        may be given; with none, a new session is created."""
        model = model or self.default_model
        thinking = thinking or self.default_thinking
        cmd = [
            self.cmd, "-p", "--mode", "json",
            "--provider", self.provider, "--model", model,
            "--session-dir", str(self.session_dir(cwd)),
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if fork_from:
            cmd += ["--fork", fork_from]
        elif continue_latest:
            cmd += ["--continue"]
        else:
            cmd += ["--session-id", session_id or str(uuid.uuid4())]
        cmd += [f"@{p}" for p in files or []]
        cmd += ["--", prompt]

        env = {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}
        logger.debug("CMD (cwd=%s): %s", cwd, " ".join(cmd[:-1]))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,  # pi waits on stdin otherwise
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            limit=64 * 1024 * 1024,  # agent_end lines carry the whole run
        )
        self._procs[channel_id] = proc
        self._stopped.discard(channel_id)
        result = RunResult(text="", session_id=session_id, model=model)
        progress = Progress()
        try:
            await asyncio.wait_for(
                self._consume(proc, result, progress, on_progress), timeout=self.timeout
            )
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("pi timeout after %ss", self.timeout)
            result.error = f"⏰ 运行超时（超过 {self.timeout}s）"
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        finally:
            self._procs.pop(channel_id, None)

        stderr = (await proc.stderr.read()).decode(errors="replace").strip()
        if stderr:
            logger.warning("pi stderr: %s", stderr[:500])
        if channel_id in self._stopped:
            self._stopped.discard(channel_id)
            result.aborted = True
        elif not result.text and not result.error:
            result.error = stderr[:1500] or "未收到任何回复"
        logger.info("pi done: sid=%s len=%d cost=$%.4f", result.session_id, len(result.text), result.cost)
        return result

    async def _consume(self, proc, result: RunResult, progress: Progress, on_progress) -> None:
        steps: dict[str, Step] = {}
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type")
            changed = False

            if t == "session":
                result.session_id = e.get("id")
            elif t == "message_update":
                ev = e.get("assistantMessageEvent", {})
                et = ev.get("type")
                if et == "thinking_start":
                    progress.thinking, changed = True, True
                elif et == "thinking_end":
                    progress.thinking, changed = False, True
                elif et == "text_delta":
                    progress.text += ev.get("delta", "")
                    progress.thinking = False
                    changed = True
            elif t == "message_end":
                msg = e.get("message", {})
                if msg.get("role") == "assistant":
                    usage = msg.get("usage") or {}
                    result.cost += (usage.get("cost") or {}).get("total", 0) or 0
                    result.context_tokens = usage.get("totalTokens", result.context_tokens)
                    result.model = msg.get("model") or result.model
                    if msg.get("stopReason") == "error":
                        result.error = msg.get("errorMessage") or "模型返回错误"
                    text = _text_of(msg).strip()
                    if text:
                        result.text = text
                    progress.text = ""
                    changed = True
            elif t == "tool_execution_start":
                step = Step(e.get("toolName", "?"), summarize_args(e.get("toolName"), e.get("args")))
                steps[e.get("toolCallId")] = step
                progress.steps.append(step)
                changed = True
            elif t == "tool_execution_end":
                step = steps.get(e.get("toolCallId"))
                if step:
                    step.done, step.error = True, bool(e.get("isError"))
                    changed = True
            elif t == "auto_retry_start":
                progress.retry = f"重试 {e.get('attempt')}/{e.get('maxAttempts')}: {e.get('errorMessage', '')[:80]}"
                changed = True
            elif t == "auto_retry_end":
                progress.retry = ""
                if not e.get("success"):
                    result.error = e.get("finalError") or result.error
                changed = True
            elif t == "compaction_start":
                progress.compacting, changed = True, True
            elif t == "compaction_end":
                progress.compacting, changed = False, True

            if changed and on_progress:
                result.steps = len(progress.steps)
                try:
                    await on_progress(progress)
                except Exception as ex:
                    logger.debug("on_progress failed: %s", ex)
        result.steps = len(progress.steps)
