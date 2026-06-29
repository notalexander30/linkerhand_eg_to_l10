#!/usr/bin/env python3
"""Shared helpers for glove open/closed range calibration."""

from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


def load_yaml(path: Path) -> dict[str, Any]:
    """Read an existing mapping YAML."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path: Path, data: Mapping[str, Any]) -> None:
    """Write an updated mapping YAML."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(dict(data), file, sort_keys=False)
    print(f"Updated glove ranges in {path}")


def wait_for_enter(message: str, *, skip: bool) -> None:
    """Show a calibration prompt and optionally wait for the operator."""

    print(message)
    if not skip:
        input("Press Enter when ready...")


def collect_samples(
    frame_iter: Iterator[dict[str, float]],
    keys: Iterable[str],
    sample_count: int,
) -> dict[str, list[float]]:
    """Collect raw glove samples until every requested key has enough data."""

    key_list = list(keys)
    if not key_list:
        raise SystemExit("No glove sensor keys selected for calibration.")
    samples: dict[str, list[float]] = {key: [] for key in key_list}
    while min(len(values) for values in samples.values()) < sample_count:
        frame = next(frame_iter)
        for key in samples:
            if key in frame:
                samples[key].append(float(frame[key]))
    return samples


def median_values(samples: Mapping[str, list[float]]) -> dict[str, float]:
    """Convert sample lists to median values."""

    return {key: float(statistics.median(values)) for key, values in samples.items() if values}


def select_channels(data: Mapping[str, Any], motors: set[int] | None, include_disabled: bool) -> list[dict[str, Any]]:
    """Choose which YAML channels should receive new glove_open/glove_closed values."""

    selected = []
    for channel in data.get("channels", []):
        motor_index = int(channel.get("motor_index", -1))
        if motors is not None and motor_index not in motors:
            continue
        if not include_disabled and channel.get("enabled") is False:
            continue
        selected.append(channel)
    if not selected:
        raise SystemExit("No channels selected for range capture.")
    return selected


def update_glove_reader_settings(
    data: dict[str, Any],
    *,
    port: str | None = None,
    baud: int | None = None,
) -> dict[str, Any]:
    """Apply runtime serial overrides to the YAML glove_reader block."""

    settings = dict(data.get("glove_reader", {}))
    settings["mode"] = "serial"
    if port is not None:
        settings["port"] = port
    if baud is not None:
        settings["baud"] = baud
    data["glove_reader"] = settings
    return settings


def update_ranges(
    data: dict[str, Any],
    channels: list[dict[str, Any]],
    open_values: Mapping[str, float],
    closed_values: Mapping[str, float],
    *,
    source_sensor_index_by_key: Mapping[str, int] | None = None,
    min_delta: float = 0.0,
    note: str = "glove_open/glove_closed were re-captured without remapping sensors",
) -> list[int]:
    """Write captured open/closed/min/max values into selected YAML channels."""

    updated_motors = []
    for channel in channels:
        glove_key = str(channel["glove_key"])
        if glove_key not in open_values or glove_key not in closed_values:
            print(f"Warning: missing captured data for {glove_key}; skipped.", file=sys.stderr)
            continue
        open_value = float(open_values[glove_key])
        closed_value = float(closed_values[glove_key])
        delta = closed_value - open_value
        channel["glove_open"] = round(open_value, 5)
        channel["glove_closed"] = round(closed_value, 5)
        channel["glove_min"] = round(min(open_value, closed_value), 5)
        channel["glove_max"] = round(max(open_value, closed_value), 5)
        channel["range_delta"] = round(delta, 5)
        if source_sensor_index_by_key is not None and glove_key in source_sensor_index_by_key:
            channel["source_sensor_index"] = source_sensor_index_by_key[glove_key]
        if abs(delta) < min_delta:
            joint_name = channel.get("l10_joint_name", channel.get("name", glove_key))
            print(
                f"Warning: {joint_name} captured a small range "
                f"({delta:.3f}). Refit the glove or recapture that motor if teleop feels noisy.",
                file=sys.stderr,
            )
        updated_motors.append(int(channel["motor_index"]))

    metadata = dict(data.get("metadata", {}))
    metadata["range_capture_updated_motors"] = sorted(updated_motors)
    metadata["range_capture_note"] = note
    data["metadata"] = metadata
    return updated_motors
