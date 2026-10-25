"""Unit tests for the bridge's command parsing (no trainer needed).  Run: python -m unittest -v"""
import struct, unittest
import kickr_bridge as kb

class ParseCommandTests(unittest.TestCase):
    def test_resistance(self):
        self.assertEqual(kb.parse_command(b'{"cmd":"resistance","level":48}'), ("resistance", 48))

    def test_clamps(self):
        self.assertEqual(kb.parse_command(b'{"cmd":"resistance","level":150}')[1], 100)
        self.assertEqual(kb.parse_command(b'{"cmd":"resistance","level":-5}')[1], 0)

    def test_rounds_floats(self):
        self.assertEqual(kb.parse_command(b'{"cmd": "resistance", "level": 30.6}')[1], 31)

    def test_rejects_bad_input(self):
        for bad in [b"not json", b"[1,2]", b'{"cmd":"power","level":5}', b'{"level":5}',
                    b'{"cmd":"resistance"}', b'{"cmd":"resistance","level":"40"}',
                    b'{"cmd":"resistance","level":true}', b'{"cmd":"resistance","level":NaN}',
                    b"\xff\xfe"]:
            with self.assertRaises(ValueError, msg=bad):
                kb.parse_command(bad)

class PayloadTests(unittest.TestCase):
    def test_resistance_payload(self):
        self.assertEqual(kb.resistance_payload(48), bytes([0x04, 48]))
        self.assertEqual(kb.resistance_payload(130), bytes([0x04, 100]))

    def test_describe_reply(self):
        self.assertEqual(kb.describe_reply(bytes.fromhex("800401")), "resistance: success")
        self.assertEqual(kb.describe_reply(bytes.fromhex("800001")), "request control: success")
        self.assertEqual(kb.describe_reply(bytes.fromhex("800405")), "resistance: control not permitted")

class IndoorBikeTests(unittest.TestCase):
    def test_speed_cadence_power(self):
        data = struct.pack("<HHHh", 0x0044, 2840, 170, 162)   # speed, cadence, power present
        self.assertEqual(kb.parse_indoor_bike(data), {"speed_kmh": 28.4, "cadence_rpm": 85.0, "power_w": 162})

class CoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_newest_pending_level_is_written(self):
        class FakeClient:
            def __init__(self): self.writes = []
            async def write_gatt_char(self, uuid, payload, response):
                self.writes.append(bytes(payload))
        client = FakeClient()
        control = kb.TrainerControl(client)
        for level in (10, 20, 35):
            kb.CommandProtocol(control).datagram_received(
                ('{"cmd":"resistance","level":%d}' % level).encode(), ("127.0.0.1", 1))
        import asyncio
        task = asyncio.create_task(control.resistance_worker())
        await asyncio.sleep(0.05)
        task.cancel()
        self.assertEqual(client.writes, [bytes([0x04, 35])])

if __name__ == "__main__":
    unittest.main()
