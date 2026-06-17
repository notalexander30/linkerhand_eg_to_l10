#!/usr/bin/env python3
"""Add visible speed/smoothing controls to an existing glove mapping YAML.

Use this on a generated config/l10_left_eg_glove_mapping.auto.yaml so you do not
need to recalibrate just to expose the motion controls.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


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
    data["motion_profile"] = args.motion_profile
    data["smoothing_mode"] = args.smoothing_mode
    data["smoothing_alpha"] = args.smoothing_alpha
    data["one_euro_min_cutoff"] = args.one_euro_min_cutoff
    data["one_euro_beta"] = args.one_euro_beta
    data["one_euro_d_cutoff"] = args.one_euro_d_cutoff
    data["pose_deadband"] = args.pose_deadband
    data["max_delta_per_cycle"] = args.max_delta_per_cycle
    return data


def build_parser() -> argparse.ArgumentParser:
    """CLI controls for choosing responsive or safer motion behavior."""

    parser = argparse.ArgumentParser(description="Expose motion controls in an existing L10 glove YAML.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Mapping YAML to update.")
    parser.add_argument("--control-hz", type=float, default=60.0, help="Command loop rate.")
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
    return parser


def main() -> None:
    """Update the chosen YAML file."""

    args = build_parser().parse_args()
    data = load_yaml(args.config)
    data = apply_motion_controls(data, args)
    save_yaml(args.config, data)


if __name__ == "__main__":
    main()
