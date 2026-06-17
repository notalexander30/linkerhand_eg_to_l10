# LinkerHand EG To L10

Separate control repo for a right EG/KTH5702 USB glove controlling a left LinkerHand L10.

```text
Right EG glove -> USB serial -> laptop -> SocketCAN can0 -> left LinkerHand L10
```

## Setup

```bash
cd ~
git clone https://github.com/notalexander30/linkerhand_eg_to_l10.git
cd linkerhand_eg_to_l10
conda activate linkerhand-l10
python3 -m pip install -r requirements.txt
sudo apt update
sudo apt install -y can-utils iproute2
```

Bring CAN up:

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 restart-ms 100
sudo ip link set can0 txqueuelen 1000
sudo ip link set can0 up
```

Check the glove:

```bash
python3 -m serial.tools.list_ports
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --raw
```

## Terminal Control

Preview without moving the hand:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left
```

Send to the left L10:

```bash
python3 glove_to_l10.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

The same terminal program is also available here:

```bash
python3 terminal_control/glove_to_l10_terminal.py --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

## GUI Control

```bash
python3 gui_control/glove_to_l10_gui.py
```

Use the default values for your current setup:

```text
Glove port: /dev/ttyUSB0
Hand CAN: can0
Hand side: left
Mapping: angle
Angle max: 360
```

Enable `Send to hand` only after preview/raw data looks correct.

## Current Mapping

Default mapping is raw angle mapping:

```text
0 degrees   -> L10 position 0
180 degrees -> L10 position 128
360 degrees -> L10 position 255
```

Right glove sensors mapped to left L10 joints:

```text
glove 0  -> L10 joint 0 Thumb Base
glove 1  -> L10 joint 1 Thumb Side Swing
glove 2  -> L10 joint 9 Thumb Rotation
glove 3  -> L10 joint 2 Index Base
glove 4  -> L10 joint 6 Index Side Swing
glove 6  -> L10 joint 3 Middle Base
glove 9  -> L10 joint 4 Ring Base
glove 10 -> L10 joint 7 Ring Side Swing
glove 12 -> L10 joint 5 Little Base
glove 13 -> L10 joint 8 Little Side Swing
```

Ignored glove sensors:

```text
5, 7, 8, 11, 14
```

## Optional Calibrated Mode

The old open/fist calibration mode is still available:

```bash
python3 glove_to_l10.py --mapping calibrated --calibrate-open
python3 glove_to_l10.py --mapping calibrated --calibrate-fist
python3 glove_to_l10.py --mapping calibrated --glove-port /dev/ttyUSB0 --hand-can can0 --hand left --send
```

## Stop

Press `Ctrl+C` in terminal mode. In GUI mode, press `Stop`.
