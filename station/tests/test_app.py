import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from station.app import App, create_server
from station.history import History
from station.predictor import Predictor


class FakeLink:
    def __init__(self):
        self.sent = []
        self.snap = None

    def send(self, intent):
        self.sent.append(intent)

    def latest(self):
        return self.snap


def req(url, data=None):
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body,
                               method="GET" if data is None else "POST",
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=3) as x:
            raw = x.read()
            return x.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.link = FakeLink()
        self.app = App(link=self.link,
                       history=History(Path(self.tmp.name) / "h.jsonl"))
        self.httpd = create_server("127.0.0.1", 0, self.app)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_state_and_manual_goto(self):
        self.assertEqual(req(self.base + "/api/state")[1]["mode"], "manual")
        st, body = req(self.base + "/api/command",
                       {"source": "manual", "kind": "goto",
                        "payload": {"point": [-380, 520, 2000]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(self.link.sent[0]["intent"], "goto")
        self.assertEqual(self.link.sent[0]["point"][2], 1500.0)
        self.assertEqual(body["command"]["requested"]["point"][2], 2000.0)

    def test_manual_voice_is_suggested(self):
        st, body = req(self.base + "/api/command",
                       {"source": "voice", "kind": "goto",
                        "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "suggested")
        self.assertEqual(self.link.sent, [])

    def test_mode_and_voice(self):
        req(self.base + "/api/mode", {"mode": "auto"})
        st, body = req(self.base + "/api/command",
                       {"source": "voice", "kind": "goto",
                        "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(self.link.sent[0]["src"], "station/voice")

    def test_accept_suggestion(self):
        req(self.base + "/api/command",
            {"source": "voice", "kind": "goto",
             "payload": {"point": [0, 500, 1300]}})
        sid = req(self.base + "/api/state")[1]["suggestions"][0]["id"]
        st, _ = req(self.base + "/api/suggestion/accept", {"id": sid})
        self.assertEqual(st, 200)
        self.assertEqual(req(self.base + "/api/state")[1]["mode"], "manual")

    def test_bad_and_illegal(self):
        self.assertEqual(req(self.base + "/api/command", {})[0], 400)
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "voice", "kind": "jog",
                              "payload": {"v": [1, 0, 0]}})[0], 409)
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "nope", "kind": "goto",
                              "payload": {"point": [0, 0, 1300]}})[0], 409)

    def test_rover_blocks_motion(self):
        self.link.snap = {"body": "rover", "ball": [-380, 520, 1300]}
        st, body = req(self.base + "/api/command",
                       {"source": "manual", "kind": "goto",
                        "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 409)
        self.assertIn("rover", body["error"])
        st, _ = req(self.base + "/api/command",
                    {"source": "voice", "kind": "goto",
                     "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 409)
        self.assertEqual(self.link.sent, [])

    def test_preset_height_guard(self):
        self.link.snap = {"body": "winch", "ball": [-380, 520, 1450]}
        st, body = req(self.base + "/api/command",
                       {"source": "manual", "kind": "preset",
                        "payload": {"name": "up"}})
        self.assertEqual(st, 409)
        self.assertIn("900", body["error"])
        self.assertEqual(self.link.sent, [])

    def test_prediction_auto_sends(self):
        self.app.now = lambda: 1000.0
        self.app.arbiter.now = lambda: 1000.0
        self.app.set_mode("auto")
        self.app.settings(True)
        self.link.snap = {"body": "winch", "ball": [-380, 520, 1300]}
        p = Predictor(self.app.submit_command, lambda: self.link.snap,
                      now=lambda: 1000.0)
        p.tick(1000.0)
        self.assertEqual(self.link.sent[-1]["src"], "station/prediction")
        self.assertEqual(self.link.sent[-1]["point"], [-180.0, 520.0, 1300.0])

    def test_low_confidence_is_suggested(self):
        self.app.now = lambda: 1000.0
        self.app.arbiter.now = lambda: 1000.0
        self.app.set_mode("auto")
        self.app.settings(True)
        st, body = self.app.submit("prediction", "goto",
                                   {"point": [0, 520, 1300]}, confidence=0.6)
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "suggested")
        self.assertEqual(self.link.sent, [])

    def test_type_errors(self):
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "manual", "kind": "goto",
                              "payload": {"point": [0, 0, 1300]},
                              "confidence": "abc"})[0], 400)
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "manual", "kind": "goto",
                              "payload": {"point": [0, 0, 1300]},
                              "ttl_s": "abc"})[0], 400)
        self.assertEqual(req(self.base + "/api/settings",
                             {"prediction_auto": "false"})[0], 400)

    def test_shared_and_index(self):
        with urllib.request.urlopen(self.base + "/shared/params.json", timeout=3) as r:
            self.assertEqual(r.status, 200)
        with urllib.request.urlopen(self.base + "/", timeout=3) as r:
            html = r.read().decode("utf-8")
        self.assertIn("/api/state", html)
        self.assertIn("接管", html)
        self.assertIn("预测", html)
