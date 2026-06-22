#!/usr/bin/env python3
"""Live terminal tuner for one EG glove sensor -> one L10 motor channel.

Use this when one joint is basically mapped correctly but the open/closed
numbers need better calibration. The display updates continuously while you
move the glove, then single-key commands can capture and save the range.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

if os.name == "nt":
    import msvcrt
else:
    import select
    import termios
    import tty


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from control_l10_left_from_eg_glove import (  # noqa: E402
    GloveReader,
    L10_JOINT_NAMES,
    clamp,
    clamp_int,
    load_config,
    map_channel,
)


DEFAULT_AUTO_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.auto.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    """Read the YAML as a mutable dictionary so captured values can be saved."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path: Path, data: Mapping[str, Any]) -> None:
    """Write the tuned YAML in the same simple block style as the other tools."""

    import yaml

    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(dict(data), file, sort_keys=False)


def channels(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return mutable channel dictionaries from the YAML file."""

    values = data.get("channels", [])
    if not isinstance(values, list):
        raise SystemExit("YAML does not contain a channels list.")
    return values


def find_channel(data: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Choose the channel to tune by motor index, channel name, or glove key."""

    candidates = channels(data)
    if args.motor is not None:
        for channel in candidates:
            if int(channel.get("motor_index", -1)) == args.motor:
                return channel
        raise SystemExit(f"No channel has motor_index: {args.motor}")

    if args.name is not None:
        target = args.name.lower()
        for channel in candidates:
            if str(channel.get("name", "")).lower() == target:
                return channel
        raise SystemExit(f"No channel has name: {args.name}")

    if args.glove_key is not None:
        target = args.glove_key.lower()
        for channel in candidates:
            if str(channel.get("glove_key", "")).lower() == target:
                return channel
        raise SystemExit(f"No channel uses glove_key: {args.glove_key}")

    raise SystemExit("Choose one channel with --motor, --name, or --glove-key.")


def list_channels(data: Mapping[str, Any]) -> None:
    """Print the tunable YAML channels."""

    print("motor  channel name                 glove_key   L10 joint")
    print("-----  ---------------------------  ----------  ------------------------------")
    for channel in channels(data):
        motor = int(channel.get("motor_index", -1))
        joint = channel.get("l10_joint_name") or (
            L10_JOINT_NAMES[motor] if 0 <= motor < len(L10_JOINT_NAMES) else ""
        )
        print(
            f"{motor:>5}  "
            f"{str(channel.get('name', '')):<27}  "
            f"{str(channel.get('glove_key', '')):<10}  "
            f"{joint}"
        )


def build_reader(data: Mapping[str, Any], args: argparse.Namespace) -> GloveReader:
    """Create a glove reader, using YAML defaults unless CLI overrides them."""

    settings = dict(data.get("glove_reader", {}))
    settings["mode"] = "serial"
    if args.glove_port is not None:
        settings["port"] = args.glove_port
    if args.baud is not None:
        settings["baud"] = args.baud
    return GloveReader(mock=args.mock_glove, settings=settings)


def normalized_score(raw_value: float, channel: Mapping[str, Any]) -> float:
    """Return the raw glove position as 0..1 before invert/gain."""

    glove_open = float(channel["glove_open"])
    glove_closed = float(channel["glove_closed"])
    if glove_open == glove_closed:
        return 0.0
    return clamp((raw_value - glove_open) / (glove_closed - glove_open), 0.0, 1.0)


def tuned_l10_score(raw_value: float, channel: Mapping[str, Any], config_path: Path) -> int:
    """Use the real controller mapping so the displayed score matches live control."""

    config = load_config(config_path)
    motor_index = int(channel["motor_index"])
    for parsed_channel in config.channels:
        if parsed_channel.motor_index == motor_index:
            return map_channel(raw_value, parsed_channel, config)
    raise SystemExit(f"No parsed config channel for motor {motor_index}")


def update_channel_range(channel: dict[str, Any], open_value: float, closed_value: float) -> None:
    """Write captured open/closed values into one channel."""

    channel["glove_open"] = round(open_value, 5)
    channel["glove_closed"] = round(closed_value, 5)
    channel["glove_min"] = round(min(open_value, closed_value), 5)
    channel["glove_max"] = round(max(open_value, closed_value), 5)
    channel["range_delta"] = round(closed_value - open_value, 5)


def update_metadata(data: dict[str, Any], channel: Mapping[str, Any]) -> None:
    """Record which channel was tuned most recently."""

    metadata = dict(data.get("metadata", {}))
    metadata["last_live_tuned_motor"] = int(channel["motor_index"])
    metadata["last_live_tuned_glove_key"] = str(channel["glove_key"])
    metadata["last_live_tune_note"] = "glove_open/glove_closed updated by tune_glove_channel.py"
    data["metadata"] = metadata


@contextlib.contextmanager
def raw_terminal(enabled: bool):
    """Temporarily switch to single-key input on POSIX terminals."""

    if os.name == "nt" or not enabled or not sys.stdin.isatty():
        yield
        return

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        yield
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def read_key() -> str | None:
    """Read one key without blocking."""

    if os.name == "nt":
        if msvcrt.kbhit():
            return msvcrt.getwch().lower()
        return None

    if not sys.stdin.isatty():
        return None
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return None
    return sys.stdin.read(1).lower()


def format_bar(score: float, width: int = 32) -> str:
    """Draw a tiny terminal bar for the normalized 0..1 score."""

    filled = clamp_int(score * width, 0, width)
    return "#" * filled + "-" * (width - filled)


def clear_screen() -> None:
    """Clear terminal without depending on curses."""

    print("\033[2J\033[H", end="")


def live_tune(args: argparse.Namespace) -> None:
    """Run the interactive terminal tuner."""

    data = load_yaml(args.config)
    if args.list:
        list_channels(data)
        return

    channel = find_channel(data, args)
    reader = build_reader(data, args)
    frame_iter = reader.frames()
    glove_key = str(channel["glove_key"])
    motor_index = int(channel["motor_index"])
    joint_name = channel.get("l10_joint_name") or L10_JOINT_NAMES[motor_index]
    open_capture: float | None = None
    closed_capture: float | None = None
    observed_min: float | None = None
    observed_max: float | None = None
    status = "Move the selected glove part. Press h for help."

    with raw_terminal(not args.no_raw_terminal):
        while True:
            frame = next(frame_iter)
            if glove_key not in frame:
                raise SystemExit(f"Glove frame does not contain {glove_key}. Check the YAML glove_key.")

            raw_value = float(frame[glove_key])
            observed_min = raw_value if observed_min is None else min(observed_min, raw_value)
            observed_max = raw_value if observed_max is None else max(observed_max, raw_value)
            raw_score = normalized_score(raw_value, channel)
            l10_score = tuned_l10_score(raw_value, channel, args.config)

            clear_screen()
            print("Live EG Glove Channel Tuner")
            print("=" * 29)
            print(f"config       : {args.config}")
            print(f"motor        : {motor_index} ({joint_name})")
            print(f"channel name : {channel.get('name')}")
            print(f"glove_key    : {glove_key}")
            print(f"raw value    : {raw_value:.3f}")
            print(f"raw range    : open={float(channel['glove_open']):.3f} closed={float(channel['glove_closed']):.3f}")
            print(f"observed     : min={observed_min:.3f} max={observed_max:.3f}")
            print(f"raw score    : {raw_score * 100:6.2f}% [{format_bar(raw_score)}]")
            print(f"L10 score    : {l10_score:3d} / 255")
            print()
            print(f"captured open  : {'none' if open_capture is None else f'{open_capture:.3f}'}")
            print(f"captured closed: {'none' if closed_capture is None else f'{closed_capture:.3f}'}")
            print()
            print("keys: o=open/start  c=closed/end  s=save YAML  r=reset observed  h=help  q=quit")
            print(f"status: {status}")
            sys.stdout.flush()

            key = read_key()
            if key == "q":
                print("\nQuit without further changes.")
                return
            if key == "o":
                open_capture = raw_value
                status = f"Captured open/start value {open_capture:.3f}."
            elif key == "c":
                closed_capture = raw_value
                status = f"Captured closed/end value {closed_capture:.3f}."
            elif key == "r":
                observed_min = raw_value
                observed_max = raw_value
                status = "Reset observed min/max."
            elif key == "h":
                status = "Hold normal/start pose and press o; hold max/end pose and press c; press s to save."
            elif key == "s":
                if open_capture is None or closed_capture is None:
                    status = "Capture both open/start (o) and closed/end (c) before saving."
                else:
                    update_channel_range(channel, open_capture, closed_capture)
                    update_metadata(data, channel)
                    save_yaml(args.config, data)
                    status = f"Saved {glove_key}: open={open_capture:.3f}, closed={closed_capture:.3f}."
            time.sleep(max(0.01, 1.0 / max(args.hz, 1.0)))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""

    parser = argparse.ArgumentParser(description="Live terminal tuner for one EG glove -> L10 YAML channel.")
    parser.add_argument("--config", type=Path, default=DEFAULT_AUTO_CONFIG, help="Mapping YAML to read/update.")
    parser.add_argument("--motor", type=int, help="Tune this L10 motor index, for example 0 for thumb pitch.")
    parser.add_argument("--name", help="Tune by YAML channel name.")
    parser.add_argument("--glove-key", help="Tune by glove sensor key, for example thumb_2.")
    parser.add_argument("--list", action="store_true", help="List channels and exit.")
    parser.add_argument("--glove-port", help="Override glove serial port from YAML.")
    parser.add_argument("--baud", type=int, help="Override glove baud from YAML.")
    parser.add_argument("--hz", type=float, default=15.0, help="Terminal refresh rate.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for testing.")
    parser.add_argument("--no-raw-terminal", action="store_true", help="Require Enter after each keypress.")
    return parser


def main() -> None:
    """CLI entry point."""

    # Keep ANSI clear codes working in terminals that honor TERM.
    os.environ.setdefault("TERM", "xterm")
    live_tune(build_parser().parse_args())


if __name__ == "__main__":
    main()
