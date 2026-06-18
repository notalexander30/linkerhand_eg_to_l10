#!/usr/bin/env python3
"""Bridge a USB KTH5702 glove text stream to a left LinkerHand L10.

The glove shown by the serial console prints lines like:

    KTH5702: | thumb | 0 | 0x68 | 193.50 deg | -30311 | normal | 0 |

This script reads those lines from /dev/ttyUSB0, parses the 15 sensor angles,
maps selected right-glove sensors directly to the 10 left L10 joint values,
and can send them through the official LinkerHand Python SDK.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import linkerhand_l10_sdk as sdk  # noqa: E402


DEFAULT_CALIBRATION = REPO_ROOT / "glove_l10_calibration.json"
SENSOR_COUNT = 15
ANGLE_MAX = 360.0
OPEN_POSE = [255, 255, 255, 255, 255, 255, 128, 67, 89, 255]
FIST_POSE = [90, 0, 0, 0, 0, 0, 128, 67, 89, 197]

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

FINGER_GROUPS = {
    "thumb": [0, 1, 2],
    # This right-hand EG glove reports raw sensors 3..5 as little/pinky and
    # raw sensors 12..14 as index.
    "index": [12, 13, 14],
    "middle": [6, 7, 8],
    "ring": [9, 10, 11],
    "little": [3, 4, 5],
}

POSE_GROUPS = {
    "thumb": [0, 1, 9],
    "index": [2],
    "middle": [3],
    "ring": [4],
    "little": [5],
}

FINGER_NAMES = ["index", "middle", "ring", "little"]

ANGLE_SENSOR_TO_L10_JOINT = {
    2: 0,   # right glove thumb sensor 2 -> left L10 Thumb CMC Pitch
    1: 1,   # right glove thumb sensor 1 -> left L10 Thumb Adduction/Abduction
    0: 9,   # right glove thumb sensor 0 -> left L10 Thumb Rotation
    13: 2,  # right glove index sensor 1 -> left L10 Index Finger MCP Pitch
    12: 6,  # right glove index sensor 0 -> left L10 Index Finger Adduction/Abduction
    7: 3,   # right glove middle sensor 1 -> left L10 Middle Finger MCP Pitch
    10: 4,  # right glove ring sensor 1 -> left L10 Ring Finger MCP Pitch
    9: 7,   # right glove ring sensor 0 -> left L10 Ring Finger Adduction/Abduction
    4: 5,   # right glove little/pinky sensor 1 -> left L10 Pinky Finger MCP Pitch
    3: 8,   # right glove little/pinky sensor 0 -> left L10 Pinky Finger Adduction/Abduction
}

IGNORED_GLOVE_SENSORS = [5, 6, 8, 11, 14]


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def parse_sensor_line(line: str) -> tuple[int, float] | None:
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
    try:
        import serial
    except ImportError as exc:
        raise SystemExit("Missing pyserial. Install it with: python3 -m pip install pyserial") from exc

    try:
        return serial.Serial(port, baudrate=baud, timeout=1)
    except PermissionError as exc:
        raise SystemExit(
            f"No permission to open {port}. Run: sudo usermod -aG dialout $USER && newgrp dialout"
        ) from exc
    except OSError as exc:
        raise SystemExit(f"Could not open {port}: {exc}") from exc


def glove_frames(port: str, baud: int):
    angles: dict[int, float] = {}
    with open_serial(port, baud) as serial_port:
        print(f"Reading glove from {port} at {baud} baud. Press Ctrl+C to stop.")
        while True:
            raw = serial_port.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore")
            parsed = parse_sensor_line(line)
            if parsed is None:
                continue
            index, angle = parsed
            angles[index] = angle
            if index == SENSOR_COUNT - 1 and len(angles) == SENSOR_COUNT:
                yield dict(angles)


def collect_calibration(port: str, baud: int, seconds: float) -> dict[str, float]:
    print(f"Collecting calibration for {seconds:.1f} seconds...")
    deadline = time.monotonic() + seconds
    samples: list[dict[int, float]] = []
    for frame in glove_frames(port, baud):
        samples.append(frame)
        if time.monotonic() >= deadline:
            break

    if len(samples) < 3:
        raise SystemExit("Not enough glove samples. Check the port, baud rate, and glove power.")

    calibration: dict[str, float] = {}
    for index in range(SENSOR_COUNT):
        values = [sample[index] for sample in samples if index in sample]
        if not values:
            raise SystemExit(f"Sensor {index} did not appear during calibration.")
        calibration[str(index)] = round(float(statistics.median(values)), 4)
    return calibration


def load_calibration(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"Calibration file not found: {path}\n"
            "First run open and fist calibration commands shown below."
        )
    with path.open("r", encoding="utf-8") as file:
        calibration = json.load(file)
    if "open" not in calibration or "fist" not in calibration:
        raise SystemExit(f"Calibration file is incomplete: {path}")
    return calibration


def save_calibration(path: Path, name: str, values: dict[str, float]) -> None:
    calibration = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            calibration = json.load(file)
    calibration[name] = values
    calibration["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    calibration["source"] = "KTH5702 USB serial text"
    with path.open("w", encoding="utf-8") as file:
        json.dump(calibration, file, indent=2)
        file.write("\n")
    print(f"Saved {name} calibration to {path}")


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def clamp_int(value: float, low: int = 0, high: int = 255) -> int:
    return int(round(max(low, min(high, value))))


def angle_to_position(angle: float, angle_max: float = ANGLE_MAX) -> int:
    if angle_max <= 0:
        raise ValueError("angle_max must be greater than 0")
    return clamp_int((angle / angle_max) * 255.0)


def sensor_flex(index: int, angle: float, open_angles: dict, fist_angles: dict) -> float | None:
    key = str(index)
    if key not in open_angles or key not in fist_angles:
        return None
    open_angle = float(open_angles[key])
    fist_angle = float(fist_angles[key])
    span = fist_angle - open_angle
    if abs(span) < 1e-6:
        return None
    return clamp((angle - open_angle) / span)


def sensor_flex_map(frame: dict[int, float], open_angles: dict, fist_angles: dict) -> dict[int, float]:
    result: dict[int, float] = {}
    for index, angle in frame.items():
        value = sensor_flex(index, angle, open_angles, fist_angles)
        if value is not None:
            result[index] = value
    return result


def gain_amount(value: float, gain: float) -> float:
    return clamp(value * gain)


def joint_value(joint: int, amount: float) -> int:
    value = OPEN_POSE[joint] + amount * (FIST_POSE[joint] - OPEN_POSE[joint])
    return int(round(clamp(value, 0, 255)))


def pose_from_angle_map(frame: dict[int, float], angle_max: float = ANGLE_MAX) -> tuple[dict[str, float], list[int]]:
    pose = list(OPEN_POSE)
    mapped: dict[str, float] = {}
    for sensor_index, joint_index in ANGLE_SENSOR_TO_L10_JOINT.items():
        angle = frame.get(sensor_index, 0.0)
        position = angle_to_position(angle, angle_max)
        pose[joint_index] = position
        mapped[f"s{sensor_index}->j{joint_index}"] = position
    return mapped, pose


def combine_flex_values(values: list[float], mode: str) -> float:
    if not values:
        return 0.0
    if mode == "max":
        return max(values)
    if mode == "min":
        return min(values)
    return float(statistics.mean(values))


def finger_flex(
    frame: dict[int, float],
    open_angles: dict,
    fist_angles: dict,
    mode: str = "max",
) -> dict[str, float]:
    result: dict[str, float] = {}
    for finger, indexes in FINGER_GROUPS.items():
        values = [
            sensor_flex(index, frame[index], open_angles, fist_angles)
            for index in indexes
            if index in frame
        ]
        values = [value for value in values if value is not None]
        result[finger] = combine_flex_values(values, mode)
    return result


def pose_from_flex(flex: dict[str, float], args=None) -> list[int]:
    pose = list(OPEN_POSE)
    for finger, joints in POSE_GROUPS.items():
        amount = flex.get(finger, 0.0)
        if finger in FINGER_NAMES and args is not None:
            amount = gain_amount(amount, finger_gain(args, finger))
        for joint in joints:
            pose[joint] = joint_value(joint, amount)
    return pose


def pose_from_glove(frame: dict[int, float], open_angles: dict, fist_angles: dict, args) -> tuple[dict[str, float], dict[int, float], list[int]]:
    flex = finger_flex(frame, open_angles, fist_angles, args.finger_mode)
    sensor_amounts = sensor_flex_map(frame, open_angles, fist_angles)
    pose = pose_from_flex(flex, args)

    if args.thumb_mode == "follow-index":
        thumb_base = flex.get("index", 0.0)
        thumb_side = flex.get("index", 0.0)
        thumb_rotation = flex.get("index", 0.0)
    elif args.thumb_mode == "average":
        thumb_base = flex.get("thumb", 0.0)
        thumb_side = flex.get("thumb", 0.0)
        thumb_rotation = flex.get("thumb", 0.0)
    else:
        thumb_base = sensor_amounts.get(2, flex.get("thumb", 0.0))
        thumb_side = sensor_amounts.get(1, flex.get("thumb", 0.0))
        thumb_rotation = sensor_amounts.get(0, flex.get("thumb", 0.0))

    thumb_base = gain_amount(thumb_base, args.thumb_gain)
    thumb_side = gain_amount(thumb_side, args.thumb_gain)
    thumb_rotation = gain_amount(thumb_rotation, args.thumb_gain)

    if args.invert_thumb:
        thumb_base = 1.0 - thumb_base
        thumb_side = 1.0 - thumb_side
        thumb_rotation = 1.0 - thumb_rotation

    pose[0] = joint_value(0, thumb_base)
    pose[1] = joint_value(1, thumb_side)
    pose[9] = joint_value(9, thumb_rotation)
    flex["thumb_base"] = thumb_base
    flex["thumb_side"] = thumb_side
    flex["thumb_rotation"] = thumb_rotation
    return flex, sensor_amounts, pose


def finger_gain(args, finger: str) -> float:
    specific = getattr(args, f"{finger}_gain")
    if specific is not None:
        return specific
    return args.finger_gain


def connect_hand(args):
    sdk_args = SimpleNamespace(can=args.hand_can, hand_type=args.hand, force=args.force)
    api, info = sdk.connect_sdk(sdk_args)
    sdk.require_detected(sdk_args, info)
    return api


def close_hand(api) -> None:
    sdk.close_sdk(api)


def print_preview(frame: dict[int, float], flex: dict[str, float] | None, pose: list[int] | None) -> None:
    angles = " ".join(f"{index}:{frame[index]:.1f}" for index in range(SENSOR_COUNT) if index in frame)
    print(f"angles {angles}")
    if flex is not None and pose is not None:
        flex_text = " ".join(f"{finger}={value:.2f}" for finger, value in flex.items())
        print(f"flex {flex_text}")
        print(f"pose {pose}")


def run_bridge(args) -> None:
    open_angles = None
    fist_angles = None
    if args.mapping == "calibrated":
        calibration = load_calibration(args.calibration)
        open_angles = calibration["open"]
        fist_angles = calibration["fist"]

    api = None
    if args.send:
        api = connect_hand(args)
        print("LIVE SEND IS ON. Keep the hand clear. Press Ctrl+C to stop.")
    else:
        print("Preview only. Add --send when the mapping looks correct.")
    if args.mapping == "angle":
        ignored = ", ".join(str(index) for index in IGNORED_GLOVE_SENSORS)
        print(f"Mapping: angle. 0 deg -> 0, {args.angle_max:g} deg -> 255.")
        print(f"Ignoring glove sensors: {ignored}")
    else:
        print("Mapping: calibrated open/fist.")

    min_interval = 1.0 / max(args.rate, 1.0)
    last_send = 0.0
    try:
        for frame in glove_frames(args.glove_port, args.baud):
            now = time.monotonic()
            if now - last_send < min_interval:
                continue
            last_send = now

            if args.mapping == "angle":
                flex, pose = pose_from_angle_map(frame, args.angle_max)
            else:
                flex, _sensor_amounts, pose = pose_from_glove(frame, open_angles, fist_angles, args)
            print_preview(frame, flex, pose)
            if api is not None:
                api.finger_move(pose=pose)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        close_hand(api)


def run_raw_preview(args) -> None:
    try:
        for frame in glove_frames(args.glove_port, args.baud):
            print_preview(frame, None, None)
    except KeyboardInterrupt:
        print("\nStopped.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USB KTH5702 glove to LinkerHand L10 bridge.")
    parser.add_argument("--glove-port", default="/dev/ttyUSB0", help="USB serial port for the glove.")
    parser.add_argument("--baud", type=int, default=115200, help="Glove serial baud rate.")
    parser.add_argument("--hand-can", default="can0", help="SocketCAN interface for the L10 hand.")
    parser.add_argument("--hand", choices=["left", "right"], default="left", help="Controlled L10 hand side.")
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--calibrate-open", action="store_true", help="Hold the glove open and save open calibration.")
    parser.add_argument("--calibrate-fist", action="store_true", help="Hold a fist and save closed/fist calibration.")
    parser.add_argument("--seconds", type=float, default=3.0, help="Calibration duration.")
    parser.add_argument("--raw", action="store_true", help="Only print parsed glove angles.")
    parser.add_argument("--send", action="store_true", help="Actually send mapped poses to the hand.")
    parser.add_argument("--force", action="store_true", help="Allow hand movement even if SDK detection fails.")
    parser.add_argument("--rate", type=float, default=15.0, help="Maximum send/print rate in Hz.")
    parser.add_argument(
        "--mapping",
        choices=["angle", "calibrated"],
        default="angle",
        help="angle maps 0..360 degrees directly to 0..255 positions. calibrated uses open/fist calibration.",
    )
    parser.add_argument("--angle-max", type=float, default=ANGLE_MAX, help="Glove angle that maps to position 255.")
    parser.add_argument(
        "--finger-mode",
        choices=["max", "average", "min"],
        default="max",
        help="Only for --mapping calibrated. How to combine the 3 glove sensors on each non-thumb finger.",
    )
    parser.add_argument("--finger-gain", type=float, default=1.85, help="Increase/decrease non-thumb finger closing strength.")
    parser.add_argument("--index-gain", type=float, default=None, help="Optional index-only gain override.")
    parser.add_argument("--middle-gain", type=float, default=None, help="Optional middle-only gain override.")
    parser.add_argument("--ring-gain", type=float, default=None, help="Optional ring-only gain override.")
    parser.add_argument("--little-gain", type=float, default=None, help="Optional little-only gain override.")
    parser.add_argument(
        "--thumb-mode",
        choices=["direct", "average", "follow-index"],
        default="direct",
        help="Thumb mapping. direct uses sensors 0/1/2 separately; follow-index is a fallback test.",
    )
    parser.add_argument("--thumb-gain", type=float, default=1.35, help="Increase/decrease thumb movement strength.")
    parser.add_argument("--invert-thumb", action="store_true", help="Use only if thumb moves opposite in calibrated mode.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.calibrate_open:
        print("Hold the glove in a relaxed OPEN hand pose.")
        values = collect_calibration(args.glove_port, args.baud, args.seconds)
        save_calibration(args.calibration, "open", values)
        return
    if args.calibrate_fist:
        print("Hold the glove in a closed FIST pose.")
        values = collect_calibration(args.glove_port, args.baud, args.seconds)
        save_calibration(args.calibration, "fist", values)
        return
    if args.raw:
        run_raw_preview(args)
        return
    run_bridge(args)


if __name__ == "__main__":
    main()
