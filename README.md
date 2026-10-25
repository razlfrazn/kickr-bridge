# kickr-bridge

A small open-source Python program that connects to a Wahoo KICKR Core 2 (or any Bluetooth FTMS smart trainer), reads live speed, cadence and power, and can set resistance.

It also:
- saves every reading to a CSV file (`kickr_log_<time>.csv`)
- sends each reading as JSON over UDP to `127.0.0.1:5005`, so a game (Unity, Godot, anything) can use the data

## What you need
- A Windows, Mac or Linux PC with Bluetooth
- Python 3.10 or newer
- The trainer powered on, and **not** connected to Zwift or other apps

## How to run it
```
pip install -r requirements.txt
python kickr_bridge.py
```
Pedal a little to wake the trainer. Live data prints on screen.
Type a number (for example `150`) and press Enter to hold that many watts (ERG mode). Type `q` to quit.

## Commands from the game (UDP 127.0.0.1:5007)
On Windows only one program can talk to the trainer's FTMS service at a time, so a game can't
connect to the trainer itself while the bridge is running. Instead, it sends small JSON commands
to the bridge on UDP `127.0.0.1:5007`:
```
{"cmd": "resistance", "level": 45}
```
- `level` is the FTMS resistance level, **0 to 100** (anything outside is clamped; decimals are rounded).
- The bridge writes FTMS *Set Target Resistance Level* (`04 <level>`) to the control point and logs
  the trainer's reply, e.g. `control reply: 800401 (resistance: success)`.
- If several commands arrive while a write is still in flight, only the newest one is sent.
  The sender should still rate-limit (the Unity game sends at most 2 per second, only on change).
- Bad or unknown commands are logged and ignored. Typing watts on the keyboard still works.

Try it by hand while the bridge runs:
```
python send_command.py resistance 40
```

## Tests
```
python -m unittest -v
```
Checks command parsing/clamping, the control point payload, reply decoding and command coalescing (no trainer needed).

## Data sent to the game (example)
```
{"t": 1729790000.12, "speed_kmh": 28.4, "cadence_rpm": 85.0, "power_w": 162}
```
