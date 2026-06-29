# LinkerHand EG To L10

Right LinkerHand EG/KTH5702 USB glove teleoperation for a left LinkerHand L10.

```text
right EG glove -> USB serial -> laptop -> SocketCAN can0 -> left LinkerHand L10
```

The main workflow is the YAML controller:

```bash
python3 control_l10_left_from_eg_glove.py --no-dry-run
```

The default controller config is `config/l10_left_eg_glove_mapping.auto.yaml`. It is a tested baseline, not a final universal calibration. If the glove is worn differently, run startup range calibration so the controller updates `glove_open` and `glove_closed` in that YAML before teleoperation starts.

## Safety

- Keep the L10 clear before starting live control.
- Run only one hand controller at a time.
- Start with `--dry-run` before using `--no-dry-run`.
- Stop with `Ctrl+C`; the script sends `safe_exit_pose` on shutdown.
- If the hand moves unexpectedly, stop first, then edit the YAML.

## Hardware

- Right EG/KTH5702 glove on USB serial. The checked-in auto config uses `/dev/ttyUSB0`, but a new computer may show `/dev/ttyUSB1` or another port.
- LinkerHand L10 left hand on SocketCAN. The checked-in auto config uses `can0`.
- USB-to-CAN adapter, powered L10, and a Linux laptop.

These commands assume Ubuntu/Linux with SocketCAN.

## New Computer Setup

Run this once on a fresh computer.

Install system packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip iproute2 can-utils ethtool
```

Clone the repo:

```bash
git clone https://github.com/notalexander30/linkerhand_eg_to_l10.git
cd linkerhand_eg_to_l10
```

Create and activate a local Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Allow your user to read the USB glove serial port:

```bash
sudo usermod -aG dialout $USER
newgrp dialout
```

If `newgrp dialout` does not refresh permissions, log out and log back in.

Plug in the glove, USB-to-CAN adapter, and L10. Then find the glove serial port:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Find the CAN interface:

```bash
ip -br link show type can
bash find_can.sh
```

If the glove is not `/dev/ttyUSB0`, edit `glove_reader.port` in:

```text
config/l10_left_eg_glove_mapping.auto.yaml
```

If the CAN interface is not `can0`, either edit `can` in the YAML or pass `--can can1` when running commands.

## Daily Quick Start

Use this sequence after the computer has already been set up.

```bash
cd linkerhand_eg_to_l10
source .venv/bin/activate
```

Bring up CAN at 1 Mbps:

```bash
sudo ip link set can0 down
sudo ip link set can0 up type can bitrate 1000000
ip -details link show can0
```

Check the L10 before moving it:

```bash
python linkerhand_l10_sdk.py --can can0 --hand-type left state
```

Preview the YAML controller without moving the hand:

```bash
python control_l10_left_from_eg_glove.py --dry-run --print-glove --print-pose
```

If the glove fit changed, re-capture the open/closed ranges in the active auto YAML:

```bash
python control_l10_left_from_eg_glove.py --calibrate-ranges --calibrate-only
```

Or calibrate and immediately continue into dry-run preview:

```bash
python control_l10_left_from_eg_glove.py --calibrate-ranges --dry-run --print-pose
```

Run live after the dry run looks right:

```bash
python control_l10_left_from_eg_glove.py --no-dry-run
```

Avoid `--print-glove` and `--print-pose` during normal live control because terminal printing can make motion less smooth. Stop with `Ctrl+C`; the controller sends `safe_exit_pose` on shutdown.

If your CAN interface is `can1` instead of `can0`, use:

```bash
python control_l10_left_from_eg_glove.py --can can1 --no-dry-run
```

## Current Auto Config

The live robot setup usually uses:

```text
config/l10_left_eg_glove_mapping.auto.yaml
```

Current important settings:

```yaml
glove_reader:
  port: /dev/ttyUSB0
  baud: 115200
can: can0
hand_output_mode: calibrated
motion_profile: responsive_1to1
smoothing_mode: one_euro
startup_calibration:
  enabled: false
```

Thumb rotation is enabled in the current auto config:

```yaml
- name: thumb_2
  glove_key: thumb_1
  motor_index: 9
  l10_joint_name: Thumb Rotation
  enabled: true
  fixed_value: null
```

If the glove appears on a different serial port, edit the YAML or pass `--glove-port` at runtime.

```yaml
glove_reader:
  mode: serial
  port: /dev/ttyUSB0
  baud: 115200
```

The CAN interface and glove serial port can be overridden at runtime:

```bash
python3 control_l10_left_from_eg_glove.py --can can1 --glove-port /dev/ttyUSB1 --no-dry-run
```

## Mapping Basics

L10 motor order:

```text
0 Thumb CMC Pitch
1 Thumb Adduction/Abduction
2 Index Finger MCP Pitch
3 Middle Finger MCP Pitch
4 Ring Finger MCP Pitch
5 Pinky Finger MCP Pitch
6 Index Finger Adduction/Abduction
7 Ring Finger Adduction/Abduction
8 Pinky Finger Adduction/Abduction
9 Thumb Rotation
```

EG glove raw sensor names used by the YAML controller:

```text
0  pinky_0
1  pinky_1
2  pinky_2
3  ring_0
4  ring_1
5  ring_2
6  middle_0
7  middle_1
8  middle_2
9  index_0
10 index_1
11 index_2
12 thumb_0
13 thumb_1
14 thumb_2
```

In each YAML channel:

```yaml
glove_key: index_1      # which glove sensor controls this motor
source_sensor_index: 10 # note/debug value for the raw sensor index
motor_index: 2          # which L10 motor moves
```

To change which glove sensor drives a motor, edit `glove_key` and `source_sensor_index` together. Do not change `motor_index` unless you want a different L10 joint to move.

## Tuning

Most useful channel fields:

```yaml
glove_open: 115.88   # glove raw value when the motion should be open/start
glove_closed: 103.62 # glove raw value when the motion should be closed/end
hand_open: 255       # L10 command at glove_open
hand_closed: 0       # L10 command at glove_closed
invert: false        # true reverses the motion
gain: 1.0            # >1 moves more, <1 moves less
enabled: true        # false disables this channel
fixed_value: null    # fixed motor value when disabled
```

Common fixes:

```text
Starts from the wrong side       -> swap hand_open and hand_closed, or toggle invert
Moves opposite direction         -> toggle invert
Moves too little                 -> increase gain
Moves too far                    -> decrease gain
One joint should not move        -> enabled: false and fixed_value: desired value
Glove was worn differently       -> recapture glove_open/glove_closed
```

For smoother movement:

```yaml
send_interval_sec: 0.0
motion_profile: responsive_1to1
smoothing_mode: one_euro
one_euro_min_cutoff: 2.0
one_euro_beta: 0.08
one_euro_d_cutoff: 1.0
pose_deadband: 0
max_delta_per_cycle: 0
```

If motion is jittery while holding still, lower `one_euro_min_cutoff`. If quick movement feels laggy, raise `one_euro_beta`. If motion is too sudden, use `motion_profile: safe` and set `max_delta_per_cycle`, for example `8`.

## Calibration Tools

Quick glove-fit calibration updates only `glove_open` and `glove_closed` in the active YAML. Use this when teleoperation feels inaccurate because the glove was worn differently:

```bash
python3 control_l10_left_from_eg_glove.py --calibrate-ranges --calibrate-only
```

To make startup calibration happen every run, set this in `config/l10_left_eg_glove_mapping.auto.yaml`:

```yaml
startup_calibration:
  enabled: true
```

Auto-match glove sensors to L10 motors when the channel mapping itself is wrong:

```bash
python3 calibrate_l10_glove_mapping.py --glove-port /dev/ttyUSB0 --can can0 --no-dry-run
```

Update an existing auto YAML instead of writing a new one:

```bash
python3 calibrate_l10_glove_mapping.py --update-config config/l10_left_eg_glove_mapping.auto.yaml --glove-port /dev/ttyUSB0 --can can0 --no-dry-run
```

Recalibrate only selected motors:

```bash
python3 calibrate_l10_glove_mapping.py --update-config config/l10_left_eg_glove_mapping.auto.yaml --motors 2 6 --glove-port /dev/ttyUSB0 --can can0 --no-dry-run
```

Capture open/closed glove ranges without remapping sensors:

```bash
python3 capture_glove_ranges.py --config config/l10_left_eg_glove_mapping.auto.yaml --glove-port /dev/ttyUSB0
```

Capture only selected motors:

```bash
python3 capture_glove_ranges.py --config config/l10_left_eg_glove_mapping.auto.yaml --glove-port /dev/ttyUSB0 --motors 2 6
```

Apply default motion-control fields to an older YAML:

```bash
python3 update_motion_controls.py --config config/l10_left_eg_glove_mapping.auto.yaml
```

Disable thumb rotation if needed:

```bash
python3 update_motion_controls.py --config config/l10_left_eg_glove_mapping.auto.yaml --disable-thumb-rotation
```

## Older Direct Bridge

`glove_to_l10.py` is still available for raw serial inspection and simple direct mapping.

Read raw glove values:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --raw
```

Preview direct bridge:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left
```

Send direct bridge output to the L10:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

The YAML controller is preferred for the current EG-to-L10 setup because it is easier to tune individual L10 motors.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `/dev/ttyUSB0` does not exist | Run `ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null`; use the port that appears and edit `glove_reader.port` in the YAML. |
| `Permission denied: /dev/ttyUSB0` | Run `sudo usermod -aG dialout $USER`, then log out/in or run `newgrp dialout`. Use the actual glove port if it is different. |
| Raw glove values do not print | Check glove USB cable, port name, and `baud: 115200`. |
| `can0` does not appear | Check the USB-to-CAN adapter, then run `ip -br link show type can`. |
| `Operation not permitted` | Use `sudo` for `ip link` commands. |
| `Object "set" is unknown` | Use `sudo ip link set can0 down`, not `sudo ip set can0 down`. |
| `RTNETLINK answers: Device or resource busy` | Stop Python/ROS/CAN tools using the hand, then run `sudo ip link set can0 down`. |
| `can0 interface is not open` | Run the CAN down/configure/up commands again. |
| SDK does not detect the hand | Check hand power, CAN wiring, bitrate, and `python3 linkerhand_l10_sdk.py --can can0 --hand-type left state`. |
| Hand moves unexpectedly | Press `Ctrl+C`, preview with `--dry-run`, then check `glove_key`, `invert`, `gain`, and motor order. |
| Thumb rotation does not move | In the motor `9` channel, set `enabled: true` and `fixed_value: null`. |

## Git Workflow

After a good physical tuning session:

```bash
git status
git add config/l10_left_eg_glove_mapping.auto.yaml README.md
git commit -m "Tune L10 EG glove mapping"
git push origin main
```

On another computer:

```bash
git pull origin main
```
