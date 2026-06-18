#!/usr/bin/env python3
"""Add visible speed/smoothing controls to an existing glove mapping YAML.

Use this on a generated config/l10_left_eg_glove_mapping.auto.yaml so you do not
need to recalibrate just to expose the motion controls.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from control_l10_left_from_eg_glove import L10_JOINT_NAMES, SERIAL_SENSOR_KEYS


DEFAULT_CONFIG = Path("config/l10_left_eg_glove_mapping.auto.yaml")
REFERENCE_GLOVE_KEYS_BY_MOTOR = {
    0: "pinky_2",
    1: "pinky_1",
    2: "ring_1",
    3: "middle_1",
    4: "thumb_1",
    5: "index_1",
    6: "ring_0",
    7: "thumb_0",
    8: "index_0",
    9: "pinky_0",
}
SOURCE_SENSOR_INDEX_BY_KEY = {key: index for index, key in enumerate(SERIAL_SENSOR_KEYS)}


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
    """Set speed/smoothing fields and optionally apply the EG-to-L10 key map."""

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
        if args.reference_glove_keys and motor_index in REFERENCE_GLOVE_KEYS_BY_MOTOR:
            glove_key = REFERENCE_GLOVE_KEYS_BY_MOTOR[motor_index]
            channel["glove_key"] = glove_key
            channel["source_sensor_index"] = SOURCE_SENSOR_INDEX_BY_KEY.get(glove_key)
            if motor_index == 9 and not args.disable_thumb_rotation:
                channel["enabled"] = True
                channel["fixed_value"] = None
        if args.disable_thumb_rotation and motor_index == 9:
            channel["enabled"] = False
            channel["fixed_value"] = args.thumb_rotation_fixed_value
    metadata = dict(data.get("metadata", {}))
    if args.reference_glove_keys:
        metadata["reference_mapping"] = (
            "Corrected tested EG sensor offset: thumb=pinky_*, index=ring_*, "
            "middle=middle_*, ring=thumb_*, pinky=index_*"
        )
    metadata["thumb_rotation"] = "enabled from pinky_0" if not args.disable_thumb_rotation else "disabled; motor 9 held fixed"
    data["metadata"] = metadata
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
    parser.add_argument("--send-interval-sec", type=float, default=0.0, help="0.0 sends every loop; 1.0 sends a slow set-state snapshot.")
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
        "--keep-glove-keys",
        dest="reference_glove_keys",
        action="store_false",
        help="Keep existing glove_key values instead of applying the EG-to-L10 reference map.",
    )
    parser.add_argument(
        "--disable-thumb-rotation",
        dest="disable_thumb_rotation",
        action="store_true",
        help="Disable motor 9 thumb rotation and hold it fixed.",
    )
    parser.add_argument("--enable-thumb-rotation", dest="disable_thumb_rotation", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--thumb-rotation-fixed-value", type=int, default=255, help="Fixed value for disabled thumb rotation.")
    parser.set_defaults(disable_thumb_rotation=False, reference_glove_keys=True)
    return parser


def main() -> None:
    """Update the chosen YAML file."""

    args = build_parser().parse_args()
    data = load_yaml(args.config)
    data = apply_motion_controls(data, args)
    save_yaml(args.config, data)


if __name__ == "__main__":
    main()
