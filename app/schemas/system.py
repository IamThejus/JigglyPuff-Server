"""Response models for system health."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoadAverage(BaseModel):
    one: float = Field(..., description="1-minute load average")
    five: float = Field(..., description="5-minute load average")
    fifteen: float = Field(..., description="15-minute load average")


class MemoryInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float
    total_human: str
    used_human: str


class SwapInfo(BaseModel):
    total_bytes: int
    used_bytes: int
    percent: float
    total_human: str


class NetworkInterface(BaseModel):
    name: str
    addresses: list[str]


class TemperatureReading(BaseModel):
    label: str
    current_celsius: float
    high_celsius: float | None = None
    critical_celsius: float | None = None


class BatteryInfo(BaseModel):
    percent: float
    power_plugged: bool | None = None
    secs_left: int | None = None


class SystemOverview(BaseModel):
    hostname: str
    os: str
    kernel: str
    architecture: str
    uptime_seconds: int
    uptime_human: str
    boot_time_iso: str

    cpu_percent: float
    cpu_count_logical: int
    cpu_count_physical: int | None = None
    load_average: LoadAverage | None = None

    memory: MemoryInfo
    swap: SwapInfo

    temperatures: list[TemperatureReading] = Field(default_factory=list)
    battery: BatteryInfo | None = None
    interfaces: list[NetworkInterface] = Field(default_factory=list)
