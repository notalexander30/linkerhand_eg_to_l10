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
from typing import Any, Iterable, Iterator, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CONFIG = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.yaml"
DEFAULT_CAN = "can0"
L10_JOINT_NAMES = [
    "Thumb CMC Pitch",
    "Thumb Adduction/Abduction",
    "Index Finger MCP Pitch",
    "Middle Finger MCP Pitch",
    "Ring Finger MCP Pitch",
    "Pinky Finger MCP Pitch",
    "Index Finger Adduction/Abduction",
    "Ring Finger Adduction/Abduction",
    "Pinky Finger Adduction/Abduction",
    "Thumb Rotation",
]
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
    """One glove sensor to one L10 motor mapping; tune these under channels in YAML."""

    name: str
    glove_key: str
    motor_index: int
    glove_open: float
    glove_closed: float
    hand_open: int
    hand_closed: int
    l10_joint_name: str = ""
    invert: bool = False
    gain: float = 1.0


@dataclass(frozen=True)
class TeleopConfig:
    """Top-level YAML settings for hand setup, smoothing, speed, and channel mapping."""

    hand_joint: str
    hand_type: str
    can: str
    control_hz: float
    dry_run: bool
    motion_profile: str
    hand_output_mode: str
    normalized_hand_open: int
    normalized_hand_closed: int
    send_interval_sec: float
    smoothing_mode: str
    smoothing_alpha: float
    one_euro_min_cutoff: float
    one_euro_beta: float
    one_euro_d_cutoff: float
    pose_deadband: int
    max_delta_per_cycle: int
    motor_count: int
    channels: list[ChannelMapping]
    safe_exit_pose: Optional[list[int]]
    glove_reader: dict[str, Any]


def clamp(value: float, low: float, high: float) -> float:
    """Limit a float into a safe range; used before sending motor commands."""

    return max(low, min(high, value))


def clamp_int(value: float, low: int = 0, high: int = 255) -> int:
    """Limit an L10 command to 0..255 and round to the integer SDK expects."""

    return int(round(clamp(value, low, high)))


def parse_channel(raw: Mapping[str, Any]) -> ChannelMapping:
    """Read one YAML channel; gain is the per-motor master-to-slave multiplier."""

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

    motor_index = int(raw["motor_index"])
    default_joint_name = L10_JOINT_NAMES[motor_index] if 0 <= motor_index < len(L10_JOINT_NAMES) else str(raw["name"])

    return ChannelMapping(
        name=str(raw["name"]),
        glove_key=str(raw["glove_key"]),
        motor_index=motor_index,
        glove_open=float(raw["glove_open"]),
        glove_closed=float(raw["glove_closed"]),
        hand_open=clamp_int(float(raw["hand_open"])),
        hand_closed=clamp_int(float(raw["hand_closed"])),
        l10_joint_name=str(raw.get("l10_joint_name", default_joint_name)),
        invert=bool(raw.get("invert", False)),
        gain=max(0.0, float(raw.get("gain", raw.get("multiplier", 1.0)))),
    )


def load_config(path: Path) -> TeleopConfig:
    """Load YAML controls; motion_profile decides fast 1:1 mode versus capped safe mode."""

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

    motion_profile = str(raw.get("motion_profile", "responsive_1to1")).lower()
    is_responsive_1to1 = motion_profile in {"responsive_1to1", "one_to_one", "1to1", "fast"}
    configured_max_delta = max(0, int(raw.get("max_delta_per_cycle", 0)))
    max_delta_per_cycle = 0 if is_responsive_1to1 else configured_max_delta

    return TeleopConfig(
        hand_joint=str(raw.get("hand_joint", "L10")),
        hand_type=str(raw.get("hand_type", "left")),
        can=str(raw.get("can", DEFAULT_CAN)),
        control_hz=float(raw.get("control_hz", 60)),
        dry_run=bool(raw.get("dry_run", True)),
        motion_profile=motion_profile,
        hand_output_mode=str(raw.get("hand_output_mode", "normalized_255")).lower(),
        normalized_hand_open=clamp_int(float(raw.get("normalized_hand_open", 255))),
        normalized_hand_closed=clamp_int(float(raw.get("normalized_hand_closed", 0))),
        send_interval_sec=max(0.0, float(raw.get("send_interval_sec", 1.0))),
        smoothing_mode=str(raw.get("smoothing_mode", "one_euro")).lower(),
        smoothing_alpha=clamp(float(raw.get("smoothing_alpha", 1.0)), 0.0, 1.0),
        one_euro_min_cutoff=max(0.001, float(raw.get("one_euro_min_cutoff", 2.0))),
        one_euro_beta=max(0.0, float(raw.get("one_euro_beta", 0.08))),
        one_euro_d_cutoff=max(0.001, float(raw.get("one_euro_d_cutoff", 1.0))),
        pose_deadband=max(0, int(raw.get("pose_deadband", 0 if is_responsive_1to1 else 1))),
        max_delta_per_cycle=max_delta_per_cycle,
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
        """Yield glove frames as dictionaries like {'thumb_0': value, 'index_0': value}."""

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
        """Generate fake opening/closing glove motion for dry-run testing without hardware."""

        keys = list(dict.fromkeys(SERIAL_SENSOR_KEYS))
        while True:
            for flex in itertools.chain(
                [index / 20.0 for index in range(21)],
                [index / 20.0 for index in range(19, 0, -1)],
            ):
                # Mock values use the default 0=open, 1000=closed calibration.
                yield {key: flex * 1000.0 for key in keys}

    def _serial_frames(self) -> Iterator[dict[str, float]]:
        """Use the existing KTH5702 serial parser from glove_to_l10.py for the real glove."""

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


def hand_range_for_channel(channel: ChannelMapping, config: TeleopConfig) -> tuple[int, int]:
    """Choose the L10 open/closed output range for this channel."""

    if config.hand_output_mode in {"normalized_255", "full_range_255", "state_255"}:
        return config.normalized_hand_open, config.normalized_hand_closed
    return channel.hand_open, channel.hand_closed


def map_channel(value: float, channel: ChannelMapping, config: TeleopConfig) -> int:
    """Convert one raw glove value into one L10 motor value using calibration plus gain."""

    normalized = (value - channel.glove_open) / (channel.glove_closed - channel.glove_open)
    normalized = clamp(normalized, 0.0, 1.0)
    if channel.invert:
        normalized = 1.0 - normalized
    normalized = clamp(normalized * channel.gain, 0.0, 1.0)
    hand_open, hand_closed = hand_range_for_channel(channel, config)
    hand_value = hand_open + normalized * (hand_closed - hand_open)
    return clamp_int(hand_value)


def open_pose_from_config(config: TeleopConfig) -> list[int]:
    """Build the open-hand pose from each channel's hand_open value."""

    pose = [255] * config.motor_count
    for channel in config.channels:
        hand_open, _hand_closed = hand_range_for_channel(channel, config)
        pose[channel.motor_index] = clamp_int(hand_open)
    return pose


def map_glove_to_pose(
    glove_values: Mapping[str, float],
    config: TeleopConfig,
    warned_missing: set[str],
) -> list[int]:
    """Convert all available glove values into the full 10-number L10 pose."""

    pose = open_pose_from_config(config)
    for channel in config.channels:
        if channel.glove_key not in glove_values:
            if channel.glove_key not in warned_missing:
                print(
                    f"Warning: missing glove key '{channel.glove_key}' for "
                    f"{channel.l10_joint_name}. Using hand_open={channel.hand_open}.",
                    file=sys.stderr,
                )
                warned_missing.add(channel.glove_key)
            continue
        pose[channel.motor_index] = map_channel(float(glove_values[channel.glove_key]), channel, config)
    return [clamp_int(value) for value in pose]


def smooth_pose(previous: Optional[list[int]], current: list[int], alpha: float) -> list[int]:
    """Simple EMA smoothing; used only when smoothing_mode is 'ema'."""

    if previous is None or alpha >= 1.0:
        return list(current)
    if alpha <= 0.0:
        return list(previous)
    return [
        clamp_int(previous_value + alpha * (current_value - previous_value))
        for previous_value, current_value in zip(previous, current)
    ]


def smoothing_factor(dt: float, cutoff: float) -> float:
    """Convert a One Euro cutoff frequency into a low-pass alpha value."""

    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class LowPassFilter:
    """Tiny reusable low-pass filter used internally by the One Euro filter."""

    def __init__(self, initial_value: Optional[float] = None) -> None:
        self.value = initial_value

    def apply(self, value: float, alpha: float) -> float:
        if self.value is None:
            self.value = value
            return value
        self.value = alpha * value + (1.0 - alpha) * self.value
        return self.value


class OneEuroFilter:
    """Adaptive low-pass filter for human motion input.

    The cutoff rises when the signal moves quickly, which reduces lag, and falls
    when the signal is slow or still, which reduces jitter.
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float, initial_value: float) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.signal_filter = LowPassFilter(initial_value)
        self.derivative_filter = LowPassFilter(0.0)
        self.last_time: Optional[float] = None

    def apply(self, value: float, timestamp: float) -> float:
        """Filter one motor command; beta controls how quickly fast motion passes through."""

        if self.last_time is None:
            self.last_time = timestamp
            return self.signal_filter.apply(value, 1.0)

        dt = max(timestamp - self.last_time, 1e-6)
        self.last_time = timestamp
        previous_value = self.signal_filter.value if self.signal_filter.value is not None else value
        derivative = (value - previous_value) / dt
        filtered_derivative = self.derivative_filter.apply(
            derivative,
            smoothing_factor(dt, self.d_cutoff),
        )
        cutoff = self.min_cutoff + self.beta * abs(filtered_derivative)
        return self.signal_filter.apply(value, smoothing_factor(dt, cutoff))


class PoseSmoother:
    """Applies the selected smoothing_mode and pose_deadband to the 10-motor pose."""

    def __init__(self, config: TeleopConfig, initial_pose: list[int]) -> None:
        self.config = config
        self.previous_pose = list(initial_pose)
        self.filters = [
            OneEuroFilter(
                min_cutoff=config.one_euro_min_cutoff,
                beta=config.one_euro_beta,
                d_cutoff=config.one_euro_d_cutoff,
                initial_value=float(value),
            )
            for value in initial_pose
        ]

    def apply(self, mapped_pose: list[int], timestamp: float) -> list[int]:
        """Return a smoothed pose; tune one_euro_* or smoothing_alpha in YAML."""

        if self.config.smoothing_mode in {"none", "off"}:
            filtered_pose = list(mapped_pose)
        elif self.config.smoothing_mode in {"ema", "exponential"}:
            filtered_pose = smooth_pose(self.previous_pose, mapped_pose, self.config.smoothing_alpha)
        elif self.config.smoothing_mode in {"one_euro", "1euro", "one-euro"}:
            filtered_pose = [
                clamp_int(filter_.apply(float(value), timestamp))
                for filter_, value in zip(self.filters, mapped_pose)
            ]
        else:
            raise SystemExit(f"Unsupported smoothing_mode: {self.config.smoothing_mode}")

        if self.config.pose_deadband > 0:
            filtered_pose = [
                previous if abs(current - previous) <= self.config.pose_deadband else current
                for previous, current in zip(self.previous_pose, filtered_pose)
            ]

        self.previous_pose = [clamp_int(value) for value in filtered_pose]
        return list(self.previous_pose)


def limit_delta(previous: Optional[list[int]], current: list[int], max_delta: int) -> list[int]:
    """Optional speed cap; max_delta_per_cycle=0 means fastest uncapped movement."""

    if previous is None or max_delta <= 0:
        return list(current)
    limited = []
    for previous_value, current_value in zip(previous, current):
        delta = current_value - previous_value
        delta = int(clamp(delta, -max_delta, max_delta))
        limited.append(clamp_int(previous_value + delta))
    return limited


def connect_hand(config: TeleopConfig):
    """Create the LinkerHand SDK object for the left L10 on the configured CAN bus."""

    from LinkerHand.linker_hand_api import LinkerHandApi

    print(
        "Connecting LinkerHand SDK: "
        f'LinkerHandApi(hand_type="{config.hand_type}", '
        f'hand_joint="{config.hand_joint}", can="{config.can}")'
    )
    return LinkerHandApi(hand_type=config.hand_type, hand_joint=config.hand_joint, can=config.can)


def send_pose(api: Any, pose: list[int]) -> None:
    """Send the final 10-value set-state style pose through LinkerHandApi.finger_move()."""

    api.finger_move(pose=pose)


def print_glove(values: Mapping[str, float]) -> None:
    """Debug print for raw glove values; avoid during live control for smoother timing."""

    ordered = " ".join(f"{key}={values[key]:.1f}" for key in sorted(values))
    print(f"glove {ordered}")


def print_pose(pose: Iterable[int]) -> None:
    """Debug print for final L10 pose; avoid during live control for smoother timing."""

    values = [int(value) for value in pose]
    print(f"pose {values}")


def run(args: argparse.Namespace) -> None:
    """Main loop: read glove, map to pose, smooth/limit it, then dry-run or send."""

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
    pose_smoother = PoseSmoother(config, previous_pose)
    last_send_time: Optional[float] = None
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
            smoothed_pose = pose_smoother.apply(mapped_pose, cycle_started)
            pose = limit_delta(previous_pose, smoothed_pose, config.max_delta_per_cycle)
            previous_pose = pose

            send_due = (
                config.send_interval_sec <= 0.0
                or last_send_time is None
                or cycle_started - last_send_time >= config.send_interval_sec
            )
            if send_due:
                last_send_time = cycle_started
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
    """CLI flags override common YAML options like dry-run, CAN, and loop Hz."""

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
    """Program entry point."""

    args = build_parser().parse_args(argv)
    if args.dry_run and args.no_dry_run:
        raise SystemExit("Choose only one of --dry-run or --no-dry-run.")
    run(args)


if __name__ == "__main__":
    main()
