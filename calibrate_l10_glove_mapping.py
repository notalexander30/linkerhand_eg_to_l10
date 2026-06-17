#!/usr/bin/env python3
"""Find a 15-sensor glove to 10-motor L10 mapping.

The workflow is:

1. Send an open pose to the left L10. By default this is ten 255 values because
   it matches the common "set-state 255" test command.
2. Record the glove's open baseline.
3. For each L10 motor, ask the user to move the matching right-glove finger/DOF.
4. Pick the glove sensor with the largest movement and write a YAML config.

The result is a starting point. After generating it, test with
control_l10_left_from_eg_glove.py in dry-run mode before live control.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from control_l10_left_from_eg_glove import (  # noqa: E402
    DEFAULT_CAN,
    DEFAULT_CONFIG,
    GloveReader,
    TeleopConfig,
    clamp_int,
    load_config,
    open_pose_from_config,
)


DEFAULT_OUTPUT = REPO_ROOT / "config" / "l10_left_eg_glove_mapping.auto.yaml"
ALL_255_OPEN_POSE = [255] * 10

SENSOR_KEYS = [
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

SENSOR_INDEX_BY_KEY = {key: index for index, key in enumerate(SENSOR_KEYS)}

MOTOR_NAMES = {
    0: "Thumb Base",
    1: "Thumb Side Swing",
    2: "Index Base",
    3: "Middle Base",
    4: "Ring Base",
    5: "Pinky Base",
    6: "Index Side Swing",
    7: "Ring Side Swing",
    8: "Pinky Side Swing",
    9: "Thumb Rotation",
}

MOTOR_PROMPTS = {
    0: "Bend only the RIGHT thumb base joint from open toward closed.",
    1: "Move only the RIGHT thumb side/swing motion.",
    2: "Bend only the RIGHT index finger.",
    3: "Bend only the RIGHT middle finger.",
    4: "Bend only the RIGHT ring finger.",
    5: "Bend only the RIGHT pinky finger.",
    6: "Move the RIGHT index side/splay motion if the glove exposes it.",
    7: "Move the RIGHT ring side/splay motion if the glove exposes it.",
    8: "Move the RIGHT pinky side/splay motion if the glove exposes it.",
    9: "Rotate or oppose the RIGHT thumb, whichever changes the glove thumb rotation sensor.",
}


@dataclass(frozen=True)
class SensorMatch:
    motor_index: int
    glove_key: str
    glove_open: float
    glove_closed: float
    delta: float
    confidence: float
    top_candidates: list[tuple[str, float]]


def wait_for_enter(message: str, *, skip: bool = False) -> None:
    print(message)
    if skip:
        return
    input("Press Enter when ready...")


def median_frame(frame_iter: Iterator[dict[str, float]], sample_count: int) -> dict[str, float]:
    samples: dict[str, list[float]] = {key: [] for key in SENSOR_KEYS}
    while min(len(values) for values in samples.values()) < sample_count:
        frame = next(frame_iter)
        for key in SENSOR_KEYS:
            if key in frame:
                samples[key].append(float(frame[key]))

    return {
        key: float(statistics.median(values))
        for key, values in samples.items()
        if values
    }


def print_frame(title: str, frame: Mapping[str, float]) -> None:
    print(title)
    print("-" * len(title))
    for key in SENSOR_KEYS:
        if key in frame:
            print(f"{SENSOR_INDEX_BY_KEY[key]:2d}. {key:<9} {frame[key]:9.3f}")


def choose_sensor(
    motor_index: int,
    open_frame: Mapping[str, float],
    moved_frame: Mapping[str, float],
    used_sensors: set[str],
    *,
    allow_duplicates: bool,
    min_delta: float,
) -> SensorMatch:
    candidates: list[tuple[str, float]] = []
    for key in SENSOR_KEYS:
        if key not in open_frame or key not in moved_frame:
            continue
        if not allow_duplicates and key in used_sensors:
            continue
        candidates.append((key, moved_frame[key] - open_frame[key]))

    if not candidates:
        raise RuntimeError("no glove sensor candidates were available")

    ranked = sorted(candidates, key=lambda item: abs(item[1]), reverse=True)
    best_key, best_delta = ranked[0]
    second_delta = abs(ranked[1][1]) if len(ranked) > 1 else 0.0
    confidence = abs(best_delta) / second_delta if second_delta > 1e-9 else 999.0
    if abs(best_delta) < min_delta:
        print(
            f"Warning: {MOTOR_NAMES.get(motor_index, motor_index)} only moved "
            f"{best_delta:.3f}. The selected sensor may be noisy.",
            file=sys.stderr,
        )

    return SensorMatch(
        motor_index=motor_index,
        glove_key=best_key,
        glove_open=float(open_frame[best_key]),
        glove_closed=float(moved_frame[best_key]),
        delta=float(best_delta),
        confidence=float(confidence),
        top_candidates=[(key, delta) for key, delta in ranked[:3]],
    )


def connect_hand(config: TeleopConfig):
    from LinkerHand.linker_hand_api import LinkerHandApi

    print(
        "Connecting LinkerHand SDK: "
        f'LinkerHandApi(hand_type="{config.hand_type}", '
        f'hand_joint="{config.hand_joint}", can="{config.can}")'
    )
    return LinkerHandApi(hand_type=config.hand_type, hand_joint=config.hand_joint, can=config.can)


def send_open_pose(api: Any, pose: list[int], *, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY RUN] Would send L10 open pose: {pose}")
        return
    print(f"Sending L10 open pose: {pose}")
    api.finger_move(pose=pose)
    time.sleep(0.5)


def select_open_pose(config: TeleopConfig, mode: str) -> list[int]:
    if mode == "all-255":
        return list(ALL_255_OPEN_POSE)
    if mode == "config-open":
        return open_pose_from_config(config)
    if mode == "safe-exit":
        return list(config.safe_exit_pose or open_pose_from_config(config))
    raise ValueError(f"unknown open pose mode: {mode}")


def build_reader(args: argparse.Namespace, config: TeleopConfig) -> GloveReader:
    settings = dict(config.glove_reader)
    settings["mode"] = "serial"
    settings["port"] = args.glove_port
    settings["baud"] = args.baud
    return GloveReader(mock=args.mock_glove, settings=settings)


def write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install dependencies with: python3 -m pip install -r requirements.txt") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)
    print(f"Wrote calibrated mapping: {path}")


def build_output_config(
    template: TeleopConfig,
    matches: Iterable[SensorMatch],
    args: argparse.Namespace,
) -> dict[str, Any]:
    matches_by_motor = {match.motor_index: match for match in matches}
    channels = []
    for channel in template.channels:
        match = matches_by_motor[channel.motor_index]
        channels.append(
            {
                "name": channel.name,
                "glove_key": match.glove_key,
                "source_sensor_index": SENSOR_INDEX_BY_KEY.get(match.glove_key),
                "motor_index": channel.motor_index,
                "glove_open": round(match.glove_open, 5),
                "glove_closed": round(match.glove_closed, 5),
                "hand_open": channel.hand_open,
                "hand_closed": channel.hand_closed,
                "invert": False,
                "gain": float(args.gain),
                "match_delta": round(match.delta, 5),
                "match_confidence": round(match.confidence, 3),
            }
        )

    return {
        "hand_joint": template.hand_joint,
        "hand_type": template.hand_type,
        "can": args.can,
        "control_hz": template.control_hz,
        "dry_run": True,
        "smoothing_alpha": template.smoothing_alpha,
        "max_delta_per_cycle": template.max_delta_per_cycle,
        "motor_count": template.motor_count,
        "safe_exit_pose": template.safe_exit_pose or open_pose_from_config(template),
        "glove_reader": {
            "mode": "serial",
            "port": args.glove_port,
            "baud": args.baud,
        },
        "metadata": {
            "generated_by": "calibrate_l10_glove_mapping.py",
            "open_pose_command": args.open_pose,
            "samples_per_step": args.samples,
            "allow_duplicate_sensors": args.allow_duplicate_sensors,
            "notes": (
                "Right glove maps to left L10 by anatomical finger name. "
                "Use gain as the master-to-slave movement multiplier."
            ),
        },
        "channels": channels,
    }


def print_match(match: SensorMatch) -> None:
    print(
        f"Selected glove sensor {match.glove_key} "
        f"(index {SENSOR_INDEX_BY_KEY.get(match.glove_key)}) "
        f"delta={match.delta:.3f} confidence={match.confidence:.2f}"
    )
    top = ", ".join(f"{key}:{delta:.3f}" for key, delta in match.top_candidates)
    print(f"Top candidates: {top}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive 15-DOF glove to 10-DOF L10 mapping calibration.")
    parser.add_argument("--template", type=Path, default=DEFAULT_CONFIG, help="Existing mapping config to use as a template.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Generated YAML config path.")
    parser.add_argument("--glove-port", default="/dev/ttyUSB0", help="USB serial port for the glove.")
    parser.add_argument("--baud", type=int, default=115200, help="Glove serial baud rate.")
    parser.add_argument("--can", default=DEFAULT_CAN, help="SocketCAN channel for the L10.")
    parser.add_argument("--samples", type=int, default=35, help="Frames to collect for each prompt.")
    parser.add_argument("--settle", type=float, default=0.4, help="Seconds to wait after each prompt before sampling.")
    parser.add_argument("--gain", type=float, default=1.0, help="Movement multiplier written to each channel.")
    parser.add_argument("--min-delta", type=float, default=5.0, help="Warn when the selected glove sensor moves less than this.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for debugging the script.")
    parser.add_argument("--dry-run", action="store_true", help="Do not send the open pose to the L10.")
    parser.add_argument("--no-dry-run", action="store_true", help="Send the open pose to the L10.")
    parser.add_argument(
        "--open-pose",
        choices=["all-255", "config-open", "safe-exit"],
        default="all-255",
        help="Open pose sent before calibration. Default matches set-state 255.",
    )
    parser.add_argument(
        "--allow-duplicate-sensors",
        action="store_true",
        help="Allow the same glove sensor to be assigned to multiple L10 motors.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip Enter prompts. Mostly useful with --mock-glove.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.dry_run and args.no_dry_run:
        raise SystemExit("Choose only one of --dry-run or --no-dry-run.")
    if args.samples < 1:
        raise SystemExit("--samples must be at least 1.")
    if args.gain < 0:
        raise SystemExit("--gain must be 0 or greater.")
    dry_run = not args.no_dry_run

    template = load_config(args.template)
    template = TeleopConfig(**{**template.__dict__, "can": args.can})
    open_pose = select_open_pose(template, args.open_pose)
    reader = build_reader(args, template)
    frame_iter = reader.frames()
    api = None

    try:
        if not dry_run:
            api = connect_hand(template)
        send_open_pose(api, [clamp_int(value) for value in open_pose], dry_run=dry_run)

        wait_for_enter(
            "\nOpen your RIGHT glove hand fully and hold it still.",
            skip=args.non_interactive,
        )
        time.sleep(max(0.0, args.settle))
        open_frame = median_frame(frame_iter, args.samples)
        print_frame("Glove Open Baseline", open_frame)

        matches: list[SensorMatch] = []
        used_sensors: set[str] = set()
        for channel in template.channels:
            motor_name = MOTOR_NAMES.get(channel.motor_index, channel.name)
            prompt = MOTOR_PROMPTS.get(channel.motor_index, f"Move glove DOF for {motor_name}.")
            wait_for_enter(
                f"\nCalibrating L10 motor {channel.motor_index}: {motor_name}\n"
                f"{prompt}\nHold the moved/closed pose steady.",
                skip=args.non_interactive,
            )
            time.sleep(max(0.0, args.settle))
            moved_frame = median_frame(frame_iter, args.samples)
            match = choose_sensor(
                channel.motor_index,
                open_frame,
                moved_frame,
                used_sensors,
                allow_duplicates=args.allow_duplicate_sensors,
                min_delta=args.min_delta,
            )
            matches.append(match)
            used_sensors.add(match.glove_key)
            print_match(match)

            wait_for_enter(
                "Return the glove to the fully open pose.",
                skip=args.non_interactive,
            )
            time.sleep(max(0.0, args.settle))

        output = build_output_config(template, matches, args)
        write_yaml(args.output, output)
        print("\nNext dry-run test:")
        print(
            "python3 control_l10_left_from_eg_glove.py "
            f"--config {args.output} --dry-run --print-glove --print-pose"
        )
    except KeyboardInterrupt:
        print("\nCalibration stopped.")
    finally:
        if api is not None:
            try:
                send_open_pose(api, [clamp_int(value) for value in open_pose], dry_run=False)
            except Exception as exc:  # noqa: BLE001 - best effort on hardware exit
                print(f"Warning: could not re-send open pose: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
