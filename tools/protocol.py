"""CoreBall serial protocol v1.1 reference codec.

Frame: A5 5A | VER | TYPE | LEN | PAYLOAD | CRC16-CCITT-FALSE.
CRC covers VER..PAYLOAD. All multi-byte fields — CRC included — are
little-endian, per docs/04-接口标准.md §6.
WHO 请求完整帧（空载荷）：A5 5A 10 01 00 CE BC。
"""
import struct

MAGIC = b"\xA5\x5A"
PROTO_VER = 0x10

WHO = 0x01
CMD = 0x02
STATUS = 0x03
HEARTBEAT = 0x04
ERROR = 0x05

ERR_POWER = 1
ERR_PROTO = 2
ERR_DUMB = 3


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode(ftype, payload=b"", ver=PROTO_VER):
    if len(payload) > 64:
        raise ValueError("payload > 64")
    body = bytes([ver, ftype, len(payload)]) + payload
    return MAGIC + body + struct.pack("<H", crc16(body))


class Frame:
    __slots__ = ("ver", "type", "payload")

    def __init__(self, ver, ftype, payload):
        self.ver = ver
        self.type = ftype
        self.payload = payload

    def __repr__(self):
        return "Frame(ver=0x%02X,type=0x%02X,len=%d)" % (
            self.ver, self.type, len(self.payload))


def decode(buf):
    """Return (frame|None, rest, error|None).

    error is "short" when more bytes are needed, "crc" or "len" otherwise.
    On error the bad frame is dropped and rest keeps scanning after the header.
    """
    buf = bytes(buf)
    if len(buf) < 2:
        return None, buf, "short"
    if buf[:2] != MAGIC:
        i = buf.find(MAGIC)
        if i < 0:
            return None, b"", "sync"
        return None, buf[i:], "sync"
    if len(buf) < 5:
        return None, buf, "short"
    ver, ftype, ln = buf[2], buf[3], buf[4]
    if ln > 64:
        return None, buf[2:], "len"
    need = 5 + ln + 2
    if len(buf) < need:
        return None, buf, "short"
    body = buf[2:5 + ln]
    got = struct.unpack("<H", buf[5 + ln:need])[0]
    if crc16(body) != got:
        return None, buf[2:], "crc"
    return Frame(ver, ftype, body[3:]), buf[need:], None


# ---------------- payloads ----------------

def who_payload(class_id, axes, sensors, draw_mA, battery_mAh, vmax, name,
                proto=PROTO_VER):
    raw = name.encode("utf-8")[:24]
    return struct.pack("<BBB I H H H", proto, class_id, axes, sensors,
                       draw_mA, battery_mAh, vmax) + raw


def parse_who(payload):
    if len(payload) < 13:
        raise ValueError("WHO too short")
    proto, cls, axes, sensors, draw, batt, vmax = struct.unpack(
        "<BBB I H H H", payload[:13])
    name = payload[13:].decode("utf-8", "replace")
    return {
        "proto": proto, "class": cls, "axes": axes, "sensors": sensors,
        "draw_mA": draw, "battery_mAh": batt, "vmax": vmax, "name": name,
    }


def cmd_payload(axis, target, vmax, amax):
    return struct.pack("<BiHH", axis, target, vmax, amax)


def parse_cmd(payload):
    if len(payload) != 9:
        raise ValueError("CMD must be 9 bytes")
    return dict(zip(("axis", "target", "vmax", "amax"),
                    struct.unpack("<BiHH", payload)))


def status_payload(pos, vel, fault):
    return struct.pack("<ihH", pos, vel, fault)


def parse_status(payload):
    if len(payload) != 8:
        raise ValueError("STATUS must be 8 bytes")
    return dict(zip(("pos", "vel", "fault"), struct.unpack("<ihH", payload)))


def error_payload(code):
    return bytes([code])


def parse_error(payload):
    return payload[0] if payload else 0
