"""systemd service status via ``systemctl``.

Read-only: we only query ``is-active`` / ``show`` / ``is-enabled``. Control
actions (restart/stop) are intentionally out of scope for v1 — see the NOTE at
the bottom for where they would live.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.services import ServicesResponse, ServiceStatus
from app.utils import shell

logger = get_logger(__name__)

_ACTIVE_STATES = {"active"}


def _parse_show(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def get_service_status(name: str) -> ServiceStatus:
    """Return the status of a single systemd unit."""

    # `systemctl show` gives us ActiveState + SubState + UnitFileState in one go.
    result = shell.run(
        [
            "systemctl",
            "show",
            name,
            "--no-page",
            "--property=ActiveState,SubState,UnitFileState,LoadState",
        ],
        timeout=8.0,
    )

    if not result.ok and not result.stdout:
        return ServiceStatus(name=name, active=False, state="unknown", sub_state=None)

    props = _parse_show(result.stdout)
    active_state = props.get("ActiveState", "unknown")
    sub_state = props.get("SubState") or None
    unit_file_state = props.get("UnitFileState", "")

    enabled: bool | None
    if unit_file_state in ("enabled", "enabled-runtime", "static", "alias"):
        enabled = True
    elif unit_file_state in ("disabled", "masked"):
        enabled = False
    else:
        enabled = None

    # If the unit doesn't exist at all, LoadState is "not-found".
    if props.get("LoadState") == "not-found":
        active_state = "not-found"

    return ServiceStatus(
        name=name,
        active=active_state in _ACTIVE_STATES,
        state=active_state,
        sub_state=sub_state,
        enabled=enabled,
    )


def get_services_status(settings: Settings | None = None) -> ServicesResponse:
    """Return the status of every configured monitored service."""

    settings = settings or get_settings()

    if not shell.command_exists("systemctl"):
        return ServicesResponse(
            available=False,
            services=[],
            message="systemctl not available on this host",
        )

    statuses = [get_service_status(name) for name in settings.monitored_services_list]
    return ServicesResponse(available=True, services=statuses)


# NOTE (future control endpoints): systemctl start/stop/restart require root or
# a PolicyKit rule. When adding control actions, do it in a separate
# `service_control_service.py`, keep this read-only module untouched, and gate
# the routes behind authentication.
