#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉 CRM 里同步好的「企业微信会话存档」消息

    python3 抓会话存档.py --days 30        # 拉最近 30 天
    python3 抓会话存档.py --staff 70       # 只看某个号
    python3 抓会话存档.py --full           # 全量（会很久）

产出：
    会话存档_明细.csv   时间 / 方向 / 类型 / 内容 / 对方 / 所属号
    会话_统计.json      按客户聚合：条数、我方/对方、最近、关键词

数据来源：GET /api/workbuddy/my-group/msgaudit/messages
"""
import argparse, csv, json, os, pathlib, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "会话存档_明细.csv"
STAT = HERE / "会话_统计.json"
BASE = "https://jiasujiaoyu.cn/api/workbuddy"

KW = {
    "等行情": ["等行情", "观望", "等回调", "行情不好", "等大盘"],
    "嫌贵/预算": ["太贵", "没钱", "预算", "便宜", "优惠", "分期"],
    "想报名": ["报名", "怎么买", "在哪付", "链接", "名额", "开课时间"],
    "已付款": ["付了", "转了", "买了", "拍下", "已支付"],
    "异议": ["考虑一下", "再看看", "不合适", "没时间", "太忙"],
    "问课程": ["讲什么", "内容", "多久", "几天", "回放"],
}


def token():
    t = os.environ.get("WORKBUDDY_TOKEN") or os.environ.get("WB_CHAT_TOKEN")
    if not t:
        p = pathlib.Path.home() / ".workbuddy_chat_token"
        if p.exists():
            t = p.read_text().strip()
    if not t:
        sys.exit("缺凭证：export WORKBUDDY_TOKEN=jsu_xxx 或写到 ~/.workbuddy_chat_token")
    return t


TOK = token()


def get(path, params=None, timeout=60):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOK,
                                               "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(30)
                continue
            return {"ok": False, "error": "http_%d" % e.code,
                    "body": e.read().decode("utf-8", "replace")[:200]}
        except Exception as e:  # noqa: BLE001
            time.sleep(2)
    return {"ok": False, "error": "retry_exhausted"}


PROG = HERE / "会话存档_进度.json"


def load_prog():
    if PROG.exists():
        try:
            return json.loads(PROG.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"已完成天": []}


def fetch_day(day, staff=""):
    """拉某一天（自动翻页，遇 502 退避重试）"""
    params = {"from": day, "to": day}
    if staff:
        params["staff_ids"] = staff
    out, before, pages = [], None, 0
    while pages < 40:
        p = dict(params)
        if before:
            p["before"] = before
        d = None
        for attempt in range(4):
            d = get("/my-group/msgaudit/messages", p)
            if d.get("ok"):
                break
            err = str(d.get("error") or "")
            if "502" in err or "timeout" in err or "500" in err:
                time.sleep(3 * (attempt + 1))
                continue
            break
        if not d or not d.get("ok"):
            return out, False
        out += d.get("list") or []
        pages += 1
        if not d.get("has_more"):
            return out, True
        before = d.get("next_before")
        if not before:
            return out, True
        time.sleep(0.4)
    return out, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--staff", default="")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--max-pages", type=int, default=200)
    a = ap.parse_args()

    prog = load_prog()
    done_days = set(prog.get("已完成天") or [])
    days = [time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
            for i in range(a.days)]
    days = list(reversed(days))
    todo = [d for d in days if a.full or d not in done_days]
    print("要拉 %d 天（已拉过 %d 天，本次 %d 天）" % (len(days), len(days) - len(todo), len(todo)))

    rows = []
    for i, day in enumerate(todo, 1):
        batch, ok = fetch_day(day, a.staff)
        rows += batch
        if ok:
            done_days.add(day)
            prog["已完成天"] = sorted(done_days)
            PROG.write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
        print("  %s  %d 条%s  累计 %d" % (day, len(batch), "" if ok else "（未完成，下次重试）", len(rows)), flush=True)

    if not rows:
        print("没拉到消息"); return

    # 明细
    # 按 chat_key 建会话表：客户名/客户ID 从「对方消息」取，员工从「我方消息」取
    chats = {}
    for m in rows:
        ck = m.get("chat_key") or ("solo-" + str(m.get("id")))
        c = chats.setdefault(ck, {"客户": "", "客户ID": "", "号": ""})
        if m.get("mine"):
            c["号"] = c["号"] or (m.get("fromName") or "")
        else:
            c["客户"] = c["客户"] or (m.get("fromName") or "")
            c["客户ID"] = c["客户ID"] or (m.get("from_userid") or "")
    for ck, c in chats.items():
        if not c["客户"]:
            c["客户"] = "（客户未发言）"

    # 追加去重：老行保留，新行按 (时间+方向+内容+客户) 去重
    old_rows = []
    if OUT.exists() and not a.full:
        try:
            old_rows = list(csv.DictReader(OUT.open(encoding="utf-8-sig")))
        except Exception:
            old_rows = []
        have = {(r.get("时间"), r.get("方向"), r.get("内容"), r.get("客户")) for r in old_rows}
        rows = [m for m in rows if ((m.get("sentAt",""), ("我方" if m.get("mine") else "对方"),
                (m.get("text") or "").replace("\n"," ")[:300],
                (chats.get(m.get("chat_key") or "") or {}).get("客户") or "未知")) not in have]
        print("  本次新增 %d 条（已有 %d 条）" % (len(rows), len(old_rows)))

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["时间", "方向", "类型", "内容", "客户", "客户ID", "会话键", "所属号"])
        for m in rows:
            ck = m.get("chat_key") or ("solo-" + str(m.get("id")))
            c = chats.get(ck) or {"客户": "", "客户ID": "", "号": ""}
            mine = "我方" if m.get("mine") else "对方"
            w.writerow([m.get("sentAt", ""), mine, m.get("typeLabel", ""),
                        (m.get("text") or "").replace("\n", " ")[:300],
                        c["客户"], c["客户ID"], ck, c["号"]])

    # 统计（按对方聚合）
    stat = defaultdict(lambda: {"条数": 0, "我方": 0, "对方": 0, "首次": "9999", "最近": "", "关键词": Counter()})
    for m in rows:
        key = (chats.get(m.get("chat_key") or "") or {}).get("客户") or "未知"
        s = stat[key]
        s["条数"] += 1
        s["我方" if m.get("mine") else "对方"] += 1
        t = m.get("sentAt") or ""
        if t:
            s["首次"] = min(s["首次"], t)
            s["最近"] = max(s["最近"], t)
        txt = m.get("text") or ""
        for k, kws in KW.items():
            if any(w in txt for w in kws):
                s["关键词"][k] += 1

    out = {}
    for k, v in stat.items():
        v["关键词"] = dict(v["关键词"])
        if v["首次"] == "9999":
            v["首次"] = ""
        out[k] = v
    STAT.write_text(json.dumps({"生成时间": time.strftime("%Y-%m-%d %H:%M"),
                                "消息数": len(rows), "对话对象数": len(out),
                                "按对象": dict(sorted(out.items(), key=lambda kv: -kv[1]["条数"])[:800])},
                               ensure_ascii=False, indent=1), encoding="utf-8")

    tot_me = sum(v["我方"] for v in out.values())
    tot_them = sum(v["对方"] for v in out.values())
    print("\n完成：%d 条消息，%d 个对话对象" % (len(rows), len(out)))
    print("  我方 %d 条 / 对方 %d 条（对方占比 %.0f%%）" % (tot_me, tot_them, tot_them / max(1, len(rows)) * 100))
    kw = Counter()
    for v in out.values():
        for k, n in v["关键词"].items():
            kw[k] += n
    print("  关键词：", dict(kw.most_common()))
    print("\n→", OUT.name, STAT.name)


if __name__ == "__main__":
    main()
