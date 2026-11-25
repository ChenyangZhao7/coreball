import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import brain  # noqa: E402


def eq(a, b, msg):
    if a != b:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# ---------- 意图抠取 ----------
eq(brain.parse_move('好。<move intent="come"/>'), ("好。", "come"), "抠意图")
eq(brain.parse_move("好。"), ("好。", None), "没意图")
eq(brain.parse_move('<move intent="nope"/>'), ("", None), "未知意图")
eq(brain.parse_move("过来。\n<move intent=\"come\"/>"), ("过来。", "come"), "多行")

# ---------- 口令兜底 ----------
t = {"过来": "come", "退后": "back", "随便聊聊": "nope"}
eq(brain.phrase_intent("你过来一下", t), "come", "口令命中")
eq(brain.phrase_intent("今天怎么样", t), None, "没口令")
eq(brain.phrase_intent("随便聊聊", t), None, "未知动作忽略")

# ---------- 否定词不算口令 ----------
t2 = {"停": "stop", "过来": "come", "上车": "mount_rover"}
eq(brain.phrase_intent("别停", t2), None, "别停 ≠ 停")
eq(brain.phrase_intent("不要过来", t2), None, "不要过来 ≠ 过来")
eq(brain.phrase_intent("不上车", t2), None, "不上车 ≠ 上车")
eq(brain.phrase_intent("停下", t2), "stop", "停下仍然命中")
eq(brain.phrase_intent("你先过来再説", t2), "come", "正常口令不受影响")

# ---------- 拼消息 ----------
msgs = brain.build_messages("P", "记得你怕吵", [{"user": "a", "assistant": "b"}], "c")
eq(msgs[0]["role"], "system", "system 在最前")
if "记得你怕吵" not in msgs[0]["content"]:
    raise SystemExit("FAIL: 摘要没进 system")
eq(msgs[-1], {"role": "user", "content": "c"}, "最后一条是用户")
eq(len(msgs), 4, "消息条数")

msgs2 = brain.build_messages("P", "", [], "u", "他在济南实习")
if "他在济南实习" not in msgs2[0]["content"]:
    raise SystemExit("FAIL: 个人资料没进 system")

# ---------- 事件流 ----------
d = tempfile.mkdtemp()
ev = os.path.join(d, "e.jsonl")
brain.append_event("u1", "a1", ev)
brain.append_event("u2", "a2", ev)
eq([e["user"] for e in brain.load_events(ev)], ["u1", "u2"], "事件顺序")
eq(brain.load_events(ev, limit=1)[0]["user"], "u2", "limit 取最近")

# ---------- 压缩记忆 ----------
def fake(url, headers, payload, timeout=60):
    assert url.endswith("/chat/completions")
    assert headers["Authorization"].startswith("Bearer ")
    return {"choices": [{"message": {"content": "- 他喜欢安静\n- 他叫老陈"}}]}


cfg = brain.load_config()
cfg["providers"]["deepseek"]["api_key"] = "test"

with open(ev, "w", encoding="utf-8") as f:
    f.write("")
for i in range(21):
    brain.append_event("我%d" % i, "嗯%d" % i, ev)
fact = brain.maybe_summarize(cfg, fake, ev, os.path.join(d, "s.md"), limit=20, batch=10)
if "安静" not in fact:
    raise SystemExit("FAIL: 压缩结果没写出来")
eq(len(brain.load_events(ev)), 11, "归档后剩余条数")
if "他喜欢安静" not in brain.load_text(os.path.join(d, "s.md")):
    raise SystemExit("FAIL: 摘要没落盘")

# ---------- 换身与目标 ----------
eq(brain.phrase_intent("换到车上"), "mount_rover", "换到车上")
eq(brain.phrase_intent("换回吊索"), "mount_winch", "换回吊索")
sf = os.path.join(d, "state.json")
brain.note_goal("come", sf)
eq(json.load(open(sf, encoding="utf-8"))["goal"], "come", "记目标")
brain.note_goal("mount_rover", sf)
eq(json.load(open(sf, encoding="utf-8"))["body"], "rover", "记身体")
brain.note_goal("stop", sf)
eq(json.load(open(sf, encoding="utf-8"))["goal"], None, "停就清目标")

print("PASS")
