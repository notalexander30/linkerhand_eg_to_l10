#!/usr/bin/env python3
"""Re-capture glove open/closed calibration ranges for an existing mapping YAML.

This does not remap sensors. It keeps the current glove_key for each channel,
captures an open hand pose and a closed/max pose, then updates glove_open and
glove_closed in place.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from control_l10_left_from_eg_glove import DEFAULT_CONFIG, GloveReader, apply_reference_mapping  # noqa: E402


DEFAULT_AUTO_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.auto.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    """Read an existing mapping YAML."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path: Path, data: Mapping[str, Any]) -> None:
    """Write the updated mapping YAML."""

    import yaml

    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(dict(data), file, sort_keys=False)
    print(f"Updated glove ranges in {path}")


def wait_for_enter(message: str, *, skip: bool) -> None:
    """Show a calibration prompt."""

    print(message)
    if not skip:
        input("Press Enter when ready...")


def collect_samples(
    frame_iter: Iterator[dict[str, float]],
    keys: Iterable[str],
    sample_count: int,
) -> dict[str, list[float]]:
    """Collect raw glove samples until every requested key has enough data."""

    samples: dict[str, list[float]] = {key: [] for key in keys}
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


def update_ranges(
    data: dict[str, Any],
    channels: list[dict[str, Any]],
    open_values: Mapping[str, float],
    closed_values: Mapping[str, float],
) -> None:
    """Write captured open/closed/min/max values into the selected channels."""

    updated_motors = []
    for channel in channels:
        glove_key = str(channel["glove_key"])
        if glove_key not in open_values or glove_key not in closed_values:
            print(f"Warning: missing captured data for {glove_key}; skipped.", file=sys.stderr)
            continue
        open_value = float(open_values[glove_key])
        closed_value = float(closed_values[glove_key])
        channel["glove_open"] = round(open_value, 5)
        channel["glove_closed"] = round(closed_value, 5)
        channel["glove_min"] = round(min(open_value, closed_value), 5)
        channel["glove_max"] = round(max(open_value, closed_value), 5)
        channel["range_delta"] = round(closed_value - open_value, 5)
        updated_motors.append(int(channel["motor_index"]))

    metadata = dict(data.get("metadata", {}))
    metadata["range_capture_updated_motors"] = sorted(updated_motors)
    metadata["range_capture_note"] = "glove_open/glove_closed were re-captured without remapping sensors"
    data["metadata"] = metadata


def build_reader(args: argparse.Namespace, config_path: Path) -> GloveReader:
    """Create a glove reader from CLI overrides and YAML defaults."""

    data = load_yaml(config_path) if config_path.exists() else load_yaml(DEFAULT_CONFIG)
    settings = dict(data.get("glove_reader", {}))
    settings["mode"] = "serial"
    settings["port"] = args.glove_port
    settings["baud"] = args.baud
    return GloveReader(mock=args.mock_glove, settings=settings)


def build_parser() -> argparse.ArgumentParser:
    """CLI for in-place open/closed range capture."""

    parser = argparse.ArgumentParser(description="Capture open/closed glove ranges for an existing L10 mapping.")
    parser.add_argument("--config", type=Path, default=DEFAULT_AUTO_CONFIG, help="YAML mapping to update in place.")
    parser.add_argument("--glove-port", default="/dev/ttyUSB0", help="USB serial port for the glove.")
    parser.add_argument("--baud", type=int, default=115200, help="Glove serial baud rate.")
    parser.add_argument("--samples", type=int, default=45, help="Samples to collect for open and closed poses.")
    parser.add_argument("--settle", type=float, default=0.5, help="Seconds to wait after each prompt before sampling.")
    parser.add_argument("--motors", nargs="+", type=int, default=None, help="Only update these L10 motor indexes.")
    parser.add_argument("--include-disabled", action="store_true", help="Also update channels where enabled: false.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for testing.")
    parser.add_argument("--non-interactive", action="store_true", help="Skip Enter prompts.")
    return parser


def main() -> None:
    """Capture and save the new open/closed ranges."""

    args = build_parser().parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1.")

    data = load_yaml(args.config)
    if bool(data.get("apply_reference_mapping", True)):
        apply_reference_mapping(data)
    motors = None if args.motors is None else set(args.motors)
    channels = select_channels(data, motors, args.include_disabled)
    keys = sorted({str(channel["glove_key"]) for channel in channels})
    reader = build_reader(args, args.config)
    frame_iter = reader.frames()

    wait_for_enter("\nOpen your RIGHT glove hand fully and hold it still.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    open_samples = collect_samples(frame_iter, keys, args.samples)

    wait_for_enter("\nClose/flex the selected fingers to their maximum useful pose and hold still.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    closed_samples = collect_samples(frame_iter, keys, args.samples)

    update_ranges(data, channels, median_values(open_samples), median_values(closed_samples))
    save_yaml(args.config, data)


if __name__ == "__main__":
    main()
