#!/usr/bin/env python3
"""SDK-first command tool for a left LinkerHand L10.

This script intentionally keeps the official LinkerHand Python SDK as the main
control path. It creates LinkerHandApi, reads get_embedded_version()/get_state(),
and sends movement only through LinkerHandApi.finger_move().
"""

import argparse
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CAN = "can0"
DEFAULT_HAND_TYPE = "left"
HAND_JOINT = "L10"
BITRATE = "1000000"
PRESETS_PATH = REPO_ROOT / "example" / "terminal_control" / "poses_l10.json"

JOINT_NAMES = [
    "Thumb Base",
    "Thumb Side Swing",
    "Index Base",
    "Middle Base",
    "Ring Base",
    "Little Base",
    "Index Side Swing",
    "Ring Side Swing",
    "Little Side Swing",
    "Thumb Rotation",
]

HOME_POSE = [255] * 10
ZERO_POSE = [0] * 10


class SafetyError(RuntimeError):
    """Raised when a movement command should not be sent."""


def run(command, check=False, quiet=False):
    if not quiet:
        print("+", " ".join(command))
    return subprocess.run(command, text=True, check=check)


def load_sdk():
    from LinkerHand.linker_hand_api import LinkerHandApi

    return LinkerHandApi


def load_presets():
    with PRESETS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_presets(presets):
    with PRESETS_PATH.open("w", encoding="utf-8") as file:
        json.dump(presets, file, indent=2)
        file.write("\n")


def normalize_name(name):
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def validate_pose(values):
    if len(values) != 10:
        raise argparse.ArgumentTypeError(f"L10 requires exactly 10 values, got {len(values)}")
    pose = [int(value) for value in values]
    invalid = [value for value in pose if value < 0 or value > 255]
    if invalid:
        raise argparse.ArgumentTypeError(f"values must be 0..255, invalid: {invalid}")
    return pose


def parse_csv_pose(text):
    try:
        return validate_pose([int(part.strip()) for part in text.split(",")])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("values must be comma-separated integers") from exc


def print_pose(title, pose):
    print(f"\n{title}")
    print("-" * len(title))
    for index, (name, value) in enumerate(zip(JOINT_NAMES, pose), start=1):
        print(f"{index:2d}. {name:<18} {int(value):3d}")


def good_serial(serial_number):
    return serial_number not in (None, "", -1, "-1", [])


def valid_version(version):
    return isinstance(version, (list, tuple)) and len(version) >= 7


def valid_state(state):
    if not isinstance(state, list) or len(state) != 10:
        return False
    return all(isinstance(value, (int, float)) and 0 <= value <= 255 for value in state)


def format_version(version):
    if not valid_version(version):
        return "not detected"
    direction = chr(int(version[3])) if 32 <= int(version[3]) <= 126 else str(version[3])
    software = f"V{int(version[4]) >> 4}.{int(version[4]) & 15}"
    hardware = f"V{int(version[5]) >> 4}.{int(version[5]) & 15}"
    return (
        f"degrees={version[0]}, mechanical={version[1]}, serial/index={version[2]}, "
        f"direction={direction}, software={software}, hardware={hardware}, revision={version[6]}"
    )


def read_serial(api):
    serial_number = getattr(api, "serial_number", None)
    if good_serial(serial_number):
        return serial_number

    get_serial = getattr(api, "get_serial_number", None)
    if callable(get_serial):
        try:
            serial_number = get_serial()
            if good_serial(serial_number):
                return serial_number
        except Exception:
            pass

    hand = getattr(api, "hand", None)
    serial_number = getattr(hand, "sn", None)
    if good_serial(serial_number):
        return serial_number

    get_hand_serial = getattr(hand, "get_serial_number", None)
    if callable(get_hand_serial):
        try:
            serial_number = get_hand_serial()
            if good_serial(serial_number):
                return serial_number
        except Exception:
            pass

    return -1


def read_version(api):
    try:
        version = api.get_embedded_version()
    except Exception:
        version = getattr(getattr(api, "hand", None), "version", None)
    if not valid_version(version):
        version = getattr(getattr(api, "hand", None), "version", version)
    return version


def read_state(api):
    try:
        state = api.get_state()
    except Exception:
        return None
    if valid_state(state):
        return [int(value) for value in state]
    return None


def close_sdk(api):
    if api is None:
        return
    # Do not call api.close_can(); in this SDK it brings the Linux can0 device down.
    hand = getattr(api, "hand", None)
    close_interface = getattr(hand, "close_can_interface", None)
    if callable(close_interface):
        try:
            close_interface()
            return
        except Exception:
            pass
    bus = getattr(hand, "bus", None)
    shutdown = getattr(bus, "shutdown", None)
    if callable(shutdown):
        shutdown()


def connect_sdk(args):
    print(f"SDK connect: hand_type={args.hand_type}, hand_joint={HAND_JOINT}, can={args.can}")
    api = load_sdk()(hand_type=args.hand_type, hand_joint=HAND_JOINT, can=args.can)
    version = read_version(api)
    serial_number = read_serial(api)
    state = read_state(api)
    detected_by = []
    if valid_version(version):
        detected_by.append("version")
    if good_serial(serial_number):
        detected_by.append("serial")
    if state is not None:
        detected_by.append("state")
    return api, {
        "version": version,
        "serial": serial_number,
        "state": state,
        "detected": bool(detected_by),
        "detected_by": ",".join(detected_by) if detected_by else "none",
    }


def print_detection(info):
    print("\nSDK Detection")
    print("-------------")
    print(f"Embedded Version Raw: {info['version']}")
    print(f"Decoded Version: {format_version(info['version'])}")
    print(f"Serial Number: {info['serial']}")
    print(f"Detected By: {info['detected_by']}")
    print(f"Hardware Detected: {info['detected']}")
    if info["state"] is not None:
        print_pose("Current State", info["state"])


def require_detected(args, info):
    if args.force or info["detected"]:
        return
    raise SafetyError(
        "SDK did not detect the hand by version, serial, or state. "
        "Movement is blocked. Use --mock to test or --force only if you accept the risk."
    )


def can_down(can):
    run(["sudo", "ip", "link", "set", can, "down"], quiet=False, check=False)


def can_up(can):
    run(["sudo", "ip", "link", "set", can, "type", "can", "bitrate", BITRATE, "restart-ms", "100"], check=True)
    run(["sudo", "ip", "link", "set", can, "txqueuelen", "1000"], check=True)
    run(["sudo", "ip", "link", "set", can, "up"], check=True)


def can_show(can, stats=False):
    command = ["ip"]
    if stats:
        command.extend(["-statistics", "-details"])
    else:
        command.append("-details")
    command.extend(["link", "show", can])
    run(command, check=False)


def kill_old_processes():
    patterns = ["terminal_control.py", "linkerhand_l10_sdk.py", "gui_control.py", "get_set_state.py"]
    skip_pids = {os.getpid(), os.getppid()}
    for pattern in patterns:
        result = subprocess.run(["pgrep", "-f", pattern], text=True, capture_output=True, check=False)
        for line in result.stdout.splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid in skip_pids:
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Killed old process {pid}: {pattern}")
            except ProcessLookupError:
                pass
            except PermissionError:
                print(f"No permission to kill process {pid}: {pattern}")


def command_boot(args):
    if args.mock:
        print("[MOCK] Boot skipped.")
        return
    if shutil.which("ip") is None:
        raise SystemExit("Missing ip command. Install with: sudo apt install iproute2")
    if not args.no_can_setup:
        kill_old_processes()
        can_down(args.can)
        time.sleep(1)
        can_up(args.can)
    can_show(args.can, stats=True)
    api = None
    try:
        api, info = connect_sdk(args)
        print_detection(info)
    finally:
        close_sdk(api)


def command_status(args):
    if args.mock:
        print("[MOCK] Status: no SDK connection.")
        return
    api = None
    try:
        api, info = connect_sdk(args)
        print_detection(info)
    finally:
        close_sdk(api)


def command_state(args):
    if args.mock:
        print_pose("Mock State", HOME_POSE)
        return
    api = None
    try:
        api, _info = connect_sdk(args)
        state = read_state(api)
        if state is None:
            raise SystemExit("SDK did not return a valid 10-value state.")
        print_pose("Current State", state)
    finally:
        close_sdk(api)


def send_pose(args, pose, label):
    print_pose(f"About To Send: {label}", pose)
    if args.mock:
        print("[MOCK] No hardware command sent.")
        return
    api = None
    try:
        api, info = connect_sdk(args)
        require_detected(args, info)
        api.finger_move(pose=pose)
        time.sleep(0.05)
        print("Sent through LinkerHandApi.finger_move().")
        state = read_state(api)
        if state is not None:
            print_pose("State After Command", state)
    finally:
        close_sdk(api)


def command_set_state(args):
    send_pose(args, validate_pose(args.position), "set-state")


def command_set(args):
    send_pose(args, args.values, "set")


def command_list_presets(_args):
    print("Available presets:")
    for name in sorted(load_presets()):
        print(f"  {name}")


def get_preset(name):
    presets = load_presets()
    key = normalize_name(name)
    if key not in presets:
        available = ", ".join(sorted(presets))
        raise SystemExit(f"Unknown preset '{name}'. Available presets: {available}")
    return validate_pose(presets[key])


def command_show_preset(args):
    print_pose(f"Preset: {normalize_name(args.name)}", get_preset(args.name))


def command_preset(args):
    send_pose(args, get_preset(args.name), f"preset {normalize_name(args.name)}")


def command_save_preset(args):
    presets = load_presets()
    key = normalize_name(args.name)
    presets[key] = validate_pose(args.position)
    save_presets(presets)
    print_pose(f"Saved Preset: {key}", presets[key])


def command_stop(_args):
    print("No raw CAN stop command is sent by this SDK tool.")
    print("Use Ctrl+C for foreground sequences or your hardware power/emergency stop.")


def build_parser():
    parser = argparse.ArgumentParser(description="SDK-first LinkerHand L10 hardware tool.")
    parser.add_argument("--can", default=DEFAULT_CAN, help="SocketCAN channel. Default: can0.")
    parser.add_argument("--hand-type", choices=["left", "right"], default=DEFAULT_HAND_TYPE, help="Official SDK hand_type. Default: left.")
    parser.add_argument("--mock", action="store_true", help="Print actions without connecting/sending.")
    parser.add_argument("--force", action="store_true", help="Allow movement even if SDK detection fails.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    boot = subparsers.add_parser("boot", help="Bring CAN up and check SDK detection.")
    boot.add_argument("--no-can-setup", action="store_true", help="Skip sudo ip link setup and only run SDK detection.")

    subparsers.add_parser("status", help="Check SDK detection.")
    subparsers.add_parser("state", help="Read current L10 state.")
    subparsers.add_parser("can-show", help="Show CAN link details.")
    subparsers.add_parser("can-stats", help="Show CAN link counters.")
    subparsers.add_parser("can-reset", help="Reset CAN link without running SDK.")
    subparsers.add_parser("kill", help="Kill old controller/example scripts.")

    set_state = subparsers.add_parser("set-state", help="Send ten position values, official SDK style.")
    set_state.add_argument("--position", nargs=10, required=True, type=int, help="Ten L10 values separated by spaces.")

    set_csv = subparsers.add_parser("set", help="Send comma-separated ten values.")
    set_csv.add_argument("--values", required=True, type=parse_csv_pose, help="Example: 255,255,255,255,255,255,255,255,255,255")

    preset = subparsers.add_parser("preset", help="Run a named preset.")
    preset.add_argument("name", help="Preset name.")

    show_preset = subparsers.add_parser("show-preset", help="Print a preset without sending.")
    show_preset.add_argument("name", help="Preset name.")

    save_preset = subparsers.add_parser("save-preset", help="Save a preset.")
    save_preset.add_argument("name", help="Preset name.")
    save_preset.add_argument("--position", nargs=10, required=True, type=int, help="Ten L10 values separated by spaces.")

    subparsers.add_parser("list-presets", help="List available presets.")
    subparsers.add_parser("home", help="Send all-255 home preset.")
    subparsers.add_parser("zero", help="Send all-zero preset.")
    subparsers.add_parser("stop", help="Print safe stop instructions.")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "boot":
            command_boot(args)
        elif args.command == "status":
            command_status(args)
        elif args.command == "state":
            command_state(args)
        elif args.command == "can-show":
            can_show(args.can)
        elif args.command == "can-stats":
            can_show(args.can, stats=True)
        elif args.command == "can-reset":
            can_down(args.can)
            time.sleep(1)
            can_up(args.can)
            can_show(args.can, stats=True)
        elif args.command == "kill":
            kill_old_processes()
        elif args.command == "set-state":
            command_set_state(args)
        elif args.command == "set":
            command_set(args)
        elif args.command == "list-presets":
            command_list_presets(args)
        elif args.command == "show-preset":
            command_show_preset(args)
        elif args.command == "preset":
            command_preset(args)
        elif args.command == "save-preset":
            command_save_preset(args)
        elif args.command == "home":
            send_pose(args, HOME_POSE, "home")
        elif args.command == "zero":
            send_pose(args, ZERO_POSE, "zero")
        elif args.command == "stop":
            command_stop(args)
        else:
            raise SystemExit(f"Unknown command: {args.command}")
    except SafetyError as exc:
        raise SystemExit(f"SAFETY BLOCK: {exc}") from exc


if __name__ == "__main__":
    main()
