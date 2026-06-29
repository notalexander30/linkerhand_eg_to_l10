#!/usr/bin/env python3
"""Re-capture glove open/closed calibration ranges for an existing mapping YAML.

This does not remap sensors. It keeps the current glove_key for each channel,
captures an open hand pose and a closed/max pose, then updates glove_open and
glove_closed in place.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from control_l10_left_from_eg_glove import DEFAULT_TEMPLATE_CONFIG, SERIAL_SENSOR_KEYS, GloveReader  # noqa: E402
from glove_range_calibration import (  # noqa: E402
    collect_samples,
    load_yaml,
    median_values,
    save_yaml,
    select_channels,
    update_glove_reader_settings,
    update_ranges,
    wait_for_enter,
)


DEFAULT_AUTO_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.auto.yaml"
SOURCE_SENSOR_INDEX_BY_KEY = {key: index for index, key in enumerate(SERIAL_SENSOR_KEYS)}


def build_reader(args: argparse.Namespace, config_path: Path) -> GloveReader:
    """Create a glove reader from CLI overrides and YAML defaults."""

    data = load_yaml(config_path) if config_path.exists() else load_yaml(DEFAULT_TEMPLATE_CONFIG)
    settings = update_glove_reader_settings(data, port=args.glove_port, baud=args.baud)
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
    parser.add_argument("--min-delta", type=float, default=3.0, help="Warn when open/closed capture is smaller than this.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for testing.")
    parser.add_argument("--non-interactive", action="store_true", help="Skip Enter prompts.")
    return parser


def main() -> None:
    """Capture and save the new open/closed ranges."""

    args = build_parser().parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1.")

    data = load_yaml(args.config)
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

    update_ranges(
        data,
        channels,
        median_values(open_samples),
        median_values(closed_samples),
        source_sensor_index_by_key=SOURCE_SENSOR_INDEX_BY_KEY,
        min_delta=args.min_delta,
    )
    save_yaml(args.config, data)


if __name__ == "__main__":
    main()
