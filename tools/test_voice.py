"""voice.py 的纯逻辑测试：配置合并、backend 选择、火山请求构造。不发声、不联网。"""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import voice  # noqa: E402


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


def cfg_in(d, obj):
    p = os.path.join(d, "voice.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return voice.load_config(p)


# ---------- backend 选择 ----------
d = tempfile.mkdtemp()
c = cfg_in(d, {})
eq(voice.pick_backend(c), "windows", "默认 auto 且无凭据 → windows")

c = cfg_in(d, {"backend": "cloud"})
eq(voice.pick_backend(c), "windows", "旧值 cloud 按 auto 处理")

c = cfg_in(d, {"volcengine": {"appid": "a1", "token": "t1"}})
eq(voice.pick_backend(c), "volcengine", "凭据填了 → volcengine")

c = cfg_in(d, {"volcengine": {"appid": "PUT_YOUR_VOLC_APPID_HERE", "token": "x"}})
eq(voice.pick_backend(c), "windows", "占位符不算填")

c = cfg_in(d, {"backend": "windows",
               "volcengine": {"appid": "a1", "token": "t1"}})
eq(voice.pick_backend(c), "windows", "显式 windows 优先")

# ---------- brain.json 合并 ----------
c = cfg_in(d, {"voice": "Microsoft Huihui Desktop"})
brain = {"voice": {"provider": "auto",
                   "volcengine": {"appid": "PUT_YOUR_VOLC_APPID_HERE",
                                  "token": "PUT_YOUR_VOLC_ACCESS_TOKEN_HERE"}}}
v = voice.merge_brain(c, brain)
eq(isinstance(v["voice"], str), True, "brain 的 voice dict 不能覆盖音色名")
eq(v["voice"], "Microsoft Huihui Desktop", "音色名保持")
eq(voice.pick_backend(v), "windows", "占位符凭据 → windows")

v = voice.merge_brain(c, {"voice": {"volcengine": {"appid": "a1", "token": "t1"}}})
eq(voice.pick_backend(v), "volcengine", "brain 凭据生效")

v = voice.merge_brain(c, {"voice": "Microsoft Kangkang Desktop"})
eq(v["voice"], "Microsoft Kangkang Desktop", "字符串 voice = 音色名")

# ---------- 火山请求与播放（假 transport / 假 player） ----------
volc = {"appid": "a1", "token": "t1", "cluster": "volcano_tts",
        "voice_type": "BV700_streaming", "encoding": "wav", "speed_ratio": 1.0}
url, headers, payload = voice.volc_request("你好", volc)
eq(url, voice.VOLC_URL, "火山 URL")
eq(headers["Authorization"], "Bearer;t1", "鉴权头是分号格式")
eq(payload["app"]["appid"], "a1", "appid")
eq(payload["request"]["text"], "你好", "文本")

played = []
resp = {"code": 3000, "data": base64.b64encode(b"RIFFfake").decode()}
ok = voice.speak_volcengine("你好", volc,
                            transport=lambda *a: resp,
                            player=lambda data: played.append(data))
eq(ok, True, "火山 speak 返回")
eq(played, [b"RIFFfake"], "解码后的音频交给播放器")

try:
    voice.speak_volcengine("你好", volc, transport=lambda *a: {"code": 3001, "message": "bad"})
except RuntimeError as e:
    assert "3001" in str(e)
else:
    raise SystemExit("FAIL: 火山报错应抛出")

# ---------- speak 端到端（假 player） ----------
seen = []
ok = voice.speak("测试", {"voice": {"provider": "windows"}},
                 player=lambda script: seen.append(script))
eq(ok, True, "windows speak 返回")
eq("Microsoft Huihui Desktop" in seen[0], True, "脚本里是配置的音色名")

print("PASS")
