"""
KICKR Core 2 bridge: reads live FTMS data, logs it to CSV, and forwards it as JSON over UDP
(localhost:5005) so Unity or anything else can use it. You can also type a wattage to set ERG power.

Setup:  pip install bleak
Run:    python kickr_bridge.py
Close Zwift and other apps first so the trainer has a free Bluetooth slot.
"""
import asyncio, csv, json, socket, struct, time, sys
from bleak import BleakScanner, BleakClient

FTMS_SERVICE   = "00001826-0000-1000-8000-00805f9b34fb"
INDOOR_BIKE    = "00002ad2-0000-1000-8000-00805f9b34fb"   # live data (notify)
CONTROL_POINT  = "00002ad9-0000-1000-8000-00805f9b34fb"   # write + indicate
UDP_TARGET     = ("127.0.0.1", 5005)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def parse_indoor_bike(data: bytes) -> dict:
    flags = struct.unpack_from("<H", data, 0)[0]; i = 2; out = {}
    def take(fmt):
        nonlocal i
        v = struct.unpack_from(fmt, data, i)[0]; i += struct.calcsize(fmt); return v
    if not flags & 0x0001: out["speed_kmh"] = take("<H") / 100
    if flags & 0x0002: out["avg_speed_kmh"] = take("<H") / 100
    if flags & 0x0004: out["cadence_rpm"] = take("<H") / 2
    if flags & 0x0008: out["avg_cadence_rpm"] = take("<H") / 2
    if flags & 0x0010:
        b = data[i:i+3]; i += 3; out["distance_m"] = int.from_bytes(b, "little")
    if flags & 0x0020: out["resistance_level"] = take("<h")
    if flags & 0x0040: out["power_w"] = take("<h")
    if flags & 0x0080: out["avg_power_w"] = take("<h")
    if flags & 0x0100: out["energy_kcal"] = take("<H"); take("<H"); take("<B")
    if flags & 0x0200: out["heart_rate"] = take("<B")
    if flags & 0x0400: take("<B")
    if flags & 0x0800: out["elapsed_s"] = take("<H")
    return out

async def main():
    print("Scanning for a trainer with FTMS...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: FTMS_SERVICE in [u.lower() for u in ad.service_uuids], timeout=15)
    if not dev:
        print("No FTMS trainer found. Is it awake (pedal a bit) and disconnected from other apps?"); return
    print(f"Found {dev.name} ({dev.address}), connecting...")
    log = open(f"kickr_log_{int(time.time())}.csv", "w", newline="")
    writer = None

    async with BleakClient(dev) as client:
        def on_data(_, data):
            nonlocal writer
            row = {"t": round(time.time(), 3), **parse_indoor_bike(bytes(data))}
            print(row)
            sock.sendto(json.dumps(row).encode(), UDP_TARGET)
            if writer is None:
                writer = csv.DictWriter(log, fieldnames=["t","speed_kmh","cadence_rpm","power_w",
                    "distance_m","resistance_level","heart_rate","elapsed_s","avg_speed_kmh",
                    "avg_cadence_rpm","avg_power_w","energy_kcal"], extrasaction="ignore")
                writer.writeheader()
            writer.writerow(row); log.flush()

        await client.start_notify(INDOOR_BIKE, on_data)
        await client.start_notify(CONTROL_POINT, lambda _, d: print("control reply:", bytes(d).hex()))
        await client.write_gatt_char(CONTROL_POINT, b"\x00", response=True)   # request control
        print("Streaming. Type a wattage + Enter to set ERG power (e.g. 150), or q to quit.")

        loop = asyncio.get_running_loop()
        while True:
            line = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
            if line == "q": break
            if line.isdigit():
                await client.write_gatt_char(CONTROL_POINT, b"\x05" + struct.pack("<h", int(line)), response=True)
                print(f"Target power set to {line} W")
    log.close()

asyncio.run(main())
