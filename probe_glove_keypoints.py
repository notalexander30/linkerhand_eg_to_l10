#!/usr/bin/env python3
"""Probe EG glove open/moved values and optionally patch one L10 YAML channel.

This is a small calibration helper for the "move one finger, see which sensor
changed" workflow. It does not move the L10 hand.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Mapping


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from control_l10_left_from_eg_glove import GloveReader, SERIAL_SENSOR_KEYS  # noqa: E402


DEFAULT_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.auto.yaml"
DEFAULT_FALLBACK_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.yaml"
SOURCE_SENSOR_INDEX_BY_KEY = {key: index for index, key in enumerate(SERIAL_SENSOR_KEYS)}


def load_yaml(path: Path) -> dict[str, Any]:
    """Read the YAML mapping file that may be patched."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path: Path, data: Mapping[str, Any]) -> None:
    """Write the patched YAML mapping file."""

    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(dict(data), file, sort_keys=False)
    print(f"\nUpdated YAML: {path}")


def wait_for_enter(message: str, *, skip: bool) -> None:
    """Prompt the user before sampling a stable glove pose."""

    print(message)
    if not skip:
        input("Press Enter when ready...")


def median_frame(
    frame_iter: Iterator[dict[str, float]],
    keys: list[str],
    sample_count: int,
) -> dict[str, float]:
    """Collect enough frames and return one median value per glove key."""

    samples: dict[str, list[float]] = {key: [] for key in keys}
    while min(len(values) for values in samples.values()) < sample_count:
        frame = next(frame_iter)
        for key in keys:
            if key in frame:
                samples[key].append(float(frame[key]))
    return {key: float(statistics.median(values)) for key, values in samples.items() if values}


def rank_sensor_deltas(
    open_frame: Mapping[str, float],
    moved_frame: Mapping[str, float],
) -> list[tuple[str, float]]:
    """Rank sensors by how much they changed between open and moved poses."""

    ranked = []
    for key in SERIAL_SENSOR_KEYS:
        if key in open_frame and key in moved_frame:
            ranked.append((key, moved_frame[key] - open_frame[key]))
    return sorted(ranked, key=lambda item: abs(item[1]), reverse=True)


def print_probe_table(
    open_frame: Mapping[str, float],
    moved_frame: Mapping[str, float],
    ranked: list[tuple[str, float]],
    top_count: int,
) -> None:
    """Print all captured values plus the strongest sensor candidates."""

    print("\nAll EG glove sensor values")
    print("raw  glove_key   open        moved       delta")
    print("---  ---------   ---------   ---------   ---------")
    for key in SERIAL_SENSOR_KEYS:
        if key not in open_frame or key not in moved_frame:
            continue
        source_index = SOURCE_SENSOR_INDEX_BY_KEY[key]
        delta = moved_frame[key] - open_frame[key]
        print(
            f"{source_index:>3}  {key:<9}   "
            f"{open_frame[key]:>9.3f}   {moved_frame[key]:>9.3f}   {delta:>+9.3f}"
        )

    print(f"\nTop {min(top_count, len(ranked))} moved sensors")
    for rank, (key, delta) in enumerate(ranked[:top_count], start=1):
        print(
            f"{rank:>2}. raw {SOURCE_SENSOR_INDEX_BY_KEY[key]:>2}  "
            f"{key:<9}  delta={delta:+.3f}  "
            f"open={open_frame[key]:.3f}  moved={moved_frame[key]:.3f}"
        )


def find_channel(data: Mapping[str, Any], motor_index: int) -> dict[str, Any]:
    """Find the YAML channel for a target L10 motor index."""

    for channel in data.get("channels", []):
        if int(channel.get("motor_index", -1)) == motor_index:
            return channel
    raise SystemExit(f"Could not find motor_index {motor_index} in YAML channels.")


def patch_channel(
    data: dict[str, Any],
    motor_index: int,
    glove_key: str,
    open_value: float,
    moved_value: float,
    ranked: list[tuple[str, float]],
) -> None:
    """Patch one channel with the selected glove key and captured keypoints."""

    channel = find_channel(data, motor_index)
    second_delta = abs(ranked[1][1]) if len(ranked) > 1 else 0.0
    best_delta = abs(ranked[0][1]) if ranked else 0.0
    confidence = best_delta / second_delta if second_delta > 1e-9 else 999.0

    channel["glove_key"] = glove_key
    channel["source_sensor_index"] = SOURCE_SENSOR_INDEX_BY_KEY.get(glove_key)
    channel["glove_open"] = round(float(open_value), 5)
    channel["glove_closed"] = round(float(moved_value), 5)
    channel["glove_min"] = round(min(float(open_value), float(moved_value)), 5)
    channel["glove_max"] = round(max(float(open_value), float(moved_value)), 5)
    channel["match_delta"] = round(float(moved_value - open_value), 5)
    channel["match_confidence"] = round(float(confidence), 3)

    metadata = dict(data.get("metadata", {}))
    metadata["last_probe_motor"] = motor_index
    metadata["last_probe_glove_key"] = glove_key
    metadata["last_probe_source_sensor_index"] = SOURCE_SENSOR_INDEX_BY_KEY.get(glove_key)
    data["metadata"] = metadata


def build_reader(args: argparse.Namespace, data: Mapping[str, Any]) -> GloveReader:
    """Create the EG glove reader from CLI values and YAML defaults."""

    settings = dict(data.get("glove_reader", {}))
    settings["mode"] = "serial"
    settings["port"] = args.glove_port
    settings["baud"] = args.baud
    return GloveReader(mock=args.mock_glove, settings=settings)


def build_parser() -> argparse.ArgumentParser:
    """CLI for probing one glove open/moved keypoint pair."""

    parser = argparse.ArgumentParser(description="Probe EG glove keypoints and optionally patch one L10 YAML motor.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML mapping to update.")
    parser.add_argument("--motor", type=int, default=None, help="L10 motor index to patch with the strongest sensor.")
    parser.add_argument("--glove-key", default=None, help="Force this glove_key instead of the strongest moved sensor.")
    parser.add_argument("--label", default="target finger", help="Text shown in prompts, for example index or pinky.")
    parser.add_argument("--glove-port", default="/dev/ttyUSB0", help="USB serial port for the EG glove.")
    parser.add_argument("--baud", type=int, default=115200, help="Glove serial baud rate.")
    parser.add_argument("--samples", type=int, default=35, help="Samples to collect for each pose.")
    parser.add_argument("--settle", type=float, default=0.4, help="Seconds to wait after each prompt.")
    parser.add_argument("--top", type=int, default=6, help="How many strongest sensor candidates to print.")
    parser.add_argument("--no-write", action="store_true", help="Only print captured values; do not patch YAML.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for testing.")
    parser.add_argument("--non-interactive", action="store_true", help="Skip Enter prompts.")
    return parser


def main() -> None:
    """Capture open/moved keypoints, print candidates, and optionally patch YAML."""

    args = build_parser().parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1.")
    if args.top < 1:
        raise SystemExit("--top must be at least 1.")
    if args.glove_key is not None and args.glove_key not in SOURCE_SENSOR_INDEX_BY_KEY:
        raise SystemExit(f"Unknown --glove-key {args.glove_key!r}.")

    config_path = args.config if args.config.exists() else DEFAULT_FALLBACK_CONFIG
    data = load_yaml(config_path)
    reader = build_reader(args, data)
    frame_iter = reader.frames()

    wait_for_enter(f"\nOpen your RIGHT glove hand fully for {args.label}.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    open_frame = median_frame(frame_iter, list(SERIAL_SENSOR_KEYS), args.samples)

    wait_for_enter(f"\nMove/close only the RIGHT glove {args.label} and hold still.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    moved_frame = median_frame(frame_iter, list(SERIAL_SENSOR_KEYS), args.samples)

    ranked = rank_sensor_deltas(open_frame, moved_frame)
    if not ranked:
        raise SystemExit("No glove sensor data was captured.")
    print_probe_table(open_frame, moved_frame, ranked, args.top)

    selected_key = args.glove_key or ranked[0][0]
    print("\nCopy this back to Codex if you want me to verify it:")
    print(f"motor={args.motor}")
    print(f"best_glove_key={selected_key}")
    print(f"source_sensor_index={SOURCE_SENSOR_INDEX_BY_KEY[selected_key]}")
    print(f"glove_open={open_frame[selected_key]:.5f}")
    print(f"glove_closed={moved_frame[selected_key]:.5f}")

    if args.motor is None or args.no_write:
        print("\nYAML was not changed.")
        return

    output_data = load_yaml(args.config) if args.config.exists() else data
    patch_channel(output_data, args.motor, selected_key, open_frame[selected_key], moved_frame[selected_key], ranked)
    save_yaml(args.config, output_data)


if __name__ == "__main__":
    main()
