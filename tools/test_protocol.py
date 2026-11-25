import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocol as P


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# CRC-16/CCITT-FALSE check vector
eq(P.crc16(b"123456789"), 0x29B1, "CRC 校验向量")

# 冻结标准的 WHO 请求完整帧（docs/04 §6）：A5 5A 10 01 00 + CRC 小端
eq(P.encode(P.WHO).hex(), "a55a100100cebc", "WHO 请求帧字节流")
f, rest, err = P.decode(bytes.fromhex("a55a100100cebc"))
eq((err, f.type, f.payload), (None, P.WHO, b""), "WHO 请求解码")

# 帧往返
raw = P.encode(P.CMD, P.cmd_payload(0, 1000, 500, 1000))
f, rest, err = P.decode(raw)
eq(err, None, "解码错误")
eq(rest, b"", "剩余")
eq((f.ver, f.type), (0x10, P.CMD), "帧头")
eq(P.parse_cmd(f.payload)["target"], 1000, "target")

# 半帧保留
f, rest, err = P.decode(raw[:6])
eq(f, None, "半帧不解")
eq(err, "short", "半帧状态")
eq(rest, raw[:6], "半帧保留")

# CRC 错丢帧
bad = bytearray(raw)
bad[-1] ^= 0xFF
f, rest, err = P.decode(bytes(bad))
eq(f, None, "坏 CRC 不解")
eq(err, "crc", "坏 CRC 状态")

# WHO / STATUS
w = P.who_payload(3, 1, 0x03, 2500, 0, 1200, "轮式底盘")
d = P.parse_who(P.decode(P.encode(P.WHO, w))[0].payload)
eq((d["draw_mA"], d["name"]), (2500, "轮式底盘"), "WHO")

s = P.parse_status(P.decode(P.encode(P.STATUS, P.status_payload(-50, 12, 2)))[0].payload)
eq((s["pos"], s["vel"], s["fault"]), (-50, 12, 2), "STATUS")

# 超长
try:
    P.encode(P.CMD, b"x" * 65)
except ValueError:
    pass
else:
    raise SystemExit("FAIL: >64 应报错")

print("PASS")
