import unittest

from station.predictor import Predictor


class PredictorTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.ball = [-380.0, 520.0, 1300.0]

    def submit(self, cmd):
        self.sent.append(cmd)

    def latest(self):
        return {"ball": self.ball}

    def test_tick_builds_suggestion(self):
        p = Predictor(self.submit, self.latest, now=lambda: 100.0)
        c = p.tick(100.0)
        self.assertEqual(c.source, "prediction")
        self.assertEqual(c.payload["point"], [-180.0, 520.0, 1300.0])
        self.assertEqual(c.confidence, 0.75)
        self.assertEqual(self.sent[0].source, "prediction")

    def test_interval_and_no_ball(self):
        p = Predictor(self.submit, lambda: None, now=lambda: 100.0)
        self.assertIsNone(p.tick(100.0))
        self.ball = None
        p2 = Predictor(self.submit, self.latest, now=lambda: 100.0)
        self.assertIsNone(p2.tick(100.0))

    def test_interval_rate(self):
        p = Predictor(self.submit, self.latest, now=lambda: 100.0)
        self.assertIsNotNone(p.tick(100.0))
        self.assertIsNone(p.tick(103.0))
        self.assertIsNotNone(p.tick(108.1))

    def test_stale_telemetry_is_ignored(self):
        p = Predictor(self.submit,
                      lambda: {"ball": self.ball, "stale": True},
                      now=lambda: 100.0)
        self.assertIsNone(p.tick(100.0))
