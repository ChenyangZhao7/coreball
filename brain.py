"""CoreBall 大脑：角色卡 + 事件流记忆 + LLM + 动作意图。

用法：
  python brain.py                 # 打字对话，回复里的动作会通过 UDP 发给 Blender
  python brain.py --once "过来"    # 只跑一轮

配置：brain.json（本地，不提交）。key 填在 providers.<name>.api_key。
记忆：memory/events.jsonl（只追加）、memory/summary.md（压缩后的事实）。
"""
import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "brain.json"
PERSONA = HERE / "persona.md"
MEM_DIR = HERE / "memory"
EVENTS = MEM_DIR / "events.jsonl"
ARCHIVE = MEM_DIR / "events.archive.jsonl"
SUMMARY = MEM_DIR / "summary.md"
PROFILE = MEM_DIR / "profile.md"

ALLOWED = {"come", "back", "up", "down", "look", "stop", "mount_rover", "mount_winch"}
MOVE_RE = re.compile(r'<move\s+intent="([a-zA-Z_]+)"\s*/?>')
ACTIONS = HERE / "blender" / "actions.json"


# ---------------- 文件 ----------------
def load_config(path=CONFIG):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path, default=""):
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else default


def load_events(path=EVENTS, limit=None):
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-limit:] if limit else rows


def append_event(user, reply, path=EVENTS):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "user": user, "assistant": reply},
                           ensure_ascii=False) + "\n")


# ---------------- 文本 ----------------
def parse_move(text):
    """从回复里抠出 <move intent="..."/>，返回（干净文本，意图或 None）。"""
    m = MOVE_RE.search(text)
    if not m:
        return text.strip(), None
    intent = m.group(1).lower()
    clean = MOVE_RE.sub("", text).strip()
    return clean, (intent if intent in ALLOWED else None)


# 口令前一个或两个字是否定词时，这句不是指令（「不停」「别动」「不要动」）
_NEG = ("不", "别", "甭", "莫")


def phrase_intent(user, table=None):
    """用户原话里有没有口令；命中就直接动，不依赖模型记不记得打标签。"""
    if table is None:
        try:
            data = json.loads(ACTIONS.read_text(encoding="utf-8"))
        except Exception:
            return None
        table = (data.get("bindings") or {}).get("voice") or {}
    for phrase, name in table.items():
        if not phrase:
            continue
        start = 0
        while True:
            i = user.find(phrase, start)
            if i < 0:
                break
            prefix = user[max(0, i - 2):i]
            if not any(n in prefix for n in _NEG):
                return name if name in ALLOWED else None
            start = i + 1
    return None


def build_messages(persona, summary, events, user, profile=""):
    system = persona.strip()
    if profile.strip():
        system += "\n\n# 他是谁\n" + profile.strip()
    if summary.strip():
        system += "\n\n# 你记得\n" + summary.strip()
    msgs = [{"role": "system", "content": system}]
    for e in events:
        msgs.append({"role": "user", "content": e.get("user", "")})
        msgs.append({"role": "assistant", "content": e.get("assistant", "")})
    msgs.append({"role": "user", "content": user})
    return msgs


# ---------------- 网络 ----------------
def http_post(url, headers, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def call_llm(cfg, role, messages, transport=http_post):
    name = cfg["roles"][role]
    prov = cfg["providers"][name]
    if not prov.get("api_key"):
        raise RuntimeError("brain.json 里 %s 的 api_key 还是空的" % name)
    payload = {"model": prov["model"], "messages": messages,
               "temperature": cfg.get("temperature", 0.8),
               "max_tokens": cfg.get("max_tokens", 300)}
    out = transport(prov["base_url"].rstrip("/") + "/chat/completions",
                    {"Content-Type": "application/json",
                     "Authorization": "Bearer " + prov["api_key"]},
                    payload)
    return out["choices"][0]["message"]["content"]


def send_intent(intent, cfg):
    body = cfg.get("body", {})
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(json.dumps({"intent": intent, "src": "brain"}).encode("utf-8"),
                 (body.get("udp_host", "127.0.0.1"), int(body.get("udp_port", 4590))))
    finally:
        s.close()


def note_goal(intent, path=None):
    """把当前目标和身体记下来，换身以后能接着用。"""
    p = Path(path) if path else (MEM_DIR / "state.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    if intent == "stop":
        cur["goal"] = None
    elif intent.startswith("mount_"):
        cur["body"] = intent[len("mount_"):]
    else:
        cur["goal"] = intent
    cur["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    return cur


# ---------------- 记忆压缩 ----------------
def summarize(cfg, events, transport=http_post):
    dialog = "\n".join("你：%s\n它：%s" % (e.get("user", ""), e.get("assistant", ""))
                       for e in events)
    msgs = [
        {"role": "system", "content": "把下面的对话压成不超过 5 条事实。只写记下来的事，"
                                      "不要评论，不要称呼，不要分点符号之外的格式。"},
        {"role": "user", "content": dialog},
    ]
    return call_llm(cfg, "memory", msgs, transport).strip()


def maybe_summarize(cfg, transport=http_post, events_path=EVENTS,
                    summary_path=SUMMARY, limit=40, batch=20):
    """事件太多时，把最旧的 batch 条压成事实，追加到 summary，事件归档后移除。"""
    events = load_events(events_path)
    if len(events) <= limit:
        return None
    old, keep = events[:batch], events[batch:]
    fact = summarize(cfg, old, transport)
    p = Path(summary_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n- " + time.strftime("%Y-%m-%d") + "\n" + fact + "\n")
    Path(ARCHIVE).parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE, "a", encoding="utf-8") as f:
        for e in old:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(events_path, "w", encoding="utf-8") as f:
        for e in keep:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return fact


# ---------------- 主循环 ----------------
def reply_once(cfg, user, transport=http_post, speak=True):
    persona = load_text(PERSONA)
    summary = load_text(SUMMARY)
    profile = load_text(PROFILE)
    events = load_events(EVENTS, limit=12)
    msgs = build_messages(persona, summary, events, user, profile)
    raw = call_llm(cfg, "mind", msgs, transport)
    clean, intent = parse_move(raw)
    if intent is None:
        intent = phrase_intent(user)
    append_event(user, clean)
    if intent:
        send_intent(intent, cfg)
        note_goal(intent)
    if speak and clean:
        try:
            import voice
            voice.speak(clean, cfg)
        except Exception as e:
            print("   （没说出来：%s）" % e)
    return clean, intent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--mount", choices=["winch", "rover"])
    a = ap.parse_args()

    try:
        cfg = load_config()
    except Exception as e:
        print("读不到 brain.json：", e)
        return 1
    if not cfg["providers"][cfg["roles"]["mind"]].get("api_key"):
        print("先把 DeepSeek 的 key 填进 brain.json → providers.deepseek.api_key")
        return 2

    if a.mount:
        send_intent("mount_" + a.mount, cfg)
        note_goal("mount_" + a.mount)
        print("已换到", "吊索" if a.mount == "winch" else "小机器人")
        return 0

    if a.once:
        try:
            clean, intent = reply_once(cfg, a.once, speak=not a.no_voice)
        except Exception as e:
            print("出错：", e)
            return 3
        print("它>", clean)
        if intent:
            print("   （身体：%s）" % intent)
        return 0

    print("CoreBall 大脑。输入 q 退出。")
    while True:
        try:
            line = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line.lower() in ("q", "quit", "exit"):
            break
        try:
            clean, intent = reply_once(cfg, line, speak=not a.no_voice)
        except urllib.error.HTTPError as e:
            print("API 出错 %s：%s" % (e.code, e.read().decode("utf-8", "ignore")[:300]))
            continue
        except Exception as e:
            print("出错：", e)
            continue
        print("它>", clean)
        if intent:
            print("   （身体：%s）" % intent)
        try:
            fact = maybe_summarize(cfg)
            if fact:
                print("   （记忆压缩了一次）")
        except Exception as e:
            print("   （记忆压缩失败，先跳过：%s）" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
