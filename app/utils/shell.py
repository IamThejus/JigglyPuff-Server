"""Thin, safe wrapper around ``subprocess`` for the few places we must shell out.

Every command is passed as an argument list (never a shell string) so there is
no shell-injection surface. Failures are captured and returned instead of
raising, so callers can degrade gracefully when an optional tool (``smartctl``,
``systemctl`` ...) is missing on the machine.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class CommandResult:
    """Result of running an external command."""

    ok: bool
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout.strip()


def command_exists(name: str) -> bool:
    """Return True if ``name`` is on PATH."""

    return shutil.which(name) is not None


def run(args: list[str], timeout: float = 10.0) -> CommandResult:
    """Run ``args`` and return a :class:`CommandResult`.

    Never raises for non-zero exit codes or missing binaries — inspect the
    returned ``ok`` flag instead.
    """

    if not args:
        return CommandResult(ok=False, returncode=-1, stdout="", stderr="empty command")

    if not command_exists(args[0]):
        logger.debug("command not found: %s", args[0])
        return CommandResult(
            ok=False, returncode=127, stdout="", stderr=f"{args[0]}: not found"
        )

    try:
        proc = subprocess.run(  # noqa: S603 - args is a fixed list, no shell
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("command timed out: %s", " ".join(args))
        return CommandResult(ok=False, returncode=-1, stdout="", stderr="timeout")
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("command failed to start: %s (%s)", " ".join(args), exc)
        return CommandResult(ok=False, returncode=-1, stdout="", stderr=str(exc))

    return CommandResult(
        ok=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
