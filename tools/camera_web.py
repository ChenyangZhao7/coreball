"""浏览器里的实时摄像头 + 手势骨架。

用法：
  .venv\\Scripts\\python.exe tools\\camera_web.py            # 摄像头 + 手势骨架
  .venv\\Scripts\\python.exe tools\\camera_web.py --raw      # 只出画面（操作台用）
  .venv\\Scripts\\python.exe tools\\camera_web.py --camera 1 # 选另一个摄像头
然后浏览器打开 http://127.0.0.1:8765
开关：GET /control?on=0 释放摄像头，GET /control?on=1 重新打开。

为什么不用 OpenCV 窗口：部分 Windows 机器上 HighGUI 会卡成「未响应」。
"""
import http.server
import os
import socketserver
import sys
import threading
import time

try:
    import cv2
except Exception as e:
    print("NO_DEPS:", e)
    sys.exit(3)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "hand_landmarker.task")
PORT = 8765

LATEST = {"jpg": b"", "note": "starting"}
STATE = {"on": True}
LOCK = threading.Lock()

CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
        (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>CoreBall Camera</title><style>
html,body{margin:0;height:100%;background:#0a0d10;color:#c9d6e2;
font:14px/1.5 "Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:18px}
img{width:100%;border-radius:10px;background:#000}
.hint{color:#7f8f9c;margin-top:10px}
b{color:#4fd39b}
</style></head><body><div class="wrap">
<img src="/stream" alt="camera">
<div class="hint">绿点 = 识别到的手。把「要举手的区域」放进画面，再去看左上角的 HAND / no hand。</div>
</div></body></html>"""


def worker(camera=0, raw=False):
    cap = None
    landmarker = None
    fps = 0.0
    last = time.time()
    hits = frames = 0
    while True:
        if not STATE["on"]:
            if cap is not None:
                cap.release()
                cap = None
            with LOCK:
                LATEST["jpg"] = b""
            time.sleep(0.2)
            continue
        if cap is None:
            cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
            if not cap.isOpened():
                LATEST["note"] = "NO_CAMERA"
                cap = None
                time.sleep(0.6)
                continue
            LATEST["note"] = "on"
            if not raw and landmarker is None:
                if not os.path.exists(MODEL):
                    LATEST["note"] = "NO_MODEL"
                    cap.release()
                    cap = None
                    time.sleep(1.0)
                    continue
                try:
                    import mediapipe as mp
                    from mediapipe.tasks import python as mpp
                    from mediapipe.tasks.python import vision
                except Exception:
                    LATEST["note"] = "NO_DEPS"
                    cap.release()
                    cap = None
                    time.sleep(1.0)
                    continue
                opts = vision.HandLandmarkerOptions(
                    base_options=mpp.BaseOptions(model_asset_path=MODEL),
                    num_hands=1, running_mode=vision.RunningMode.VIDEO,
                    min_hand_detection_confidence=0.5, min_tracking_confidence=0.5)
                landmarker = vision.HandLandmarker.create_from_options(opts)
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01)
            continue
        frame = cv2.flip(frame, 1)
        if landmarker is not None:
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(time.time() * 1000))
            frames += 1
            hand = bool(res.hand_landmarks)
            if hand:
                hits += 1
                pts = [(int(p.x * w), int(p.y * h)) for p in res.hand_landmarks[0]]
                for a, b in CONN:
                    cv2.line(frame, pts[a], pts[b], (0, 200, 120), 2)
                for p in pts:
                    cv2.circle(frame, p, 4, (0, 255, 160), -1)
            now = time.time()
            fps = 0.9 * fps + 0.1 / max(1e-3, now - last)
            last = now
            cv2.putText(frame, "HAND" if hand else "no hand", (16, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 220, 120) if hand else (80, 80, 255), 2)
            cv2.putText(frame, "%.0f fps   %.0f%% hit" % (fps, 100.0 * hits / max(1, frames)),
                        (16, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (205, 215, 225), 1)
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if ok:
            with LOCK:
                LATEST["jpg"] = jpg.tobytes()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/control"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            STATE["on"] = q.get("on", ["1"])[0].lower() not in ("0", "false", "off", "no")
            if not STATE["on"]:
                with LOCK:
                    LATEST["jpg"] = b""
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    with LOCK:
                        jpg = LATEST["jpg"]
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode("utf-8"))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="CoreBall browser camera")
    ap.add_argument("--camera", type=int, default=0, help="摄像头编号（默认 0）")
    ap.add_argument("--raw", action="store_true", help="只出画面，不跑手势骨架")
    args = ap.parse_args()
    threading.Thread(target=worker, args=(args.camera, args.raw), daemon=True).start()
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as srv:
        srv.daemon_threads = True
        print("打开 http://127.0.0.1:%d" % PORT, flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
