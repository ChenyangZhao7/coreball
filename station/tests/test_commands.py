import tempfile
import unittest
from pathlib import Path

from station import commands as C
from station.history import History

NOW = 1000.0


def cmd(source="manual", kind="goto", payload=None, **kw):
    return C.Command(source=source, kind=kind,
                     payload=payload or {"point": [-380.0, 520.0, 1300.0]},
                     created_at=NOW, **kw)


class ArbiterTest(unittest.TestCase):
    def setUp(self):
        self.a = C.Arbiter(now=lambda: NOW)

    def test_manual_voice_is_suggested(self):
        self.assertEqual(self.a.submit(cmd(source="voice")), "suggested")
        self.assertEqual(self.a.status()["mode"], "manual")
        self.assertIsNone(self.a.status()["active"])

    def test_manual_goto_accepted_and_z_clamped(self):
        c = cmd(payload={"point": [-380.0, 520.0, 5000.0]})
        self.assertEqual(self.a.submit(c), "accepted")
        self.assertEqual(c.payload["point"][2], 1500.0)
        self.assertEqual(c.requested["point"][2], 5000.0)

    def test_auto_voice_accepted(self):
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="voice")), "accepted")
        self.assertEqual(self.a.status()["current_source"], "voice")

    def test_lower_priority_rejected_during_hold(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="behavior")), "rejected")

    def test_lower_priority_after_hold_accepted(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.a.now = lambda: NOW + 2.1
        self.assertEqual(self.a.submit(cmd(source="behavior")), "accepted")

    def test_manual_preempts_voice(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="manual")), "accepted")
        self.assertEqual(self.a.status()["mode"], "manual")

    def test_stop_clears_and_manual(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="voice", kind="stop",
                                          payload={})), "accepted")
        s = self.a.status()
        self.assertEqual(s["mode"], "manual")
        self.assertIsNone(s["active"])

    def test_bad_command(self):
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(kind="nope"))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(source="nope"))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(payload={"point": [float("nan"), 0, 1300]}))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(source="voice", kind="jog",
                              payload={"v": [10, 0, 0]}))
        with self.assertRaises(C.BadCommand):
            self.a.submit(C.Command("manual", "goto", []))

    def test_ttl_expired(self):
        old = cmd()
        old.created_at = NOW - 10
        self.assertEqual(self.a.submit(old), "expired")

    def test_prediction_suggested_by_default(self):
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="prediction")), "suggested")

    def test_prediction_auto_runs_when_idle(self):
        self.a.set_mode("auto")
        self.a.set_prediction_auto(True)
        self.assertEqual(self.a.submit(cmd(source="prediction")), "accepted")

    def test_prediction_auto_blocked_by_recent_manual(self):
        self.a.set_prediction_auto(True)
        self.a.submit(cmd(source="manual"))
        self.a.now = lambda: NOW
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="prediction")), "suggested")

    def test_accept_suggestion_becomes_manual(self):
        self.a.submit(cmd(source="voice"))
        sid = self.a.status()["suggestions"][0]["id"]
        self.a.accept(sid)
        s = self.a.status()
        self.assertEqual(s["mode"], "manual")
        self.assertEqual(s["current_source"], "manual")

    def test_suggestions_are_listed(self):
        self.a.submit(cmd())
        self.a.submit(cmd(source="voice"))
        self.assertEqual(len(self.a.status()["suggestions"]), 1)

    def test_prediction_suggestion_replaces_old(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="prediction"))
        first = self.a.status()["suggestions"][0]["id"]
        self.a.submit(cmd(source="prediction"))
        suggestions = self.a.status()["suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertNotEqual(suggestions[0]["id"], first)


class HistoryTest(unittest.TestCase):
    def test_append_recent(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d) / "history.jsonl")
            h.append({"id": "1", "source": "manual"})
            h.append({"id": "2", "source": "voice"})
            self.assertEqual([x["id"] for x in h.recent(10)], ["1", "2"])

    def test_history_is_trimmed_and_zero_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d) / "history.jsonl", limit=2)
            for i in range(3):
                h.append({"id": str(i)})
            self.assertEqual([x["id"] for x in h.recent(10)], ["1", "2"])
            self.assertEqual(h.recent(0), [])
