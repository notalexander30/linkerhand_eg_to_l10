#!/usr/bin/env python3
"""Add visible speed/smoothing controls to an existing glove mapping YAML.

Use this on a generated config/l10_left_eg_glove_mapping.auto.yaml so you do not
need to recalibrate just to expose the motion controls.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from control_l10_left_from_eg_glove import L10_JOINT_NAMES


DEFAULT_CONFIG = Path("config/l10_left_eg_glove_mapping.auto.yaml")


def load_yaml(path: Path) -> dict[str, Any]:
    """Read the existing calibration YAML."""

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Missing PyYAML. Install with: python3 -m pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write the updated YAML back to disk."""

    import yaml

    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)
    print(f"Updated motion controls in {path}")


def apply_motion_controls(data: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Set the speed/smoothing fields while keeping calibration channels unchanged."""

    data["control_hz"] = args.control_hz
    data["hand_output_mode"] = args.hand_output_mode
    data["normalized_hand_open"] = args.normalized_hand_open
    data["normalized_hand_closed"] = args.normalized_hand_closed
    data["send_interval_sec"] = args.send_interval_sec
    data["motion_profile"] = args.motion_profile
    data["smoothing_mode"] = args.smoothing_mode
    data["smoothing_alpha"] = args.smoothing_alpha
    data["one_euro_min_cutoff"] = args.one_euro_min_cutoff
    data["one_euro_beta"] = args.one_euro_beta
    data["one_euro_d_cutoff"] = args.one_euro_d_cutoff
    data["pose_deadband"] = args.pose_deadband
    data["max_delta_per_cycle"] = args.max_delta_per_cycle
    for channel in data.get("channels", []):
        motor_index = int(channel.get("motor_index", -1))
        if 0 <= motor_index < len(L10_JOINT_NAMES):
            channel["l10_joint_name"] = L10_JOINT_NAMES[motor_index]
        if args.mirror_thumb_abduction and motor_index == 1:
            channel["invert"] = True
        if motor_index in args.invert_motor:
            channel["invert"] = True
        if motor_index in args.uninvert_motor:
            channel["invert"] = False
    return data


def build_parser() -> argparse.ArgumentParser:
    """CLI controls for choosing responsive or safer motion behavior."""

    parser = argparse.ArgumentParser(description="Expose motion controls in an existing L10 glove YAML.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Mapping YAML to update.")
    parser.add_argument("--control-hz", type=float, default=60.0, help="Command loop rate.")
    parser.add_argument(
        "--hand-output-mode",
        choices=["normalized_255", "calibrated"],
        default="normalized_255",
        help="normalized_255 maps every joint to the same 255=open, 0=closed range.",
    )
    parser.add_argument("--normalized-hand-open", type=int, default=255, help="Open command in normalized_255 mode.")
    parser.add_argument("--normalized-hand-closed", type=int, default=0, help="Closed command in normalized_255 mode.")
    parser.add_argument("--send-interval-sec", type=float, default=1.0, help="1.0 sends a set-state snapshot every second; 0.0 sends every loop.")
    parser.add_argument(
        "--motion-profile",
        choices=["responsive_1to1", "safe"],
        default="responsive_1to1",
        help="responsive_1to1 is fastest; safe uses max_delta_per_cycle.",
    )
    parser.add_argument("--smoothing-mode", choices=["one_euro", "ema", "none"], default="one_euro")
    parser.add_argument("--smoothing-alpha", type=float, default=0.18, help="EMA smoothing only.")
    parser.add_argument("--one-euro-min-cutoff", type=float, default=2.0, help="Higher is faster; lower is smoother.")
    parser.add_argument("--one-euro-beta", type=float, default=0.08, help="Higher follows fast motion faster.")
    parser.add_argument("--one-euro-d-cutoff", type=float, default=1.0, help="Usually leave at 1.0.")
    parser.add_argument("--pose-deadband", type=int, default=0, help="0 gives most 1:1 response.")
    parser.add_argument("--max-delta-per-cycle", type=int, default=0, help="0 means no speed cap.")
    parser.add_argument(
        "--mirror-thumb-abduction",
        action="store_true",
        help="Invert motor 1 so right-glove thumb side motion mirrors on the left L10.",
    )
    parser.add_argument("--invert-motor", action="append", type=int, default=[], help="Set invert: true for this L10 motor index.")
    parser.add_argument("--uninvert-motor", action="append", type=int, default=[], help="Set invert: false for this L10 motor index.")
    return parser


def main() -> None:
    """Update the chosen YAML file."""

    args = build_parser().parse_args()
    data = load_yaml(args.config)
    data = apply_motion_controls(data, args)
    save_yaml(args.config, data)


if __name__ == "__main__":
    main()
