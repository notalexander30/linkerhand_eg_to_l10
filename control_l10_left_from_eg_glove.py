#!/usr/bin/env python3
"""Teleoperate a left LinkerHand L10 from a right Linker EG glove.

This script keeps the LinkerHand SDK as the only hand-control path:

    LinkerHandApi(hand_type="left", hand_joint="L10", can="can0")
    api.finger_move(pose=[...10 values...])

The glove side is right and the hand side is left, but mapping is by anatomical
finger name. A right index-finger glove channel controls the left index motor,
not the pinky.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Iterator, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.yaml"
DEFAULT_CAN = "can0"
SERIAL_SENSOR_KEYS = [
    "thumb_0",
    "thumb_1",
    "thumb_2",
    "index_0",
    "index_1",
    "index_2",
    "middle_0",
    "middle_1",
    "middle_2",
    "ring_0",
    "ring_1",
    "ring_2",
    "pinky_0",
    "pinky_1",
    "pinky_2",
]


@dataclass(frozen=True)
class ChannelMapping:
    name: str
    glove_key: str
    motor_index: int
    glove_open: float
    glove_closed: float
    hand_open: int
    hand_closed: int
    invert: bool = False


@dataclass(frozen=True)
class TeleopConfig:
    hand_joint: str
    hand_type: str
    can: str
    control_hz: float
    dry_run: bool
    smoothing_alpha: float
    max_delta_per_cycle: int
    motor_count: int
    channels: list[ChannelMapping]
    safe_exit_pose: Optional[list[int]]
    glove_reader: dict[str, Any]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_int(value: float, low: int = 0, high: int = 255) -> int:
    return int(round(clamp(value, low, high)))


def parse_channel(raw: Mapping[str, Any]) -> ChannelMapping:
    required = [
        "name",
        "glove_key",
        "motor_index",
        "glove_open",
        "glove_closed",
        "hand_open",
        "hand_closed",
    ]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"channel is missing required keys: {', '.join(missing)}")

    return ChannelMapping(
        name=str(raw["name"]),
        glove_key=str(raw["glove_key"]),
        motor_index=int(raw["motor_index"]),
        glove_open=float(raw["glove_open"]),
        glove_closed=float(raw["glove_closed"]),
        hand_open=clamp_int(float(raw["hand_open"])),
        hand_closed=clamp_int(float(raw["hand_closed"])),
        invert=bool(raw.get("invert", False)),
    )


def load_config(path: Path) -> TeleopConfig:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install dependencies with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    channels = [parse_channel(item) for item in raw.get("channels", [])]
    motor_count = int(raw.get("motor_count", 10))
    if motor_count != 10:
        raise ValueError(f"L10 requires motor_count: 10, got {motor_count}")
    if not channels:
        raise ValueError("config must include at least one channel mapping")

    seen_motors: set[int] = set()
    for channel in channels:
        if not 0 <= channel.motor_index < motor_count:
            raise ValueError(f"{channel.name} motor_index must be 0..{motor_count - 1}")
        if channel.motor_index in seen_motors:
            raise ValueError(f"duplicate motor_index in config: {channel.motor_index}")
        seen_motors.add(channel.motor_index)
        if math.isclose(channel.glove_open, channel.glove_closed):
            raise ValueError(f"{channel.name} glove_open and glove_closed cannot be equal")

    safe_exit_pose = raw.get("safe_exit_pose")
    if safe_exit_pose is not None:
        safe_exit_pose = [clamp_int(float(value)) for value in safe_exit_pose]
        if len(safe_exit_pose) != motor_count:
            raise ValueError("safe_exit_pose must contain exactly 10 values")

    return TeleopConfig(
        hand_joint=str(raw.get("hand_joint", "L10")),
        hand_type=str(raw.get("hand_type", "left")),
        can=str(raw.get("can", DEFAULT_CAN)),
        control_hz=float(raw.get("control_hz", 20)),
        dry_run=bool(raw.get("dry_run", True)),
        smoothing_alpha=clamp(float(raw.get("smoothing_alpha", 1.0)), 0.0, 1.0),
        max_delta_per_cycle=max(0, int(raw.get("max_delta_per_cycle", 0))),
        motor_count=motor_count,
        channels=channels,
        safe_exit_pose=safe_exit_pose,
        glove_reader=dict(raw.get("glove_reader", {})),
    )


class GloveReader:
    """Placeholder master-glove interface with mock and serial-backed modes.

    Add UDP, ROS topic, or vendor SDK readers here later as new modes that yield
    dictionaries keyed like thumb_0, index_0, middle_0, ring_0, and pinky_0.
    """

    def __init__(self, *, mock: bool, settings: Mapping[str, Any]) -> None:
        self.mock = mock
        self.settings = dict(settings)

    def frames(self) -> Iterator[dict[str, float]]:
        if self.mock:
            yield from self._mock_frames()
            return

        mode = str(self.settings.get("mode", "serial")).lower()
        if mode == "serial":
            yield from self._serial_frames()
            return
        if mode in {"placeholder", "none"}:
            raise SystemExit(
                "No real glove reader is configured. Use --mock-glove or set "
                "glove_reader.mode to serial, udp, ros, or vendor_sdk once available."
            )
        raise SystemExit(f"Unsupported glove_reader.mode: {mode}")

    def _mock_frames(self) -> Iterator[dict[str, float]]:
        keys = list(dict.fromkeys(SERIAL_SENSOR_KEYS))
        while True:
            for flex in itertools.chain(
                [index / 20.0 for index in range(21)],
                [index / 20.0 for index in range(19, 0, -1)],
            ):
                # Mock values use the default 0=open, 1000=closed calibration.
                yield {key: flex * 1000.0 for key in keys}

    def _serial_frames(self) -> Iterator[dict[str, float]]:
        try:
            from glove_to_l10 import glove_frames
        except ImportError as exc:
            raise SystemExit("Could not import existing serial glove reader from glove_to_l10.py") from exc

        port = str(self.settings.get("port", "/dev/ttyUSB0"))
        baud = int(self.settings.get("baud", 115200))
        for sensor_frame in glove_frames(port, baud):
            frame: dict[str, float] = {}
            for index, key in enumerate(SERIAL_SENSOR_KEYS):
                if index in sensor_frame:
                    frame[key] = float(sensor_frame[index])
                    if key.startswith("pinky_"):
                        frame[key.replace("pinky_", "little_")] = float(sensor_frame[index])
            yield frame


def map_channel(value: float, channel: ChannelMapping) -> int:
    normalized = (value - channel.glove_open) / (channel.glove_closed - channel.glove_open)
    normalized = clamp(normalized, 0.0, 1.0)
    if channel.invert:
        normalized = 1.0 - normalized
    hand_value = channel.hand_open + normalized * (channel.hand_closed - channel.hand_open)
    return clamp_int(hand_value)


def open_pose_from_config(config: TeleopConfig) -> list[int]:
    pose = [255] * config.motor_count
    for channel in config.channels:
        pose[channel.motor_index] = clamp_int(channel.hand_open)
    return pose


def map_glove_to_pose(
    glove_values: Mapping[str, float],
    config: TeleopConfig,
    warned_missing: set[str],
) -> list[int]:
    pose = open_pose_from_config(config)
    for channel in config.channels:
        if channel.glove_key not in glove_values:
            if channel.glove_key not in warned_missing:
                print(
                    f"Warning: missing glove key '{channel.glove_key}' for channel "
                    f"'{channel.name}'. Using hand_open={channel.hand_open}.",
                    file=sys.stderr,
                )
                warned_missing.add(channel.glove_key)
            continue
        pose[channel.motor_index] = map_channel(float(glove_values[channel.glove_key]), channel)
    return [clamp_int(value) for value in pose]


def smooth_pose(previous: Optional[list[int]], current: list[int], alpha: float) -> list[int]:
    if previous is None or alpha >= 1.0:
        return list(current)
    if alpha <= 0.0:
        return list(previous)
    return [
        clamp_int(previous_value + alpha * (current_value - previous_value))
        for previous_value, current_value in zip(previous, current)
    ]


def limit_delta(previous: Optional[list[int]], current: list[int], max_delta: int) -> list[int]:
    if previous is None or max_delta <= 0:
        return list(current)
    limited = []
    for previous_value, current_value in zip(previous, current):
        delta = current_value - previous_value
        delta = int(clamp(delta, -max_delta, max_delta))
        limited.append(clamp_int(previous_value + delta))
    return limited


def connect_hand(config: TeleopConfig):
    from LinkerHand.linker_hand_api import LinkerHandApi

    print(
        "Connecting LinkerHand SDK: "
        f'LinkerHandApi(hand_type="{config.hand_type}", '
        f'hand_joint="{config.hand_joint}", can="{config.can}")'
    )
    return LinkerHandApi(hand_type=config.hand_type, hand_joint=config.hand_joint, can=config.can)


def send_pose(api: Any, pose: list[int]) -> None:
    api.finger_move(pose=pose)


def print_glove(values: Mapping[str, float]) -> None:
    ordered = " ".join(f"{key}={values[key]:.1f}" for key in sorted(values))
    print(f"glove {ordered}")


def print_pose(pose: Iterable[int]) -> None:
    print(f"pose {[int(value) for value in pose]}")


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    if args.hz is not None:
        config = TeleopConfig(**{**config.__dict__, "control_hz": float(args.hz)})
    if args.can is not None:
        config = TeleopConfig(**{**config.__dict__, "can": str(args.can)})

    dry_run = config.dry_run
    if args.dry_run:
        dry_run = True
    if args.no_dry_run:
        dry_run = False

    if config.hand_joint != "L10":
        raise SystemExit(f"Expected hand_joint L10, got {config.hand_joint}")
    if config.hand_type != "left":
        raise SystemExit(f"Expected hand_type left, got {config.hand_type}")

    reader = GloveReader(mock=args.mock_glove, settings=config.glove_reader)
    interval = 1.0 / max(config.control_hz, 1.0)
    warned_missing: set[str] = set()
    previous_pose: Optional[list[int]] = open_pose_from_config(config)
    api = None

    if dry_run:
        print("Dry run is ON. No LinkerHand movement commands will be sent.")
    else:
        api = connect_hand(config)
        print("LIVE HAND CONTROL IS ON. Keep the L10 clear. Press Ctrl+C to stop.")

    try:
        for glove_values in reader.frames():
            cycle_started = time.monotonic()
            if args.print_glove:
                print_glove(glove_values)

            mapped_pose = map_glove_to_pose(glove_values, config, warned_missing)
            smoothed_pose = smooth_pose(previous_pose, mapped_pose, config.smoothing_alpha)
            pose = limit_delta(previous_pose, smoothed_pose, config.max_delta_per_cycle)
            previous_pose = pose

            if args.print_pose or dry_run:
                print_pose(pose)
            if api is not None:
                send_pose(api, pose)

            elapsed = time.monotonic() - cycle_started
            time.sleep(max(0.0, interval - elapsed))
    except KeyboardInterrupt:
        print("\nCtrl+C received. Stopping teleoperation.")
    finally:
        if api is not None:
            safe_pose = config.safe_exit_pose or open_pose_from_config(config)
            try:
                print(f"Sending safe exit pose: {safe_pose}")
                send_pose(api, safe_pose)
            except Exception as exc:  # noqa: BLE001 - best-effort hardware safety path
                print(f"Warning: could not send safe exit pose: {exc}", file=sys.stderr)
        else:
            print("No hardware command was sent.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Right EG glove to left LinkerHand L10 teleoperation.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML mapping config path.")
    parser.add_argument("--dry-run", action="store_true", help="Print mapped poses without moving the hand.")
    parser.add_argument("--no-dry-run", action="store_true", help="Enable live hand control.")
    parser.add_argument("--print-glove", action="store_true", help="Print raw glove values each cycle.")
    parser.add_argument("--print-pose", action="store_true", help="Print final 10-value L10 pose each cycle.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for debugging.")
    parser.add_argument("--hz", type=float, default=None, help="Override control_hz from config.")
    parser.add_argument("--can", default=None, help="Override SocketCAN channel from config, for example can0.")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.dry_run and args.no_dry_run:
        raise SystemExit("Choose only one of --dry-run or --no-dry-run.")
    run(args)


if __name__ == "__main__":
    main()
