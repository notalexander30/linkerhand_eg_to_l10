#!/usr/bin/env python3
"""Serial parser for the KTH5702/EG glove text stream."""

from __future__ import annotations

import re
from typing import Iterator


SENSOR_COUNT = 15
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove terminal escape codes from serial console text."""

    return ANSI_RE.sub("", text)


def parse_sensor_line(line: str) -> tuple[int, float] | None:
    """Parse one KTH5702 line into a sensor index and angle value."""

    clean = strip_ansi(line).replace("\\x1b", "").strip()
    if "KTH5702:" not in clean or "|" not in clean:
        return None

    parts = [part.strip() for part in clean.split("|")]
    if len(parts) < 8:
        return None

    try:
        angle_match = re.search(r"-?\d+(?:\.\d+)?", parts[4])
        if angle_match is None:
            return None
        angle = float(angle_match.group(0))
        sensor_index = int(parts[7])
    except (ValueError, IndexError):
        return None

    if 0 <= sensor_index < SENSOR_COUNT:
        return sensor_index, angle
    return None


def open_serial(port: str, baud: int):
    """Open the glove serial port with user-friendly dependency errors."""

    try:
        import serial
    except ImportError as exc:
        raise SystemExit("Missing pyserial. Install it with: python3 -m pip install -r requirements.txt") from exc

    try:
        return serial.Serial(port, baudrate=baud, timeout=1)
    except PermissionError as exc:
        raise SystemExit(
            f"No permission to open {port}. Run: sudo usermod -aG dialout $USER && newgrp dialout"
        ) from exc
    except OSError as exc:
        raise SystemExit(f"Could not open {port}: {exc}") from exc


def glove_frames(port: str, baud: int) -> Iterator[dict[int, float]]:
    """Yield complete 15-sensor glove frames keyed by raw sensor index."""

    angles: dict[int, float] = {}
    with open_serial(port, baud) as serial_port:
        print(f"Reading glove from {port} at {baud} baud. Press Ctrl+C to stop.")
        while True:
            raw = serial_port.readline()
            if not raw:
                continue
            parsed = parse_sensor_line(raw.decode("utf-8", errors="ignore"))
            if parsed is None:
                continue
            index, angle = parsed
            angles[index] = angle
            if index == SENSOR_COUNT - 1 and len(angles) == SENSOR_COUNT:
                yield dict(angles)
