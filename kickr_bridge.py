"""
KICKR Core 2 bridge: reads live FTMS data, logs it to CSV, and forwards it as JSON over UDP
(localhost:5005) so Unity or anything else can use it. You can also type a wattage to set ERG power.

It also listens for commands on UDP 127.0.0.1:5007, so a game can change the trainer's resistance
while the bridge holds the (only) Bluetooth connection:
    {"cmd": "resistance", "level": 45}      -> FTMS Set Target Resistance Level (0x04), 0-100

Setup:  pip install bleak
Run:    python kickr_bridge.py
Close Zwift and other apps first so the trainer has a free Bluetooth slot.
"""
import asyncio, csv, json, math, socket, struct, time, sys
from bleak import BleakScanner, BleakClient

FTMS_SERVICE   = "00001826-0000-1000-8000-00805f9b34fb"
INDOOR_BIKE    = "00002ad2-0000-1000-8000-00805f9b34fb"   # live data (notify)
CONTROL_POINT  = "00002ad9-0000-1000-8000-00805f9b34fb"   # write + indicate
UDP_TARGET     = ("127.0.0.1", 5005)
COMMAND_ADDR   = ("127.0.0.1", 5007)                      # game -> bridge commands

OP_REQUEST_CONTROL = 0x00
OP_SET_RESISTANCE  = 0x04
OP_SET_POWER       = 0x05
OPCODE_NAMES = {0x00: "request control", 0x01: "reset", 0x04: "resistance", 0x05: "target power",
                0x07: "start/resume", 0x08: "stop/pause", 0x11: "simulation"}
RESULT_NAMES = {0x01: "success", 0x02: "not supported", 0x03: "invalid parameter",
                0x04: "failed", 0x05: "control not permitted"}

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

def parse_command(data: bytes):
    """Parse one UDP command datagram. Returns ("resistance", level) with level clamped to 0-100.
    Raises ValueError for anything else."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"bad JSON ({e})") from None
    if not isinstance(msg, dict):
        raise ValueError("expected a JSON object")
    cmd = msg.get("cmd")
    if cmd != "resistance":
        raise ValueError(f"unknown cmd {cmd!r}")
    level = msg.get("level")
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level):
        raise ValueError(f"level must be a number, got {level!r}")
    return "resistance", max(0, min(100, int(round(level))))

def resistance_payload(level: int) -> bytes:
    """FTMS Set Target Resistance Level: opcode 0x04 + uint8 level (0-100, step 1 on the KICKR)."""
    return bytes([OP_SET_RESISTANCE, max(0, min(100, int(level)))])

def describe_reply(data: bytes) -> str:
    """Human-readable FTMS control point indication, e.g. 80 04 01 -> 'resistance: success'."""
    if len(data) >= 3 and data[0] == 0x80:
        return f"{OPCODE_NAMES.get(data[1], hex(data[1]))}: {RESULT_NAMES.get(data[2], hex(data[2]))}"
    return "unexpected reply"

def on_control_reply(_, d):
    d = bytes(d)
    print(f"control reply: {d.hex()} ({describe_reply(d)})", flush=True)

class TrainerControl:
    """Serialises control point writes (stdin watts + UDP commands share one BLE link) and
    coalesces resistance commands: if several arrive during one write, only the newest is sent."""
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()
        self._pending = None
        self._wake = asyncio.Event()

    async def write(self, payload: bytes):
        async with self.lock:
            await self.client.write_gatt_char(CONTROL_POINT, payload, response=True)

    def request_resistance(self, level: int):
        self._pending = level
        self._wake.set()

    async def resistance_worker(self):
        while True:
            await self._wake.wait()
            self._wake.clear()
            level, self._pending = self._pending, None
            if level is None:
                continue
            try:
                await self.write(resistance_payload(level))
                print(f"Resistance level set to {level} (wrote {resistance_payload(level).hex()})", flush=True)
            except Exception as e:
                print(f"Resistance write failed: {e!r}", flush=True)

class CommandProtocol(asyncio.DatagramProtocol):
    def __init__(self, control: TrainerControl):
        self.control = control

    def datagram_received(self, data, addr):
        try:
            _, level = parse_command(data)
        except ValueError as e:
            print(f"UDP command from {addr[0]}:{addr[1]} ignored: {e}", flush=True)
            return
        print(f"UDP command: resistance {level}", flush=True)
        self.control.request_resistance(level)

async def connect(dev, on_data, attempts=5):
    """Connect, subscribe and request control. Windows sometimes reports services before they're
    all discovered (CharacteristicNotFound), so retry with a fresh client."""
    for attempt in range(1, attempts + 1):
        client = BleakClient(dev)
        try:
            await client.connect()
            if not client.services.get_characteristic(INDOOR_BIKE):
                raise RuntimeError("FTMS data characteristic not found yet")
            await client.start_notify(INDOOR_BIKE, on_data)
            await client.start_notify(CONTROL_POINT, on_control_reply)
            await client.write_gatt_char(CONTROL_POINT, bytes([OP_REQUEST_CONTROL]), response=True)
            return client
        except Exception as e:
            print(f"Connect attempt {attempt}/{attempts} failed ({e!r}), retrying...", flush=True)
            try: await client.disconnect()
            except Exception: pass
            await asyncio.sleep(2)
    return None

async def main():
    print("Scanning for a trainer with FTMS...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: FTMS_SERVICE in [u.lower() for u in ad.service_uuids], timeout=15)
    if not dev:
        print("No FTMS trainer found. Is it awake (pedal a bit) and disconnected from other apps?"); return
    print(f"Found {dev.name} ({dev.address}), connecting...")
    log = open(f"kickr_log_{int(time.time())}.csv", "w", newline="")
    writer = None

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

    client = await connect(dev, on_data)
    if client is None:
        print("Couldn't connect to the FTMS service. Try again in a moment."); log.close(); return

    control = TrainerControl(client)
    loop = asyncio.get_running_loop()
    worker = asyncio.create_task(control.resistance_worker())
    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(lambda: CommandProtocol(control), local_addr=COMMAND_ADDR)
        print(f"Listening for commands on UDP {COMMAND_ADDR[0]}:{COMMAND_ADDR[1]} "
              '(e.g. {"cmd": "resistance", "level": 40})', flush=True)
    except OSError as e:
        print(f"Could not open command port {COMMAND_ADDR[1]} ({e}); UDP commands disabled.", flush=True)

    try:
        print("Streaming. Type a wattage + Enter to set ERG power (e.g. 150), or q to quit.", flush=True)
        while True:
            raw = await loop.run_in_executor(None, sys.stdin.readline)
            if raw == "":                      # no keyboard (e.g. started by another program): just stream
                await asyncio.Event().wait()
            line = raw.strip()
            if line == "q": break
            if line.isdigit():
                await control.write(bytes([OP_SET_POWER]) + struct.pack("<h", int(line)))
                print(f"Target power set to {line} W")
    finally:
        worker.cancel()
        if transport is not None: transport.close()
        await client.disconnect()
        log.close()

if __name__ == "__main__":
    asyncio.run(main())
