"""Wrapper around claude-internal CLI calls."""

import asyncio
import logging
import os
import uuid

logger = logging.getLogger("discord_bot")

CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude-internal")
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "300"))


class ClaudeCLI:
    """Encapsulate claude-internal CLI invocations."""

    def __init__(
        self,
        claude_cmd: str = CLAUDE_CMD,
        timeout: int = COMMAND_TIMEOUT,
    ):
        self.claude_cmd = claude_cmd
        self.timeout = timeout

    def _base_cmd(self) -> list[str]:
        return [
            self.claude_cmd,
            "--output-format", "text",
            "--permission-mode", "bypassPermissions",
        ]

    async def _run(self, cmd: list[str], *, cwd: str) -> str:
        """Execute CLI command and return stdout text."""
        logger.debug("CMD (cwd=%s): %s", cwd, " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("CLI timeout after %ss", self.timeout)
            return f"⏰ 响应超时（超过 {self.timeout}s），请稍后重试。"
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            logger.info("CLI cancelled")
            raise

        output = stdout.decode().strip()
        err_output = stderr.decode().strip()

        if err_output:
            logger.warning("CLI stderr: %s", err_output[:500])

        if not output:
            if err_output:
                logger.error("CLI returned no stdout, stderr: %s", err_output[:500])
                return f"⚠️ CLI 错误:\n```\n{err_output[:1500]}\n```"
            logger.warning("CLI returned empty response")
            return "⚠️ 未收到任何回复。"

        logger.info("CLI response length: %d chars", len(output))
        return output

    async def new_session(
        self, message: str, session_id: str | None = None, *, cwd: str, no_persistence: bool = False
    ) -> tuple[str, str]:
        """Start a new session. Returns (response, session_id)."""
        if session_id is None:
            session_id = str(uuid.uuid4())
        cmd = self._base_cmd() + ["-p", message, "--session-id", session_id]
        if no_persistence:
            cmd.append("--no-session-persistence")
        response = await self._run(cmd, cwd=cwd)
        return response, session_id

    async def resume_session(self, message: str, session_id: str, *, cwd: str) -> str:
        """Resume an existing session with a message."""
        cmd = self._base_cmd() + ["-p", message, "--resume", session_id]
        return await self._run(cmd, cwd=cwd)

    async def continue_latest(self, message: str | None = None, *, cwd: str) -> str:
        """Continue the most recent session (CLI --continue)."""
        cmd = self._base_cmd() + ["--continue"]
        if message:
            cmd += ["-p", message]
        return await self._run(cmd, cwd=cwd)

    async def fork_session(
        self, message: str, session_id: str, *, cwd: str
    ) -> tuple[str, str | None]:
        """Fork a session. Returns (response, new_session_id or None)."""
        new_id = str(uuid.uuid4())
        cmd = self._base_cmd() + [
            "-p", message,
            "--resume", session_id,
            "--session-id", new_id,
        ]
        response = await self._run(cmd, cwd=cwd)
        return response, new_id
