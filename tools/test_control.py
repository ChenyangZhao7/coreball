import http.client
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control_server as C


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


def ok(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)


def wait_for(fn, msg, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.02)
    raise SystemExit("FAIL: 等待超时 - " + msg)


# ---------- TelemetryStore（纯逻辑）----------
st = C.TelemetryStore(max_age=1.0)
eq(st.get(), None, "空 store 应返回 None")
eq(st.put(b"not json", now=100.0), False, "坏 JSON 应拒绝")
eq(st.put(b"[1,2,3]", now=100.0), False, "JSON 不是对象应拒绝")
eq(st.put(json.dumps({"ball": [1, 2, 3]}).encode(), now=100.0), True, "好 JSON 应接收")

g = st.get(now=100.2)
eq(g["ok"], True, "有数据时 ok")
eq(g["ball"], [1, 2, 3], "数据透传")
eq(g["age_ms"], 200, "age_ms")
eq(g["stale"], False, "1 s 内不算超时")
eq(st.get(now=101.5)["stale"], True, "超过 max_age 应超时")

# ---------- HTTP 桥 ----------
C.UDP_ADDR = ("127.0.0.1", 4599)
srv = C.create_server(port=8011)
threading.Thread(target=srv.serve_forever, daemon=True).start()

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.bind(C.UDP_ADDR)
udp.settimeout(2)

http = http.client.HTTPConnection("127.0.0.1", 8011)
http.request("POST", "/intent",
             body=json.dumps({"intent": "goto", "point": [1, 2, 3]}),
             headers={"Content-Type": "application/json"})
r = http.getresponse()
eq(r.status, 204, "POST 状态")
data, _ = udp.recvfrom(2048)
eq(json.loads(data.decode())["intent"], "goto", "UDP 内容")

http.request("GET", "/")
r = http.getresponse()
eq(r.status, 200, "首页状态")
if b"CoreBall" not in r.read():
    raise SystemExit("FAIL: 首页不是控制台")

# 没有遥测时 /state 明确返回 ok=false
http.request("GET", "/state")
r = http.getresponse()
eq(r.status, 200, "空 /state 状态")
eq(json.loads(r.read())["ok"], False, "空 /state")
eq(r.getheader("Cache-Control"), "no-store", "/state 不应被缓存")

# ---------- 遥测监听 -> /state ----------
C.STORE = C.TelemetryStore()
tsock, tthread = C.start_telemetry(port=0, store=C.STORE)
tport = tsock.getsockname()[1]

sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = {
    "ball": [-380, 520, 1300], "hub": [-380, 520, 1460],
    "body": "winch", "support": [0, 1, 2, 3], "tensions": [2.05, 1.83, 2.1, 1.83],
    "margin": 1.83, "closed": True, "t": time.time(),
}
sender.sendto(json.dumps(payload).encode(), ("127.0.0.1", tport))
wait_for(lambda: C.STORE.get() is not None, "遥测包没进 store")

http.request("GET", "/state")
r = http.getresponse()
state = json.loads(r.read())
eq(state["ok"], True, "收到遥测后 ok")
eq(state["ball"], [-380, 520, 1300], "/state 里的球心")
eq(state["support"], [0, 1, 2, 3], "/state 里的支撑绳")
ok(state["age_ms"] >= 0, "age_ms 不应为负")

tsock.close()
sender.close()
srv.shutdown()
udp.close()
print("PASS")
