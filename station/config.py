"""控制台常量。单位 mm / s。"""
HOST = "127.0.0.1"
PORT = 8030

INTENT_ADDR = ("127.0.0.1", 4590)
TELEMETRY_ADDR = ("127.0.0.1", 4591)

PRIORITIES = {
    "manual": 100,
    "voice": 60,
    "behavior": 50,
    "prediction": 20,
}
DEFAULT_TTL = {
    "goto": 5.0,
    "jog": 1.0,
    "expression": 5.0,
    "preset": 5.0,
    "stop": 0.0,
}
HOLD_S = 2.0
Z_MIN = 900.0
Z_MAX = 1500.0
MAX_JOG = 400.0

PRESETS = ("come", "back", "look", "up", "down", "left", "right")
EXPRESSIONS = ("idle", "listening", "acting")

PREDICTION_INTERVAL = 8.0
PREDICTION_CONFIDENCE = 0.75
PREDICTION_AUTO_MIN = 0.7
PREDICTION_IDLE_S = 2.0
