#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量抓「已购课程」＝近似的课程权限表

对每个客户读一次完整档案，把 events 里的订单事件抽出来，按「客户 × 课程」聚合。
买过某门课（且状态 PAID）＝有该课权限（到期时间接口里没有，只能按买过算）。

用法：
    python3 抓已购课程.py                 # 全量（续跑，已抓过的客户自动跳过）
    python3 抓已购课程.py --limit 200
    python3 抓已购课程.py --workers 6

产出：
    课程权限_已购.csv   客户编号 / 称呼 / 课程 / 首购日 / 最近付款日 / 实付元 / 订单数
    课程汇总_已购.csv   课程 / 人数 / 实付合计 / 最近一笔
"""
import argparse, csv, json, os, pathlib, sys, threading, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "用户整理工作台.html"
OUT = HERE / "课程权限_已购.csv"
SUM = HERE / "课程汇总_已购.csv"
STATE = HERE / "task_new.json"
BASE = "https://jiasujiaoyu.cn/api/workbuddy"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def token():
    p = pathlib.Path.home() / ".workbuddy_token"
    t = os.environ.get("WORKBUDDY_TOKEN") or (p.read_text().strip() if p.exists() else "")
    if not t:
        sys.exit("缺凭证")
    return t


TOK = token()
TASK = {}
if STATE.exists():
    try:
        TASK = json.loads(STATE.read_text())
    except ValueError:
        TASK = {}


class Limiter:
    def __init__(self, rate):
        self.rate = rate
        self.lock = threading.Lock()
        self.next = time.time()

    def wait(self):
        with self.lock:
            now = time.time()
            self.next = max(now, self.next) + 1.0 / self.rate
            gap = self.next - now
        if gap > 0:
            time.sleep(gap)


LIM = Limiter(6.0)
FAILED = []


def get(path):
    LIM.wait()
    headers = {"Authorization": "Bearer " + TOK, "Accept": "application/json", "User-Agent": UA}
    if TASK.get("task_id"):
        headers["X-WorkBuddy-Task-ID"] = TASK["task_id"]
        headers["X-WorkBuddy-Task-Purpose"] = TASK.get("task_purpose", "other")
    req = urllib.request.Request(BASE + path, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60
                try:
                    wait = int(json.loads(e.read().decode()).get("retry_after_seconds") or 60)
                except Exception:
                    pass
                print("  429，等 %d 秒" % wait, flush=True)
                time.sleep(min(wait, 120))
                continue
            return None
        except Exception:
            time.sleep(1.5)
    return None


def customers():
    h = PAGE.read_text(encoding="utf-8")
    i = h.index("const D = ") + 10
    j = h.index(";\nconst M = D.meta")
    return [(c["id"], c["name"]) for c in json.loads(h[i:j])["customers"]]


def done():
    if not OUT.exists():
        return set()
    with OUT.open(encoding="utf-8-sig") as f:
        return {r["客户编号"] for r in csv.DictReader(f) if r.get("客户编号")}


def orders_of(prof):
    j = (prof or {}).get("旅程") or {}
    out = []
    for e in (j.get("events") or []):
        if (e.get("type") or "") != "order":
            continue
        st = (e.get("status") or "").upper()
        if st and st not in ("PAID", "SUCCESS", "COMPLETED"):
            continue
        ex = e.get("extra") or {}
        name = (ex.get("原商品名") or e.get("title") or "").strip()
        if not name:
            continue
        out.append({
            "课程": name,
            "日": (e.get("date") or "")[:10],
            "元": round((e.get("amountCents") or 0) / 100, 2),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    all_c = customers()
    skip = done()
    todo = [(i, n) for i, n in all_c if str(i) not in skip]
    if a.limit:
        todo = todo[:a.limit]
    print("客户 %d 个，已抓 %d，本次 %d 个（%.0f 分钟）" % (len(all_c), len(skip), len(todo), len(todo) / 6 / 60))

    lock = threading.Lock()
    new = not OUT.exists()
    fd = OUT.open("a", encoding="utf-8-sig" if new else "utf-8", newline="")
    w = csv.writer(fd)
    if new:
        w.writerow(["客户编号", "称呼", "课程", "首购日", "最近付款日", "实付元", "订单数"])

    counter = {"n": 0, "rows": 0}
    t0 = time.time()
    q = list(todo)
    ql = threading.Lock()

    def worker():
        while True:
            with ql:
                if not q:
                    return
                cid, name = q.pop(0)
            prof = get("/customer/%d/profile" % cid)
            if prof is None:
                with lock:
                    FAILED.append(cid)
                continue
            agg = defaultdict(lambda: {"first": "9999", "last": "", "amt": 0.0, "n": 0})
            for o in orders_of(prof):
                k = agg[o["课程"]]
                k["first"] = min(k["first"], o["日"] or "9999")
                k["last"] = max(k["last"], o["日"])
                k["amt"] += o["元"]
                k["n"] += 1
            with lock:
                for course, v in agg.items():
                    w.writerow([cid, name, course, v["first"] if v["first"] != "9999" else "",
                                v["last"], round(v["amt"], 2), v["n"]])
                    counter["rows"] += 1
                counter["n"] += 1
                if counter["n"] % 100 == 0:
                    fd.flush()
                    el = time.time() - t0
                    print("  %d/%d · %d 行 · %.0f 秒 · 还剩 %.0f 分钟"
                          % (counter["n"], len(todo), counter["rows"], el,
                             (len(todo) - counter["n"]) / (counter["n"] / el) / 60), flush=True)

    ths = [threading.Thread(target=worker) for _ in range(a.workers)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    fd.close()

    # 汇总
    agg = defaultdict(lambda: {"人": set(), "amt": 0.0, "last": ""})
    with OUT.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            c = r["课程"]
            agg[c]["人"].add(r["客户编号"])
            agg[c]["amt"] += float(r["实付元"] or 0)
            agg[c]["last"] = max(agg[c]["last"], r["最近付款日"] or "")
    with SUM.open("w", encoding="utf-8-sig", newline="") as f:
        w2 = csv.writer(f)
        w2.writerow(["课程", "人数", "实付合计元", "最近一笔"])
        for c, v in sorted(agg.items(), key=lambda kv: -len(kv[1]["人"])):
            w2.writerow([c, len(v["人"]), round(v["amt"]), v["last"]])

    print("\n完成：%d 个客户，%d 行；失败 %d 个" % (counter["n"], counter["rows"], len(FAILED)))
    print("明细 %s\n汇总 %s" % (OUT.name, SUM.name))
    print("\n人最多的 15 门课：")
    for c, v in sorted(agg.items(), key=lambda kv: -len(kv[1]["人"]))[:15]:
        print("  %-46s %5d 人" % (c[:46], len(v["人"])))


if __name__ == "__main__":
    main()
