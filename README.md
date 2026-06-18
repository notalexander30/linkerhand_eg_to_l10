# LinkerHand EG To L10

Terminal and GUI control for using a right EG/KTH5702 USB glove to control a left LinkerHand L10 on a Linux laptop.

```text
Right EG glove -> USB serial -> laptop -> SocketCAN can0 -> left LinkerHand L10
```

This project uses the LinkerHand Python SDK path for the hand:

- `LinkerHandApi(hand_type="left", hand_joint="L10", can="can0")`
- `api.get_embedded_version()`
- `api.get_state()`
- `api.finger_move(pose=...)`

The glove is read from USB serial, usually `/dev/ttyUSB0`.

## Safety First

- Mount or hold the L10 securely before sending movement.
- Keep fingers, tools, and cables away from the hand while testing.
- Run only one controller at a time. Close ROS nodes, GUI dashboards, old terminal scripts, and other LinkerHand tools before using this bridge.
- Test the glove with `--raw` first.
- Preview without `--send` before live control.
- If motion is unsafe, press `Ctrl+C`, press `Stop` in the GUI, or use the hardware power switch/emergency stop.
- Do not use `--force` unless you understand and accept the risk.

## What You Need

- Ubuntu 20.04 or newer is recommended.
- Python 3.8 or newer.
- Git.
- A right EG/KTH5702 glove connected by USB-C/USB.
- A USB-to-CAN adapter supported by SocketCAN.
- A powered LinkerHand L10.
- Linux CAN tools: `iproute2`, `can-utils`, and optionally `ethtool`.
- Optional but recommended: Conda or another Python virtual environment.

## First Setup On A Linux Laptop

### 1. Clone the project

```bash
cd ~
git clone https://github.com/notalexander30/linkerhand_eg_to_l10.git
cd linkerhand_eg_to_l10
```

If you cloned somewhere else, always `cd` into this project directory before running the commands below.

### 2. Create and activate a Python environment

Using Conda:

```bash
conda create -n linkerhand-l10 python=3.10 -y
conda activate linkerhand-l10
python3 -m pip install --upgrade pip
```

If you already have the environment:

```bash
conda activate linkerhand-l10
```

Without Conda:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
```

### 3. Install dependencies

```bash
python3 -m pip install -r requirements.txt
sudo apt update
sudo apt install -y iproute2 can-utils ethtool
```

If you get `No module named can`, run:

```bash
python3 -m pip install python-can python-can-candle
```

If you get `No module named serial`, run:

```bash
python3 -m pip install pyserial
```

### 4. Connect the hardware

1. Connect the right EG/KTH5702 glove to the laptop by USB.
2. Connect the USB-to-CAN adapter to the laptop.
3. Connect CAN-H, CAN-L, and ground according to the adapter and L10 wiring.
4. Power on the LinkerHand L10.
5. Make sure no other controller is running.

### 5. Find the glove serial port

```bash
python3 -m serial.tools.list_ports
ls /dev/ttyUSB*
ls /dev/ttyACM*
```

In the current setup, the glove is usually:

```text
/dev/ttyUSB0
```

Confirm raw glove data:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --raw
```

Move the glove. You should see changing KTH5702 sensor angles. Press `Ctrl+C` to stop.

### 6. Find the CAN interface

```bash
ip link
ip -br link show type can
```

You should see `can0` or `can1`.

Optional helper:

```bash
chmod +x find_can.sh
./find_can.sh
```

If you do not see a CAN interface, check the USB-to-CAN adapter, cable, driver, and power.

### 7. Reset CAN: down, configure, up

Most L10 setups use 1 Mbps.

For `can0`:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 restart-ms 100
sudo ip link set can0 txqueuelen 1000
sudo ip link set can0 up
ip -details link show can0
```

For `can1`, replace `can0` with `can1`.

Watch CAN traffic if needed:

```bash
candump can0
```

Press `Ctrl+C` to stop `candump`.

### 8. Test the left L10 alone

```bash
python3 linkerhand_l10_sdk.py --can can0 --hand-type left boot
python3 linkerhand_l10_sdk.py --can can0 --hand-type left state
```

Good signs:

- SDK version prints.
- The hand is detected by version, serial, or state.
- A 10-value state prints from 0 to 255.

If this fails, fix CAN/L10 first before running glove control.

## Daily Start

```bash
cd ~/linkerhand_eg_to_l10
conda activate linkerhand-l10
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --raw
python3 linkerhand_l10_sdk.py --can can0 --hand-type left state
```

Preview the bridge without moving the hand:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left
```

Send to the left L10:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

## Terminal Control

Root command:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

Separate terminal launcher:

```bash
python3 terminal_control/glove_to_l10_terminal.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

Useful terminal commands:

| Task | Command |
| --- | --- |
| Show help | `python3 glove_to_l10.py --help` |
| Read raw glove values | `python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --raw` |
| Preview bridge, no movement | `python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left` |
| Live bridge | `python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send` |
| Use `can1` | `python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can1 --hand left --send` |
| Change max angle | `python3 glove_to_l10.py --angle-max 360 --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send` |
| Calibrated mode preview | `python3 glove_to_l10.py --mapping calibrated --glove-port /dev/ttyUSB0 --hand-can can0 --hand left` |

## YAML Mapping Controller

`control_l10_left_from_eg_glove.py` is a config-first teleoperation entry point for a right EG glove controlling a left L10. It uses the local LinkerHand SDK as:

```python
LinkerHandApi(hand_type="left", hand_joint="L10", can="can0")
api.finger_move(pose=pose)
```

The SDK `finger_move()` method sends a 10-value L10 pose through the lower-level `set_joint_positions()` implementation.

Dry-run with generated glove values:

```bash
python3 control_l10_left_from_eg_glove.py --config config/l10_left_eg_glove_mapping.yaml --mock-glove --dry-run --print-glove --print-pose
```

Live control with the real hand:

```bash
python3 control_l10_left_from_eg_glove.py --config config/l10_left_eg_glove_mapping.yaml --no-dry-run --print-pose
```

The default config keeps `dry_run: true`; use `--no-dry-run` only after the printed pose looks safe. Press `Ctrl+C` to stop; in live mode the script sends the configured open-hand `safe_exit_pose` before exiting.

Tune calibration in `config/l10_left_eg_glove_mapping.yaml`. For each channel, set `glove_open` to the raw glove value with that finger open and `glove_closed` to the value with that finger bent. Set `hand_open` and `hand_closed` to the matching L10 motor limits. The current defaults use the repo's L10 `Open Hand` and `Fist` examples, where the main flexion motors confirm `255=open` and `0=closed`.

To connect a different real Linker EG glove source later, extend the `GloveReader` class in `control_l10_left_from_eg_glove.py`. It currently supports mock values and the existing serial/KTH5702 parser from `glove_to_l10.py`; UDP, ROS topic, or vendor SDK readers can be added as new modes that yield dictionaries keyed like `thumb_0`, `index_0`, `middle_0`, `ring_0`, and `pinky_0`.

The Linker EG manual describes 15 captured values: three channels per finger. On the tested right EG glove, the raw serial order used by this bridge is thumb, index, middle, ring, pinky. The L10 has 10 active DOF, so the default bridge mirrors the right glove onto the left L10: thumb still drives thumb, the four non-thumb fingers reverse across the palm, `_1` channels drive finger pitch, `_0` channels drive side swing, and extra EG channels that the L10 cannot reproduce are ignored.

### Auto-Match The 15 Glove Sensors To 10 L10 Motors

If the glove sensor order does not match the L10 motor order, run the interactive matcher:

```bash
python3 calibrate_l10_glove_mapping.py --glove-port /dev/ttyUSB0 --can can0 --no-dry-run
```

The matcher first sends an open L10 pose of ten `255` values, records the glove-open baseline, then prompts you through the 10 L10 motors. For each prompt, move only the requested right-glove finger or DOF and hold it still. The script selects the glove sensor with the strongest change from the 15 available sensors and writes:

```text
config/l10_left_eg_glove_mapping.auto.yaml
```

Preview the generated mapping without moving the hand:

```bash
python3 control_l10_left_from_eg_glove.py --config config/l10_left_eg_glove_mapping.auto.yaml --dry-run --print-glove --print-pose
```

If the printed 10-value pose follows the glove correctly, run live:

```bash
python3 control_l10_left_from_eg_glove.py --config config/l10_left_eg_glove_mapping.auto.yaml --no-dry-run --print-pose
```

Each channel has a `gain` value, which is the master-to-slave movement multiplier. Use `gain: 1.0` for normal open-to-closed mapping, increase it if the L10 does not close enough, and decrease it if it moves too far.

If one glove sensor should drive more than one L10 motor, add `--allow-duplicate-sensors` during calibration.

### Smoother Motion

The YAML controller supports `smoothing_mode: one_euro`, based on the [1 Euro Filter](https://gery.casiez.net/1euro/) for reducing jitter while keeping fast human motion responsive.

Recommended starting values for the L10 glove bridge:

```yaml
control_hz: 60
hand_output_mode: normalized_255
normalized_hand_open: 255
normalized_hand_closed: 0
send_interval_sec: 0.0
motion_profile: responsive_1to1
smoothing_mode: one_euro
one_euro_min_cutoff: 2.0
one_euro_beta: 0.08
one_euro_d_cutoff: 1.0
pose_deadband: 0
max_delta_per_cycle: 0
```

`hand_output_mode: normalized_255` keeps the glove calibration open/close points, but makes every mapped L10 motor use a simple full-range set-state output: open maps to `255`, closed maps to `0`. This is the neatest mode when you want all joints to behave the same way.

`send_interval_sec: 0.0` sends the current 10-value pose every control loop for live teleoperation. Use `send_interval_sec: 1.0` only if you want slow set-state snapshots.

`motion_profile: responsive_1to1` makes the slave follow the mapped glove pose directly: no pose deadband and no per-cycle speed cap. Old auto-calibration files that do not have `motion_profile` use this responsive 1:1 behavior by default.

Tuning rule of thumb:

```text
Too jittery while holding still  -> lower one_euro_min_cutoff, for example 1.2
Too laggy during fast motion     -> raise one_euro_beta, for example 0.12
Too fast or sudden               -> set motion_profile: safe and max_delta_per_cycle: 8
Too slow to close                -> keep max_delta_per_cycle: 0
```

Avoid `--print-glove` and `--print-pose` during normal live control because terminal output can make motion feel less smooth.

If your generated `config/l10_left_eg_glove_mapping.auto.yaml` does not show these controls or the L10 reference joint names yet, add them without recalibrating:

```bash
python3 update_motion_controls.py --config config/l10_left_eg_glove_mapping.auto.yaml
```

That command also repairs the EG-to-L10 glove keys in the local auto YAML:

```text
motor 0 Thumb CMC Pitch                  -> thumb_2
motor 1 Thumb Adduction/Abduction        -> thumb_1
motor 2 Index Finger MCP Pitch           -> pinky_1
motor 3 Middle Finger MCP Pitch          -> ring_1
motor 4 Ring Finger MCP Pitch            -> middle_1
motor 5 Pinky Finger MCP Pitch           -> index_1
motor 6 Index Finger Adduction/Abduction -> pinky_0
motor 7 Ring Finger Adduction/Abduction  -> middle_0
motor 8 Pinky Finger Adduction/Abduction -> index_0
motor 9 Thumb Rotation                   -> thumb_0
```

Recalibrate only the left-index output channels in your existing auto YAML:

```bash
python3 calibrate_l10_glove_mapping.py --update-config config/l10_left_eg_glove_mapping.auto.yaml --motors 2 6 --glove-port /dev/ttyUSB0 --can can0 --no-dry-run
```

Motor `2` is the L10 Index Finger MCP Pitch. Motor `6` is the L10 Index Finger Adduction/Abduction. With the mirrored right-glove-to-left-L10 map, those are driven by `pinky_1` and `pinky_0`; if only left-index bend is wrong, use `--motors 2`.

Re-capture only the open/closed glove ranges without remapping sensors:

```bash
python3 capture_glove_ranges.py --config config/l10_left_eg_glove_mapping.auto.yaml --glove-port /dev/ttyUSB0
```

For only the index finger ranges:

```bash
python3 capture_glove_ranges.py --config config/l10_left_eg_glove_mapping.auto.yaml --glove-port /dev/ttyUSB0 --motors 2 6
```

Thumb rotation is enabled by default from `thumb_0`. If it causes trouble, hold motor `9` fixed:

```bash
python3 update_motion_controls.py --config config/l10_left_eg_glove_mapping.auto.yaml --disable-thumb-rotation
```

## GUI Control

Start the GUI:

```bash
python3 gui_control/glove_to_l10_gui.py
```

Use these default values for the current setup:

```text
Glove port: /dev/ttyUSB0
Hand CAN: can0
Hand side: left
Mapping: angle
Angle max: 360
```

Recommended GUI flow:

1. Start without `Send to hand`.
2. Confirm the terminal output changes when the glove moves.
3. Enable `Send to hand`.
4. Press `Start`.
5. Press `Stop` before changing settings.

## Current Mapping

Default mapping is raw angle mapping:

```text
0 degrees   -> L10 position 0
180 degrees -> L10 position 128
360 degrees -> L10 position 255
```

Raw EG glove sensor names used by the YAML:

```text
raw 0  = thumb_0
raw 1  = thumb_1
raw 2  = thumb_2
raw 3  = index_0
raw 4  = index_1
raw 5  = index_2
raw 6  = middle_0
raw 7  = middle_1
raw 8  = middle_2
raw 9  = ring_0
raw 10 = ring_1
raw 11 = ring_2
raw 12 = pinky_0
raw 13 = pinky_1
raw 14 = pinky_2
```

Right glove sensors mapped to left L10 joints:

```text
glove 0  -> L10 joint 9 Thumb Rotation
glove 1  -> L10 joint 1 Thumb Adduction/Abduction
glove 2  -> L10 joint 0 Thumb CMC Pitch
glove 3  -> L10 joint 8 Pinky Finger Adduction/Abduction
glove 4  -> L10 joint 5 Pinky Finger MCP Pitch
glove 6  -> L10 joint 7 Ring Finger Adduction/Abduction
glove 7  -> L10 joint 4 Ring Finger MCP Pitch
glove 10 -> L10 joint 3 Middle Finger MCP Pitch
glove 12 -> L10 joint 6 Index Finger Adduction/Abduction
glove 13 -> L10 joint 2 Index Finger MCP Pitch
```

Ignored glove sensors:

```text
5, 8, 9, 11, 14
```

L10 joint order:

1. Thumb CMC Pitch
2. Thumb Adduction/Abduction
3. Index Finger MCP Pitch
4. Middle Finger MCP Pitch
5. Ring Finger MCP Pitch
6. Pinky Finger MCP Pitch
7. Index Finger Adduction/Abduction
8. Ring Finger Adduction/Abduction
9. Pinky Finger Adduction/Abduction
10. Thumb Rotation

## Optional Calibrated Mode

The default angle mode does not require calibration.

If you want open/fist calibration instead:

```bash
python3 glove_to_l10.py --mapping calibrated --glove-port /dev/ttyUSB0 --calibrate-open
python3 glove_to_l10.py --mapping calibrated --glove-port /dev/ttyUSB0 --calibrate-fist
python3 glove_to_l10.py --mapping calibrated --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

This creates or updates:

```text
glove_l10_calibration.json
```

The file is ignored by Git because it is specific to your glove and hand.

## Troubleshooting

| Problem or return message | What to do first |
| --- | --- |
| `git clone` fails on Windows with `Filename too long` | Use a Linux laptop, or clone into a short path such as `C:\src`. On Windows you can also run `git config --global core.longpaths true`, then clone again. |
| `python3: command not found` | Install Python 3, or use the Python inside your Conda environment. |
| `No module named can` | Run `python3 -m pip install python-can python-can-candle`. |
| `No module named serial` | Run `python3 -m pip install pyserial`. |
| `No module named PyQt5` | Run `python3 -m pip install PyQt5`, or use terminal mode instead of GUI mode. |
| `/dev/ttyUSB0` does not exist | Replug the glove and run `python3 -m serial.tools.list_ports`. It may be `/dev/ttyUSB1` or `/dev/ttyACM0`. |
| `Permission denied: /dev/ttyUSB0` | Run `sudo usermod -aG dialout $USER`, then log out/in or run `newgrp dialout`. |
| Raw glove mode prints nothing | Check glove power, USB cable, port name, and baud rate. Try `--baud 115200`, `--baud 57600`, or `--baud 230400`. |
| `can0` does not appear in `ip link` | Check USB-to-CAN connection, driver, USB port, and cable. Replug the adapter. Run `ip -br link show type can`. |
| `Cannot find device "can0"` | Use the interface that exists, for example `--hand-can can1`, or fix the adapter/driver until `can0` appears. |
| `candump: command not found` | Run `sudo apt update && sudo apt install -y can-utils`. |
| `ip: command not found` | Run `sudo apt update && sudo apt install -y iproute2`. |
| `Operation not permitted` | Use `sudo` for `ip link` commands. |
| `RTNETLINK answers: Device or resource busy` | Stop other controllers, then run `sudo ip link set can0 down` and bring it back up. |
| `can0 interface is not open` | Run the CAN down/configure/up commands, then retry. |
| `SDK did not detect the hand` | Check CAN setup, hand power, `--hand left`, and `--hand-can can0`. Test with `python3 linkerhand_l10_sdk.py --can can0 --hand-type left state`. |
| Hand moves unexpectedly | Stop with `Ctrl+C` or GUI `Stop`. Preview without `--send`. Confirm the sensor mapping and `--angle-max`. |
| Wrong side responds | Use `--hand left` for the left L10. The glove being right-hand does not change the LinkerHand side. |
| Another script controls the hand | Close ROS nodes, dashboards, old terminal tools, and any other LinkerHand process. |

## When You Are Done

Stop terminal mode with:

```bash
Ctrl+C
```

Stop GUI mode with the `Stop` button.

Optionally bring CAN down:

```bash
sudo ip link set can0 down
```

Power off the hand when it is safe.
