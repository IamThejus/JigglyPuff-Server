"""Small formatting helpers shared across services."""

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_bytes(num: float | int | None) -> str:
    """Return a human-readable size string, e.g. ``12.4 GB``."""

    if num is None:
        return "0 B"
    value = float(num)
    for unit in _UNITS:
        if abs(value) < 1024.0 or unit == _UNITS[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def human_duration(seconds: float | int | None) -> str:
    """Return a compact duration string, e.g. ``3d 4h 12m``."""

    if seconds is None or seconds < 0:
        return "unknown"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def percent(used: float, total: float) -> float:
    """Return ``used / total`` as a rounded percentage (0 when total is 0)."""

    if not total:
        return 0.0
    return round(used / total * 100, 1)
