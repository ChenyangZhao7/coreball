import json
import socket
import unittest

from station import commands as C
from station.link import Link


class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


class LinkTest(unittest.TestCase):
    def test_intent_shapes(self):
        c = C.Command("manual", "goto", {"point": [1, 2, 1300]}, created_at=0)
        i = C.to_intent(c)
        self.assertEqual(i["intent"], "goto")
        self.assertEqual(i["src"], "station/manual")
        self.assertEqual(i["point"], [1, 2, 1300])

    def test_send(self):
        sock = FakeSock()
        link = Link(sock=sock)
        link.send({"intent": "stop"})
        raw, addr = sock.sent[0]
        self.assertEqual(json.loads(raw), {"intent": "stop"})
        self.assertEqual(addr, ("127.0.0.1", 4590))

    def test_telemetry_age(self):
        link = Link(now=lambda: 100.0)
        raw = json.dumps({"ball": [0, 0, 1300], "hub": [0, 0, 1460]}).encode()
        link.put_telemetry(raw, now=99.0)
        snap = link.latest()
        self.assertEqual(snap["ball"], [0, 0, 1300])
        self.assertEqual(snap["age_ms"], 1000)
        self.assertTrue(snap["stale"])
        self.assertFalse(link.connected(max_age=0.5))

    def test_bind_conflict(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        try:
            with self.assertRaises(OSError):
                Link(telemetry_addr=("127.0.0.1", port)).start()
        finally:
            holder.close()
