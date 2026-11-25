"""说话（TTS）。默认用 Windows 自带中文语音，零成本、离线；填了火山引擎凭据就自动切过去。

用法：
  python voice.py "你好，我是 CoreBall。"
  python brain.py --once "你好"

配置（两处都可以，brain.json 优先）：
  voice.json（本地，不提交）
    backend: "auto" | "windows" | "volcengine"   （旧值 "cloud" 按 auto 处理）
    voice:   Windows 音色名，例如 "Microsoft Huihui Desktop"
    rate:    -10..10，0 是正常语速
    auto_speak: true 时 brain.py 回复完自动念
    volcengine: { appid, token, cluster, voice_type, encoding, speed_ratio }
  brain.json 的 voice 段：
    { "provider": "auto", "volcengine": { appid, token, ... } }
    provider = auto 时：火山凭据填了就走火山，没填就走 Windows 离线。

火山引擎控制台：语音技术 → 语音合成 → 创建应用，拿 APPID 和 Access Token。
"""
import base64
import json
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICE = HERE / "voice.json"

DEFAULTS = {
    "backend": "auto",
    "voice": "Microsoft Huihui Desktop",
    "rate": 0,
    "auto_speak": True,
    "volcengine": {
        "appid": "",
        "token": "",
        "cluster": "volcano_tts",
        "voice_type": "BV700_streaming",
        "encoding": "wav",
        "speed_ratio": 1.0,
    },
}

VOLC_URL = "https://openspeech.bytedance.com/api/v1/tts"


def load_config(path=VOICE):
    cfg = json.loads(json.dumps(DEFAULTS))
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def merge_brain(cfg, brain_cfg):
    """把 brain.json 的 voice 段叠上来。

    voice 段是 dict：认 provider / volcengine / voice / rate；
    是字符串：当作 Windows 音色名。绝不把 dict 塞进音色名。
    """
    if not brain_cfg:
        return cfg
    bv = brain_cfg.get("voice")
    if isinstance(bv, dict):
        if bv.get("provider"):
            cfg["backend"] = bv["provider"]
        if isinstance(bv.get("volcengine"), dict):
            cfg["volcengine"].update(bv["volcengine"])
        if isinstance(bv.get("voice"), str):
            cfg["voice"] = bv["voice"]
        if "rate" in bv:
            cfg["rate"] = bv["rate"]
    elif isinstance(bv, str):
        cfg["voice"] = bv
    return cfg


def volc_ready(volc):
    appid, token = str(volc.get("appid", "")), str(volc.get("token", ""))
    return bool(appid and token) and "PUT_YOUR" not in appid and "PUT_YOUR" not in token


def pick_backend(cfg):
    backend = str(cfg.get("backend", "auto")).lower()
    if backend == "cloud":
        backend = "auto"          # 旧配置里的 cloud 从未实现，按 auto 处理
    if backend == "auto":
        return "volcengine" if volc_ready(cfg.get("volcengine") or {}) else "windows"
    return backend


def speak(text, cfg=None, transport=None, player=None):
    """cfg 是整份 brain.json（可选）。transport / player 仅供测试注入。"""
    text = (text or "").strip()
    if not text:
        return False
    v = merge_brain(load_config(), cfg)
    backend = pick_backend(v)
    if backend == "volcengine":
        return speak_volcengine(text, v["volcengine"], transport=transport, player=player)
    if backend == "windows":
        return speak_windows(text, v, player=player)
    raise RuntimeError("不认识的 backend: %r" % backend)


# ---------------- Windows 离线 ----------------
def _run_powershell(script):
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def speak_windows(text, cfg, player=None):
    voice = cfg.get("voice", "Microsoft Huihui Desktop")
    if not isinstance(voice, str):
        voice = "Microsoft Huihui Desktop"
    voice = voice.replace("'", "")
    rate = int(cfg.get("rate", 0))
    tmp = Path(tempfile.gettempdir()) / "coreball_say.txt"
    tmp.write_text(text, encoding="utf-8")
    path = str(tmp).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "try { $s.SelectVoice('%s') } catch {}; "
        "$s.Rate = %d; "
        "$s.Speak([IO.File]::ReadAllText('%s', [Text.Encoding]::UTF8))"
    ) % (voice, rate, path)
    (player or _run_powershell)(script)
    return True


# ---------------- 火山引擎 ----------------
def _http_json(url, headers, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def volc_request(text, volc):
    """构造火山 TTS 请求（url, headers, payload）。单独抽出方便测试。"""
    return (
        VOLC_URL,
        {"Content-Type": "application/json",
         "Authorization": "Bearer;%s" % volc["token"]},
        {
            "app": {"appid": volc["appid"], "token": volc["token"],
                    "cluster": volc.get("cluster", "volcano_tts")},
            "user": {"uid": "coreball"},
            "audio": {"voice_type": volc.get("voice_type", "BV700_streaming"),
                      "encoding": volc.get("encoding", "wav"),
                      "speed_ratio": float(volc.get("speed_ratio", 1.0))},
            "request": {"req_id": uuid.uuid4().hex, "text": text,
                        "text_type": "plain", "operation": "query"},
        },
    )


def play_wav(data):
    import winsound
    tmp = Path(tempfile.gettempdir()) / "coreball_tts.wav"
    tmp.write_bytes(data)
    winsound.PlaySound(str(tmp), winsound.SND_FILENAME)


def speak_volcengine(text, volc, transport=None, player=None):
    if not volc_ready(volc):
        raise RuntimeError("火山 TTS 没配好：brain.json → voice.volcengine 填 appid 和 token")
    url, headers, payload = volc_request(text, volc)
    resp = (transport or _http_json)(url, headers, payload)
    if not isinstance(resp, dict) or resp.get("code") != 3000 or not resp.get("data"):
        raise RuntimeError("火山 TTS 失败：%s %s" % (
            (resp or {}).get("code"), (resp or {}).get("message")))
    (player or play_wav)(base64.b64decode(resp["data"]))
    return True


def main():
    if len(sys.argv) > 1:
        speak(" ".join(sys.argv[1:]))
        return 0
    cfg = load_config()
    cfg["_effective_backend"] = pick_backend(cfg)
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
