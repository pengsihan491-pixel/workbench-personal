#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 会话存档_明细.csv 压成工作台能读的 会话分析.json"""
import csv, json, pathlib
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "会话存档_明细.csv"
OUT = HERE / "会话分析.json"

KW = {"等行情": ["等行情", "观望", "等回调", "行情不好"],
      "嫌贵/预算": ["太贵", "没钱", "预算", "便宜", "优惠", "分期"],
      "想报名": ["报名", "怎么买", "在哪付", "付款", "转账"],
      "已付款": ["付了", "转了", "买了", "拍下", "已支付"],
      "异议": ["考虑", "再看看", "不合适", "没时间", "太忙"],
      "问课程": ["讲什么", "内容", "多久", "几天", "回放"]}


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    mine = [r for r in rows if r["方向"] == "我方"]
    them = [r for r in rows if r["方向"] == "对方"]
    txt = Counter(r["内容"] for r in mine if r["内容"])
    blast = {t: n for t, n in txt.items() if n >= 20}
    real_mine = [r for r in mine if txt.get(r["内容"], 0) < 20]

    per = defaultdict(lambda: {"我方": 0, "对方": 0, "最近": "", "最近对方": "", "号": ""})
    for r in rows:
        p = per[r["客户"]]
        p["我方" if r["方向"] == "我方" else "对方"] += 1
        if r["时间"]:
            p["最近"] = max(p["最近"], r["时间"])
            if r["方向"] == "对方":
                p["最近对方"] = max(p["最近对方"], r["时间"])
        if r["所属号"]:
            p["号"] = r["所属号"]

    intent = defaultdict(list)
    for r in them:
        t = (r["内容"] or "").strip()
        if not t or len(t) > 120:
            continue
        for k, ws in KW.items():
            if any(w in t for w in ws):
                intent[k].append({"人": r["客户"], "话": t[:80], "时间": r["时间"]})
                break

    for k in intent:
        seen, uniq = set(), []
        for x in intent[k]:
            if x["人"] in seen:
                continue
            seen.add(x["人"]); uniq.append(x)
        intent[k] = uniq[:200]

    # ---------- 互动分层 H1–H5（按消息顺序判，不只看条数）----------
    from collections import defaultdict as _dd
    by_who = _dd(list)
    for r in rows:
        by_who[(r["客户ID"] or r["客户"], r["客户"])].append(r)
    CONTENT_KW = ["链接", "资料", "笔记", "回放", "课件", "课程", "直播", "报名", "开课", "http"]
    tiers = {"H5 经常沟通": [], "H4 偶尔沟通": [], "H3 内容有回应": [],
             "H2 群发有回应": [], "H1 完全不回复": []}
    silent_chats = {r["会话键"] for r in rows if r["客户"] == "（客户未发言）"}
    for (who_id, who), msgs in by_who.items():
        if who == "（客户未发言）":
            continue
        msgs.sort(key=lambda x: x["时间"] or "")
        n_them = sum(1 for m in msgs if m["方向"] == "对方")
        n_me = sum(1 for m in msgs if m["方向"] == "我方")
        n_me_real = sum(1 for m in msgs if m["方向"] == "我方" and txt.get(m["内容"], 0) < 20)
        n_blast = n_me - n_me_real
        # 来回轮次：对方每次「接话」算一轮
        rounds, prev = 0, None
        for m in msgs:
            if m["方向"] == "对方" and prev != "对方":
                rounds += 1
            prev = m["方向"]
        # 我方发内容/群发后，对方 24h 内有没有回
        import datetime as _dt
        def _t(x):
            try:
                return _dt.datetime.strptime((x or "")[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        reply_content = reply_blast = False
        for i, m in enumerate(msgs):
            if m["方向"] != "我方":
                continue
            base = _t(m["时间"])
            if not base:
                continue
            is_content = any(k in (m["内容"] or "") for k in CONTENT_KW)
            is_blast = txt.get(m["内容"], 0) >= 20
            for m2 in msgs[i + 1:]:
                if m2["方向"] != "对方":
                    continue
                t2 = _t(m2["时间"])
                if not t2 or (t2 - base).total_seconds() > 86400:
                    break
                if is_content:
                    reply_content = True
                if is_blast:
                    reply_blast = True
                break
        asked = any(("?" in (m["内容"] or "") or "？" in (m["内容"] or "")
                     or any(w in (m["内容"] or "") for w in ("吗", "怎么", "多少", "能不能", "有没有")))
                    for m in msgs if m["方向"] == "对方")
        if n_them == 0:
            tier = "H1 完全不回复"
        elif rounds >= 4 or n_them >= 20:
            tier = "H5 经常沟通"
        elif n_them >= 3:
            tier = "H4 偶尔沟通"
        elif reply_content:
            tier = "H3 内容有回应"
        else:
            tier = "H2 群发有回应"
        last = msgs[-1] if msgs else {}
        last_dir = last.get("方向") or ""
        last_time = (last.get("时间") or "")[:16]
        # 待回复：最后一条是客户发的，且在最近 3 天
        import datetime as _d2
        wait_reply = False
        if last_dir == "对方" and last_time:
            try:
                t = _d2.datetime.strptime(last_time, "%Y-%m-%d %H:%M")
                wait_reply = (_d2.datetime.now() - t).days <= 3
            except ValueError:
                wait_reply = False
        tiers[tier].append({
            "人": who, "对方": n_them, "我方真人": n_me_real, "群发": n_blast,
            "轮次": rounds, "提问": asked, "回内容": reply_content, "回群发": reply_blast,
            "最近": last_time, "最后方向": last_dir, "待回复": wait_reply,
         })

    days = Counter((r["时间"] or "")[:10] for r in rows if r["时间"])
    out = {
        "总消息": len(rows), "我方": len(mine), "对方": len(them),
        "对象数": len(per),
        "群发模板数": len(blast), "群发消息数": sum(blast.values()),
        "真人发出": len(real_mine),
        "群发Top": [{"文": t[:90], "次": n} for t, n in sorted(blast.items(), key=lambda kv: -kv[1])[:6] if t != "[图片]"],
        "单向人数": sum(1 for v in per.values() if v["对方"] == 0),
        "只回一两条": sum(1 for v in per.values() if 0 < v["对方"] <= 2),
        "真聊人数": sum(1 for v in per.values() if v["对方"] >= 10),
        "意向": {k: {"人数": len(v), "样例": v[:40]} for k, v in intent.items()},
        "按天": dict(sorted(days.items(), reverse=True)[:40]),
        "活跃对话": [{"人": k, **v} for k, v in sorted(per.items(), key=lambda kv: -kv[1]["对方"])[:60]],
        "互动分层": {k: {"人数": len(v), "样例": sorted(v, key=lambda x: -x["对方"])[:80]}
                     for k, v in tiers.items()},
        "单向会话": len(silent_chats),
        "待回复": sorted([x for v in tiers.values() for x in v if x.get("待回复")],
                        key=lambda x: x["最近"], reverse=True)[:120],
        "生成时间": __import__("time").strftime("%Y-%m-%d %H:%M"),
    }
    # 聊天索引：给「打标签清单」补最近一句话
    idx = {}
    for who, k in per.items():
        idx[who] = {"对方": k["对方"], "最近": k["最近"], "最近对方": k["最近对方"]}
    lastwords = {}
    for r in rows:
        if r["方向"] != "对方" or not (r["内容"] or "").strip():
            continue
        w = r["客户"]
        if not w or w == "（客户未发言）":
            continue
        t = r["时间"] or ""
        if t >= (lastwords.get(w) or ("",))[0]:
            lastwords[w] = (t, (r["内容"] or "").strip()[:60])
    for w, (t, txt) in lastwords.items():
        idx.setdefault(w, {})["最后一句"] = txt
    (HERE / "聊天索引.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")

    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("→", OUT.name)
    print("  消息 %d（我方 %d / 对方 %d）· 对象 %d · 群发 %d 条 · 真人发出 %d 条"
          % (out["总消息"], out["我方"], out["对方"], out["对象数"], out["群发消息数"], out["真人发出"]))
    for k, v in out["意向"].items():
        print("  %-8s %3d 人" % (k, v["人数"]))


if __name__ == "__main__":
    main()
