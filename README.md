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

## Data sent to the game (example)
```
{"t": 1729790000.12, "speed_kmh": 28.4, "cadence_rpm": 85.0, "power_w": 162}
```
