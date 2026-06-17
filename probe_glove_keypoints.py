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
FEATURE_TESTS = [
    {
        "motor": 0,
        "label": "thumb CMC pitch",
        "prompt": "Bend only the RIGHT thumb base pitch from open toward closed.",
    },
    {
        "motor": 1,
        "label": "thumb adduction/abduction",
        "prompt": "Move only the RIGHT thumb side-to-side / away-toward palm.",
    },
    {
        "motor": 2,
        "label": "index MCP pitch",
        "prompt": "Bend only the RIGHT index main knuckle open/close.",
    },
    {
        "motor": 3,
        "label": "middle MCP pitch",
        "prompt": "Bend only the RIGHT middle main knuckle open/close.",
    },
    {
        "motor": 4,
        "label": "ring MCP pitch",
        "prompt": "Bend only the RIGHT ring main knuckle open/close.",
    },
    {
        "motor": 5,
        "label": "pinky MCP pitch",
        "prompt": "Bend only the RIGHT pinky main knuckle open/close.",
    },
    {
        "motor": 6,
        "label": "index adduction/abduction",
        "prompt": "Move only the RIGHT index side-swing / spread motion.",
    },
    {
        "motor": 7,
        "label": "ring adduction/abduction",
        "prompt": "Move only the RIGHT ring side-swing / spread motion.",
    },
    {
        "motor": 8,
        "label": "pinky adduction/abduction",
        "prompt": "Move only the RIGHT pinky side-swing / spread motion.",
    },
    {
        "motor": 9,
        "label": "thumb rotation",
        "prompt": "Rotate / oppose only the RIGHT thumb across the palm.",
    },
]
FEATURE_BY_MOTOR = {int(feature["motor"]): feature for feature in FEATURE_TESTS}
REFERENCE_GLOVE_KEYS_BY_MOTOR = {
    0: "thumb_2",
    1: "thumb_1",
    2: "index_2",
    3: "middle_2",
    4: "ring_2",
    5: "pinky_2",
    6: "index_1",
    7: "ring_1",
    8: "pinky_1",
}
DISABLED_REFERENCE_MOTORS = {9}


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


def print_copy_block(
    *,
    motor_index: int | None,
    glove_key: str,
    open_frame: Mapping[str, float],
    moved_frame: Mapping[str, float],
) -> None:
    """Print a small block the user can paste back into chat."""

    print("\nCopy this back to Codex if you want me to verify it:")
    print(f"motor={motor_index}")
    print(f"best_glove_key={glove_key}")
    print(f"source_sensor_index={SOURCE_SENSOR_INDEX_BY_KEY[glove_key]}")
    print(f"glove_open={open_frame[glove_key]:.5f}")
    print(f"glove_closed={moved_frame[glove_key]:.5f}")


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


def disable_channel(data: dict[str, Any], motor_index: int, fixed_value: int = 255) -> None:
    """Mark a YAML channel disabled and hold it at a fixed L10 value."""

    channel = find_channel(data, motor_index)
    channel["enabled"] = False
    channel["fixed_value"] = fixed_value
    metadata = dict(data.get("metadata", {}))
    metadata["last_disabled_motor"] = motor_index
    metadata["last_disabled_fixed_value"] = fixed_value
    data["metadata"] = metadata


def select_glove_key(
    args: argparse.Namespace,
    *,
    motor_index: int | None,
    default_key: str,
) -> str | None:
    """Choose the glove key to write, with an optional manual override."""

    if args.glove_key is not None:
        return args.glove_key
    if args.no_write or args.auto_select or args.non_interactive:
        return default_key

    while True:
        answer = input(
            f"Use glove_key for motor {motor_index} "
            f"[{default_key}]? Enter=accept, type key, or 'skip': "
        ).strip()
        if not answer:
            return default_key
        if answer.lower() in {"skip", "s"}:
            return None
        if answer in SOURCE_SENSOR_INDEX_BY_KEY:
            return answer
        print(f"Unknown glove_key {answer!r}. Example keys: index_0, pinky_0, thumb_2.")


def default_key_for_motor(motor_index: int | None, ranked: list[tuple[str, float]]) -> str:
    """Prefer the user-guided reference key, then fall back to strongest delta."""

    if motor_index in REFERENCE_GLOVE_KEYS_BY_MOTOR:
        return REFERENCE_GLOVE_KEYS_BY_MOTOR[int(motor_index)]
    return ranked[0][0]


def build_reader(args: argparse.Namespace, data: Mapping[str, Any]) -> GloveReader:
    """Create the EG glove reader from CLI values and YAML defaults."""

    settings = dict(data.get("glove_reader", {}))
    settings["mode"] = "serial"
    settings["port"] = args.glove_port
    settings["baud"] = args.baud
    return GloveReader(mock=args.mock_glove, settings=settings)


def capture_feature_pair(
    args: argparse.Namespace,
    frame_iter: Iterator[dict[str, float]],
    *,
    label: str,
    move_prompt: str,
) -> tuple[dict[str, float], dict[str, float], list[tuple[str, float]]]:
    """Capture one open pose and one moved pose for a feature."""

    wait_for_enter(f"\nOpen your RIGHT glove hand fully for {label}.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    open_frame = median_frame(frame_iter, list(SERIAL_SENSOR_KEYS), args.samples)

    wait_for_enter(f"\n{move_prompt}\nHold still.", skip=args.non_interactive)
    time.sleep(max(0.0, args.settle))
    moved_frame = median_frame(frame_iter, list(SERIAL_SENSOR_KEYS), args.samples)

    ranked = rank_sensor_deltas(open_frame, moved_frame)
    if not ranked:
        raise SystemExit("No glove sensor data was captured.")
    return open_frame, moved_frame, ranked


def selected_feature_tests(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Return the feature tests requested by --all-features/--motors."""

    if args.motors is None:
        return list(FEATURE_TESTS)

    tests = []
    for motor_index in args.motors:
        if motor_index not in FEATURE_BY_MOTOR:
            raise SystemExit(f"Unknown L10 motor for feature probing: {motor_index}")
        tests.append(FEATURE_BY_MOTOR[motor_index])
    return tests


def run_all_features(args: argparse.Namespace, data: dict[str, Any], frame_iter: Iterator[dict[str, float]]) -> None:
    """Run a guided open/moved capture for each L10 feature."""

    output_data = load_yaml(args.config) if args.config.exists() else data
    for feature in selected_feature_tests(args):
        motor_index = int(feature["motor"])
        label = str(feature["label"])
        prompt = str(feature["prompt"])
        print("\n" + "=" * 72)
        print(f"L10 motor {motor_index}: {label}")
        print("=" * 72)

        if motor_index in DISABLED_REFERENCE_MOTORS:
            print("Reference mapping disables this L10 motor; no glove_key will be used.")
            if not args.no_write:
                disable_channel(output_data, motor_index)
                save_yaml(args.config, output_data)
            continue

        open_frame, moved_frame, ranked = capture_feature_pair(
            args,
            frame_iter,
            label=label,
            move_prompt=prompt,
        )
        print_probe_table(open_frame, moved_frame, ranked, args.top)

        default_key = default_key_for_motor(motor_index, ranked)
        if default_key != ranked[0][0]:
            print(f"\nReference glove_key for motor {motor_index}: {default_key}")
            print(f"Strongest moved sensor was: {ranked[0][0]}")
        selected_key = select_glove_key(args, motor_index=motor_index, default_key=default_key)
        print_copy_block(
            motor_index=motor_index,
            glove_key=selected_key or default_key,
            open_frame=open_frame,
            moved_frame=moved_frame,
        )

        if args.no_write:
            print("\nYAML was not changed for this feature.")
            continue
        if selected_key is None:
            print("\nSkipped YAML update for this feature.")
            continue

        patch_channel(output_data, motor_index, selected_key, open_frame[selected_key], moved_frame[selected_key], ranked)
        save_yaml(args.config, output_data)


def build_parser() -> argparse.ArgumentParser:
    """CLI for probing one glove open/moved keypoint pair."""

    parser = argparse.ArgumentParser(description="Probe EG glove keypoints and optionally patch one L10 YAML motor.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="YAML mapping to update.")
    parser.add_argument("--motor", type=int, default=None, help="L10 motor index to patch with the strongest sensor.")
    parser.add_argument("--all-features", action="store_true", help="Probe all 10 L10 features one-by-one.")
    parser.add_argument("--motors", nargs="+", type=int, default=None, help="With --all-features, probe only these motors.")
    parser.add_argument("--glove-key", default=None, help="Force this glove_key instead of the strongest moved sensor.")
    parser.add_argument("--label", default="target finger", help="Text shown in prompts, for example index or pinky.")
    parser.add_argument("--glove-port", default="/dev/ttyUSB0", help="USB serial port for the EG glove.")
    parser.add_argument("--baud", type=int, default=115200, help="Glove serial baud rate.")
    parser.add_argument("--samples", type=int, default=35, help="Samples to collect for each pose.")
    parser.add_argument("--settle", type=float, default=0.4, help="Seconds to wait after each prompt.")
    parser.add_argument("--top", type=int, default=6, help="How many strongest sensor candidates to print.")
    parser.add_argument("--no-write", action="store_true", help="Only print captured values; do not patch YAML.")
    parser.add_argument("--auto-select", action="store_true", help="Write the strongest sensor without asking for confirmation.")
    parser.add_argument("--mock-glove", action="store_true", help="Use generated glove values for testing.")
    parser.add_argument("--non-interactive", action="store_true", help="Skip Enter prompts.")
    return parser


def main() -> None:
    """Capture open/moved keypoints, print candidates, and optionally patch YAML."""

    args = build_parser().parse_args()
    if args.all_features and args.motor is not None:
        raise SystemExit("Use either --all-features or --motor, not both.")
    if args.motors is not None and not args.all_features:
        raise SystemExit("--motors is only valid with --all-features.")
    if args.glove_key is not None and args.all_features:
        raise SystemExit("--glove-key is only valid for one --motor probe.")
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

    if args.all_features:
        run_all_features(args, data, frame_iter)
        return
    if args.motor in DISABLED_REFERENCE_MOTORS and args.glove_key is None:
        if args.no_write:
            print(f"Motor {args.motor} is disabled by the reference mapping; YAML was not changed.")
            return
        output_data = load_yaml(args.config) if args.config.exists() else data
        disable_channel(output_data, args.motor)
        save_yaml(args.config, output_data)
        return

    open_frame, moved_frame, ranked = capture_feature_pair(
        args,
        frame_iter,
        label=args.label,
        move_prompt=f"Move/close only the RIGHT glove {args.label}",
    )
    print_probe_table(open_frame, moved_frame, ranked, args.top)

    default_key = default_key_for_motor(args.motor, ranked)
    if default_key != ranked[0][0]:
        print(f"\nReference glove_key for motor {args.motor}: {default_key}")
        print(f"Strongest moved sensor was: {ranked[0][0]}")
    selected_key = select_glove_key(args, motor_index=args.motor, default_key=default_key)
    print_copy_block(
        motor_index=args.motor,
        glove_key=selected_key or default_key,
        open_frame=open_frame,
        moved_frame=moved_frame,
    )

    if args.motor is None or args.no_write:
        print("\nYAML was not changed.")
        return
    if selected_key is None:
        print("\nSkipped YAML update.")
        return

    output_data = load_yaml(args.config) if args.config.exists() else data
    patch_channel(output_data, args.motor, selected_key, open_frame[selected_key], moved_frame[selected_key], ranked)
    save_yaml(args.config, output_data)


if __name__ == "__main__":
    main()
