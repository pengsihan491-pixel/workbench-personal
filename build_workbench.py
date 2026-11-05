#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户整理工作台 · 数据构建器

从加速 CRM 取数 -> 打分层 -> 生成单文件 HTML 工作台（数据内嵌，双击即用）。

用法:
    export WORKBUDDY_TOKEN=...          # 凭证只走环境变量
    python3 build_workbench.py          # 用缓存，快速重建页面
    python3 build_workbench.py --refresh  # 重新取数再构建

口径: 私域范围（跟进人=本人）含「当下好友」与「已被删除」。不取客户手机号。
"""
import json, os, re, subprocess, sys, pathlib, datetime, statistics
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "cache"
HELPER = HERE / "workbuddy-client.py"
STATE = HERE / "task_wb_v1.json"
OUT = HERE / "用户整理工作台.html"
TODAY = datetime.date.today()
REFRESH = "--refresh" in sys.argv


def _ensure_task_state():
    """每次构建前重建任务状态（凭证换了也不会卡住）"""
    env = dict(os.environ)
    if not env.get("WORKBUDDY_TOKEN"):
        return
    try:
        if STATE.exists():
            STATE.unlink()
        subprocess.run([sys.executable, str(HELPER), "--state", str(STATE), "begin",
                        "private_customer_review"], capture_output=True, text=True, env=env, timeout=90)
    except Exception:
        pass


_ensure_task_state()

sys.path.insert(0, str(HERE))
try:
    from wb_token import ensure_token
    ensure_token()
except SystemExit:
    raise
except Exception:
    pass


def _call(path):
    env = dict(os.environ)
    if not env.get("WORKBUDDY_TOKEN"):
        sys.exit("缺少凭证：设置 WORKBUDDY_TOKEN，或运行 python3 wb_token.py 保存一次")
    p = subprocess.run([sys.executable, str(HELPER), "--state", str(STATE), "get", path],
                       capture_output=True, text=True, env=env)
    raw = p.stdout.strip()
    if not raw:
        sys.exit("接口无输出: %s / %s" % (path, p.stderr[:200]))
    d = json.loads(raw)
    if d.get("ok") is False:
        sys.exit("接口报错 %s: %s" % (path, json.dumps(d, ensure_ascii=False)[:300]))
    return d


def fetch(path, key, max_pages=80):
    """整份取回（按 next_page 翻页），带本地缓存。"""
    f = CACHE / (key + ".json")
    if f.exists() and not REFRESH:
        return json.load(f.open(encoding="utf-8"))
    rows, page, seen, meta = [], 1, set(), {}
    for _ in range(max_pages):
        sep = "&" if "?" in path else "?"
        d = _call("%s%spage=%d" % (path, sep, page))
        meta = d
        got = d.get("list") or d.get("items") or []
        for r in got:
            cid = r.get("客户编号")
            if cid is None:
                rows.append(r)
                continue
            sig = json.dumps([cid, r.get("订单号"), r.get("付款时间"), r.get("推key")], ensure_ascii=False, sort_keys=True)
            if sig in seen:
                continue
            seen.add(sig)
            rows.append(r)
        nxt = d.get("next_page")
        has_more = d.get("has_more")
        if has_more is False or not got:
            break
        if has_more is None:
            size = d.get("pageSize") or len(got)
            total = d.get("total") or 0
            if not size or page * size >= total:
                break
        page = nxt if isinstance(nxt, int) and nxt > page else page + 1
    out = {"rows": rows, "meta": {k: v for k, v in meta.items() if k not in ("list", "items")}}
    CACHE.mkdir(exist_ok=True)
    json.dump(out, f.open("w", encoding="utf-8"), ensure_ascii=False)
    return out


# ---------------------------------------------------------------- 取数
print("取数中…")
roster = fetch("/my-customers?page_size=100", "roster")
due = fetch("/my-customers/due?ahead=7&page_size=100", "due")
unpaid = fetch("/my-customers/unpaid-orders?days=30&page_size=100", "unpaid")
learn = fetch("/my-customers/learning?days=14&page_size=100", "learning")
learn30 = fetch("/my-customers/learning?days=30&page_size=100", "learning30")
fus = fetch("/my-customers/followups?page_size=100&per_customer=10", "fus")
learn2 = fetch("/my-customers/learning?days=2&page_size=100", "learning2")
unpaid2 = fetch("/my-customers/unpaid-orders?days=2&page_size=100", "unpaid2")
unpaid14 = fetch("/my-customers/unpaid-orders?days=14&page_size=100&include_paid_later=1", "unpaid14")
paid30 = fetch("/my-customers/paid-orders?days=30&page_size=100", "paid30")
opps = fetch("/my-customers/opportunities?days=90&page_size=100", "opps")
signups = fetch("/my-customers/signups?days=30&page_size=100", "signups")
calls = fetch("/my-customers/calls?days=14&page_size=100", "calls")
acts = fetch("/activities/upcoming?days=60&page_size=100", "acts")
mats = fetch("/materials?q=%E8%B4%A2%E7%BB%8F&page_size=8", "materials")

# ---------------------------------------------------------------- 归并信号
unpaid_by = defaultdict(list)
for r in unpaid["rows"]:
    unpaid_by[r["客户编号"]].append(r)
learn_by = {r["客户编号"]: r for r in learn["rows"]}
opp_by = defaultdict(list)
for r in opps["rows"]:
    opp_by[r["客户编号"]].append(r)
paid_by = defaultdict(lambda: {"n": 0, "amt": 0.0, "last": None})
for r in paid30["rows"]:
    cid = r["客户编号"]
    paid_by[cid]["n"] += 1
    paid_by[cid]["amt"] += float(r.get("金额元") or 0)
    t = r.get("付款时间")
    if t and (paid_by[cid]["last"] is None or t > paid_by[cid]["last"]):
        paid_by[cid]["last"] = t
signup_by = defaultdict(list)
for r in signups["rows"]:
    signup_by[r["客户编号"]].append(r)
call_by = defaultdict(list)
for r in calls["rows"]:
    call_by[r["客户编号"]].append(r)
due_by = {r["客户编号"]: r for r in due["rows"]}
learn30_by = {r["客户编号"]: r for r in learn30["rows"]}
fu_by = {r["客户编号"]: (r.get("最近跟进") or []) for r in fus["rows"]}

# 课程主题分类：行情脉冲 / 体系学习 / 线下高认同
HANGQING = ("行情", "半月谈", "相约古吧", "黄金坑", "热点", "盘面", "策略", "宏观", "加息", "股海", "市场走向", "复盘", "A股", "美股")
TIXI = ("训练营", "私域", "专栏", "赠课", "系统", "实战", "方法论", "读书", "音频", "视频课")
OFFLINE = ("游学", "研修", "沙龙", "参访", "论坛", "线下", "香港", "峰会")


CAL_FILE = HERE / "课程直播日期.csv"
DATE_PATTERNS = [
    (re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"), "ymd4"),
    (re.compile(r"(?<!\d)(\d{4})/(\d{1,2})/(\d{1,2})"), "ymd4"),
    (re.compile(r"(?<!\d)(\d{2})/(\d{1,2})/(\d{1,2})"), "ymd2"),
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?![\.\d])"), "md"),
    (re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日"), "md"),
]


def parse_course_date(name):
    n = name or ""
    for pat, kind in DATE_PATTERNS:
        m = pat.search(n)
        if not m:
            continue
        try:
            if kind == "ymd4":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "ymd2":
                y, mo, d = 2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                y, mo, d = TODAY.year, int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 2023 <= y <= TODAY.year + 1:
                return datetime.date(y, mo, d)
        except ValueError:
            continue
    return None


def load_calendar():
    """课程直播日期.csv：课程名,直播日期。有就用它，没有就退回课程名里的日期。"""
    cal = {}
    if CAL_FILE.exists():
        import csv
        with CAL_FILE.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                name = (row.get("课程名") or "").strip()
                raw = (row.get("直播日期") or "").strip()
                if not name or not raw:
                    continue
                try:
                    cal[name] = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
    if CAL_FILE.exists():
        import csv as _csv
        rows = list(_csv.DictReader(CAL_FILE.open(encoding="utf-8-sig")))
        filled = 0
        for row in rows:
            nm = (row.get("课程名") or "").strip()
            if not nm:
                continue
            if not (row.get("直播日期") or "").strip():
                cd = parse_course_date(nm)
                if cd:
                    row["直播日期"] = cd.isoformat()
                    row["备注"] = row.get("备注") or "自动推断"
                    cal[nm] = cd
                    filled += 1
        if filled:
            with CAL_FILE.open("w", encoding="utf-8-sig", newline="") as f:
                w = _csv.DictWriter(f, fieldnames=["课程名", "直播日期", "备注"])
                w.writeheader()
                w.writerows(rows)
            print("课程日历补齐 %d 门" % filled)
    return cal


CALENDAR = load_calendar()


def course_date_of(name):
    return CALENDAR.get(name) or parse_course_date(name)


def topic_of(name, kind):
    """按内容类型判：直播＝跟场次（行情驱动），专栏/音频/视频/电子书＝课程内容（内容驱动）。"""
    n = name or ""
    if any(k in n for k in OFFLINE):
        return "offline"
    if kind == "直播":
        return "hangqing"
    return "tixi"


# 沟通内容里的立场词
WAIT_WORDS = ("等行情", "行情不好", "观望", "再看看", "没钱", "手头紧", "忙", "考虑中", "考虑一下", "以后再说", "跌", "亏", "套住", "不着急", "暂不")
TRUST_WORDS = ("老师", "认可", "想学", "报名", "续费", "复购", "介绍朋友", "推荐", "游学", "研修营", "训练营", "报名了", "已交", "余款", "感兴趣", "相信")


def tags_of(text):
    t = text or ""
    return sum(1 for w in WAIT_WORDS if w in t), sum(1 for w in TRUST_WORDS if w in t)

L_LABEL = {5: "L5 深度学习", 4: "L4 稳定学习", 3: "L3 有感学习", 2: "L2 浅尝", 1: "L1 未触达"}
G_LABEL = {5: "G5 高频深聊", 4: "G4 正常维护", 3: "G3 冷却中", 2: "G2 冰封", 1: "G1 无记录"}
R_LABEL = {5: "R5 深度黏着", 4: "R4 稳定互动", 3: "R3 双向起步", 2: "R2 单向接触", 1: "R1 零接触"}
C_LABEL = {5: "C5 顶客 1万+", 4: "C4 高价值 5千+", 3: "C3 中客单 2680+", 2: "C2 小客单", 1: "C1 未付费"}
QUAD_NOTE = {
    "核心维护": "认人不认行情：不看大盘也在学、也在聊——行情差照样有转化可能",
    "行情敏感": "认 IP 但也盯行情：行情一来就是大单，平时要保温别断联",
    "行情型": "只在行情热的时候冒头：平时不学不理，等行情再触达",
    "沉默资产": "付过 2680 以上，但近 30 天不学、长期不聊——留存风险最大的一批",
    "未激活": "消费低、也没信号，先靠内容和活动批量碰",
}


def add_part(state, v, why):
    """state = [总分, 明细列表]；嵌套函数在模块级 for 里用不了 nonlocal。"""
    if v:
        state[0] += v
        state[1].append([why, v])


def learn_level(days, minutes, kinds):
    if days >= 8 or (days >= 5 and minutes >= 300):
        return 5
    if days >= 4 or minutes >= 180:
        return 4
    if days >= 2:
        return 3
    if days >= 1:
        return 2
    return 1


def comm_level(fu_list, fu_days, has_call):
    recent = 0
    for f in fu_list:
        d = days_since(f.get("时间"))
        if d is not None and d <= 30:
            recent += 1
    if fu_days is None and not has_call:
        return 1
    if recent >= 3 or (has_call and fu_days is not None and fu_days <= 7):
        return 5
    if recent >= 1:
        return 4
    if fu_days is not None and fu_days <= 90:
        return 3
    return 2


def spend_level(spend):
    if spend >= 10000:
        return 5
    if spend >= 5000:
        return 4
    if spend >= 2680:
        return 3
    if spend > 0:
        return 2
    return 1


# ---------------------------------------------------------------- 企微标签
TAG_FILE = HERE / "企微标签_明细.csv"


def load_tags():
    """客户编号 → 半月谈相关标签（去重）。来自 抓企微标签.py 的输出。"""
    if not TAG_FILE.exists():
        return {}, {}
    import csv as _csv
    per, cnt, seen = {}, {}, set()
    with TAG_FILE.open(encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            cid = (r.get("客户编号") or "").strip()
            tag = (r.get("标签") or "").strip()
            if not cid.isdigit() or not tag:
                continue
            k = (int(cid), tag)
            if k in seen:
                continue
            seen.add(k)
            per.setdefault(int(cid), []).append(tag)
            cnt[tag] = cnt.get(tag, 0) + 1
    return per, cnt


TAGS, TAG_CNT = load_tags()

HV_FILE = HERE / "高客单分类.csv"


def load_hv():
    """高客单分类（16800+ 订单）：客户编号 → {分层, 品类[], 大额总额, 最近}"""
    if not HV_FILE.exists():
        return {}
    import csv as _csv
    out = {}
    with HV_FILE.open(encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            cid = (r.get("客户编号") or "").strip()
            if not cid.isdigit():
                continue
            cats = [c.strip() for c in (r.get("品类") or "").split("/") if c.strip() and c.strip() not in ("—", "未归类")]
            out[int(cid)] = {
                "tier": (r.get("分层") or "").split("·")[0].strip(),
                "tierFull": (r.get("分层") or "").strip(),
                "cats": cats,
                "amt": int(float(r.get("大额总额") or 0)),
                "last": (r.get("最近大额日期") or "").strip(),
                "n": int(float(r.get("大额订单数") or 0)),
            }
    return out


HV = load_hv()

# 课程价格下限：CRM 的「累计消费」没同步公域订单，用它补下限
# (关键词, 价格, 生效起始日 or None)  多条按顺序匹配，先命中先用
PRICE_FLOOR = [
    ("古今谈", 29800, None),
    ("实战营", 21800, None),
    ("游学", 88000, None),
    ("EMBA", 148000, None),
    ("诺曼底", 148000, None),
    ("香港珠海", 150000, None),
    ("内参圈", 9800, None),
    ("面对面", 3980, None),
    ("2天线下", 3980, None),
    ("线下闭门讲座", 3980, None),
    ("香港保险", 3980, None),
    ("资产配置", 3980, None),
    ("半月谈", 2980, "2026-03-01"),
    ("半月谈", 2680, None),
]
# 这些字样不是真课程购买（直播/课件/说明会），不能套价格
NON_PAID = ["明灯", "公开课", "体验", "试听", "说明会", "资料", "课件", "领取", "回放", "答疑", "试看"]


def floor_of(course, first_day=""):
    """一门课的价格下限；免费/直播/说明会类不计价"""
    name = course or ""
    if any(b in name for b in NON_PAID):
        return 0
    for kw, price, since in PRICE_FLOOR:
        if kw in name:
            if since and (first_day or "") < since:
                continue
            return price
    return 0


def load_purchases():
    """读 课程权限_已购.csv → {客户编号: [{课程, 首购日, 最近付款日, 实付}]}"""
    import csv as _csv
    from collections import Counter as _C
    f = HERE / "课程权限_已购.csv"
    purch, cnt = {}, _C()
    if not f.exists():
        return purch, cnt
    with f.open(encoding="utf-8-sig") as fh:
        for r in _csv.DictReader(fh):
            try:
                cid = int(r.get("客户编号") or 0)
            except ValueError:
                continue
            name = (r.get("课程") or "").strip()
            if not cid or not name:
                continue
            try:
                amt = float(r.get("实付元") or 0)
            except ValueError:
                amt = 0.0
            purch.setdefault(cid, []).append({
                "c": name,
                "first": (r.get("首购日") or "")[:10],
                "last": (r.get("最近付款日") or "")[:10],
                "amt": amt,
            })
            cnt[name] += 1
    return purch, cnt


PURCH, PC_CNT = load_purchases()


def build_spend_est():
    """推算消费：取 max(后台累计消费, 各课程价格下限之和)"""
    est = {}
    for cid, lst in PURCH.items():
        floors = set()
        for p2 in lst:
            f = floor_of(p2.get("c") or "", p2.get("first") or "")
            if f:
                floors.add(f)
        est[cid] = {"floor": sum(floors)}
    return est


SPEND_EST = build_spend_est()

# 对公转账：银行流水导入的额外消费，直接累加
WIRE_FILE = HERE / "对公转账_汇总.json"
WIRE = json.loads(WIRE_FILE.read_text(encoding="utf-8")) if WIRE_FILE.exists() else {}
WIRE_BY = {int(k): v for k, v in (WIRE.get("按客户") or {}).items()}

TC_FILE = HERE / "讲师分类_金岩石向松祚.csv"


def load_teachers():
    """讲师分类：客户编号 → {分类, 金岩石门数, 向松祚门数, 合计实付, 最近付款}"""
    if not TC_FILE.exists():
        return {}
    import csv as _csv
    out = {}
    with TC_FILE.open(encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            cid = (r.get("客户编号") or "").strip()
            if not cid.isdigit():
                continue
            out[int(cid)] = {
                "cls": (r.get("分类") or "").strip(),
                "jr": int(float(r.get("金岩石课程数") or 0)),
                "xs": int(float(r.get("向松祚课程数") or 0)),
                "amt": int(float(r.get("合计实付") or 0)),
                "last": (r.get("最近付款") or "").strip(),
            }
    return out


TEACH = load_teachers()

MARKET_FILE = HERE / "行情最新.json"
MARKET = json.loads(MARKET_FILE.read_text(encoding="utf-8")) if MARKET_FILE.exists() else None

STAGE_CN = {"IN_STUDY": "在读", "GRADUATED": "已毕业", "PAID_IDLE": "付过费未活跃", "PROSPECT": "未付费潜在"}
STAGE_ORDER = ["在读", "已毕业", "付过费未活跃", "未付费潜在", "未知"]


def tier_of(spend):
    if spend >= 10000:
        return "顶客"
    if spend >= 5000:
        return "高价值"
    if spend >= 2680:
        return "中客单"
    if spend > 0:
        return "小客单"
    return "未付费"


def days_since(ts):
    if not ts:
        return None
    try:
        d = datetime.datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (TODAY - d).days


# ---------------------------------------------------------------- 逐客户打分
rows = []
for r in roster["rows"]:
    cid = r["客户编号"]
    spend_backend = float(r.get("累计消费元") or 0)
    _est = SPEND_EST.get(cid) or {}
    # 后台没同步公域订单：用已购课程的价格下限兜底
    # 后台有数就信后台；后台为 0 才用课程下限补（避免重复放大）
    spend = spend_backend if spend_backend > 0 else _est.get("floor", 0)
    wire = (WIRE_BY.get(cid) or {}).get("金额", 0)
    if wire:
        spend = spend + wire
    orders = int(r.get("订单数") or 0)
    intent = int(r.get("意向评分") or 0)
    stage = STAGE_CN.get(r.get("学员阶段") or "", "未知")
    friend = r.get("私域好友状态") or ""
    deleted = friend == "已被删除"
    fu = r.get("最近跟进时间")
    fu_days = days_since(fu)
    drop = r.get("掉公倒计时小时")
    up = unpaid_by.get(cid, [])
    ln = learn_by.get(cid)
    op = opp_by.get(cid, [])
    pd = paid_by.get(cid) or {"n": 0, "amt": 0.0, "last": None}
    sg = signup_by.get(cid, [])
    cl = call_by.get(cid, [])
    du = due_by.get(cid)

    # 优先级打分（0-100），每一项都可在页面上摊开看
    parts = []
    s = intent * 0.45
    parts.append(["意向评分 %d" % intent, round(intent * 0.45, 1)])
    if up:
        s += 22
        parts.append(["下单未付款 %d 笔" % len(up), 22])
    if ln:
        v = 14
        s += v
        parts.append(["近 14 天有学习（%d 天/%d 分钟）" % (ln.get("看了几天") or 0, ln.get("总时长分钟") or 0), v])
    if op:
        v = 10
        s += v
        parts.append(["有商机 %d 条" % len(op), v])
    if pd["n"]:
        s += 10
        parts.append(["近 30 天付过款 %d 笔" % pd["n"], 10])
    if sg:
        s += 6
        parts.append(["报名活动", 6])
    if isinstance(drop, (int, float)):
        v = 16 if drop <= 72 else (8 if drop <= 168 else 0)
        if v:
            s += v
            parts.append(["掉公倒计时 %d 小时" % drop, v])
    if du:
        v = min(12, max(2, round((du.get("逾期天数") or 0) / 10)))
        s += v
        parts.append(["跟进逾期 %d 天" % (du.get("逾期天数") or 0), v])
    tb = {"顶客": 8, "高价值": 6, "中客单": 4}.get(tier_of(spend), 0)
    if tb:
        s += tb
        parts.append(["客单层 %s" % tier_of(spend), tb])
    if deleted:
        s -= 15
        parts.append(["已被删好友", -15])
    score = int(max(0, min(100, round(s))))

    # 分桶（顺序即优先级）
    du_over = bool(du) and (du.get("逾期天数") or 0) > 0
    if up or (isinstance(drop, (int, float)) and drop <= 72) or (du_over and intent >= 50):
        bucket = "即刻打"
    elif stage in ("在读", "已毕业") and spend >= 2680 and (pd["n"] or intent >= 65 or op):
        bucket = "复购升单"
    elif stage == "在读":
        bucket = "在读保温"
    elif spend > 0 and (fu_days is None or fu_days > 60) and not ln:
        bucket = "沉默唤醒"
    elif spend == 0:
        bucket = "待转化"
    else:
        bucket = "低优先"
    if deleted and bucket not in ("即刻打",) and not up and not (isinstance(drop, (int, float)) and drop <= 72):
        if spend == 0 or (fu_days is not None and fu_days > 90):
            bucket = "低优先"

    # 下一步动作
    if up:
        act = "催付：%s（%s 元）" % (up[0].get("商品", "")[:18], up[0].get("金额元"))
    elif isinstance(drop, (int, float)) and drop <= 72:
        act = "掉公倒计时 %d 小时，先发一条私聊把她拉住" % drop
    elif du_over:
        act = "跟进已逾期 %d 天，今天补一条跟进" % (du.get("逾期天数") or 0)
    elif du:
        act = "约在 %s 跟进，别拖过当天" % (du.get("约的下次跟进日期") or "本周")
    elif not pd["n"] and op:
        act = "推进商机：%s（%s）" % (op[0].get("名称", "")[:14], op[0].get("阶段", ""))
    elif stage == "已毕业" and spend >= 2680:
        act = "推进阶：研修营 / 游学"
    elif ln and stage == "在读":
        act = "学习关怀：已看 %d 天，聊进度卡点" % (ln.get("看了几天") or 0)
    elif deleted:
        act = "已被删好友，走短信或重新加好友"
    elif fu_days is None:
        act = "从无跟进记录，先做一次破冰"
    elif fu_days > 60:
        act = "沉默 %d 天，用行情内容重新唤起" % fu_days
    else:
        act = "保持节奏，下次跟进前补一条学习反馈"

    # ---- 三层分层
    l30 = learn30_by.get(cid)
    kinds = set()
    topic_n = {"hangqing": 0, "tixi": 0, "offline": 0}
    live_min = replay_min = undated_min = content_min = 0.0
    undated_names = {}
    if l30:
        for x in (l30.get("明细") or []):
            kind = x.get("类型")
            if kind:
                kinds.add(kind)
            mins = float(x.get("分钟") or 0)
            watch_day = days_since(x.get("日期"))
            nm = x.get("名称") or ""
            cd = course_date_of(nm)
            if kind != "直播":
                content_min += mins
            if cd is None:
                undated_min += mins
                if kind == "直播":
                    undated_names[nm] = undated_names.get(nm, 0) + mins
            else:
                watch_date = datetime.date.today() - datetime.timedelta(days=watch_day or 0)
                if watch_date == cd:
                    live_min += mins
                elif watch_date > cd:
                    replay_min += mins
                else:
                    undated_min += mins
            topic_n[topic_of(nm, kind)] += mins
    lu = learn_level(l30.get("看了几天") or 0 if l30 else 0,
                     l30.get("总时长分钟") or 0 if l30 else 0, kinds)
    fu_list = fu_by.get(cid) or []
    gu = comm_level(fu_list, fu_days, bool(cl))
    cu = spend_level(spend)
    fu_text = " / ".join([(f.get("内容") or "") for f in fu_list[:3]])[:120]
    wait_hits, trust_hits = 0, 0
    for f in fu_list:
        w, t = tags_of(f.get("内容"))
        wait_hits += w
        trust_hits += t
    topic_total = sum(topic_n.values()) or 1
    hq_share = topic_n["hangqing"] / topic_total if l30 else 0
    tixi_share = topic_n["tixi"] / topic_total if l30 else 0

    # ---- 关系深度层 R1–R5：只看「内容投入」和「沟通深度」，不看花了多少钱
    st = [0.0, []]
    add_part(st, min(45, round(content_min * 0.5)), "课程内容（专栏/音频/视频）%d 分钟" % round(content_min))
    add_part(st, min(20, round((l30.get("看了几天") or 0) * 2) if l30 else 0), "近 30 天学习 %d 天" % (l30.get("看了几天") or 0 if l30 else 0))
    add_part(st, gu * 5, "沟通层 %s" % G_LABEL[gu])
    add_part(st, min(15, trust_hits * 3), "跟进里出现认可/想学 %d 次" % trust_hits)
    add_part(st, min(9, len(cl) * 3), "近 14 天通话 %d 通" % len(cl))
    stick = int(max(0, min(100, round(st[0]))))
    if stick >= 55:
        ru = 5
    elif stick >= 40:
        ru = 4
    elif stick >= 25:
        ru = 3
    elif stick >= 10:
        ru = 2
    else:
        ru = 1

    # ---- 行情依赖分（越高＝越要靠行情才动）
    mo = [0.0, []]
    if l30 and hq_share >= 0.85:
        add_part(mo, 24, "观看时长 %d%% 都在直播（跟场次）" % round(hq_share * 100))
    elif l30 and hq_share >= 0.6:
        add_part(mo, 12, "观看时长 %.0f%% 在直播（跟场次）" % (hq_share * 100))
    if pd["n"] and (l30 is None or (l30.get("看了几天") or 0) <= 2):
        add_part(mo, 18, "近 30 天付过款但几乎不学习")
    if wait_hits:
        add_part(mo, min(20, wait_hits * 7), "沟通里出现「等行情/观望/没钱」%d 次" % wait_hits)
    if fu_days is None or fu_days > 90:
        add_part(mo, 12, "平时不联系（%s）" % ("从无跟进" if fu_days is None else "%d 天没跟进" % fu_days))
    if 0 < spend < 2680:
        add_part(mo, 10, "只买过低于 2680 的课")
    if not sg and not op:
        add_part(mo, 6, "没有活动报名 / 商机")
    if len(kinds) >= 3:
        add_part(mo, -10, "跨 %d 类内容学习" % len(kinds))
    if trust_hits:
        add_part(mo, -min(15, trust_hits * 5), "沟通里出现「认可/想学/报名」%d 次" % trust_hits)
    if op or sg:
        add_part(mo, -12, "有商机 / 线下活动参与")
    if l30 and (l30.get("看了几天") or 0) >= 8:
        add_part(mo, -10, "近 30 天学习 %d 天" % (l30.get("看了几天") or 0))
    market = int(max(0, min(100, round(mo[0]))))

    # ---- IP 信任分（越高＝越认人和课，越不靠行情）
    tr = [0.0, []]
    if spend >= 10000:
        add_part(tr, 20, "累计消费 1 万以上")
    elif spend >= 5000:
        add_part(tr, 15, "累计消费 5000 以上")
    elif spend >= 2680:
        add_part(tr, 9, "累计消费 2680 以上")
    if orders >= 10:
        add_part(tr, 12, "下单 %d 笔" % orders)
    elif orders >= 4:
        add_part(tr, 7, "下单 %d 笔" % orders)
    if l30 and (l30.get("看了几天") or 0) >= 5:
        add_part(tr, 12, "近 30 天学习 %d 天" % (l30.get("看了几天") or 0))
    if tixi_share >= 0.3:
        add_part(tr, 10, "%.0f%% 的时长在看课程内容（非直播）" % (tixi_share * 100))
    if len(kinds) >= 3:
        add_part(tr, 6, "跨 %d 类内容（直播/视频/专栏/音频）" % len(kinds))
    if trust_hits:
        add_part(tr, min(18, trust_hits * 6), "沟通里出现「认可/想学/报名」%d 次" % trust_hits)
    if op:
        add_part(tr, 12, "有商机（%s）" % (op[0].get("名称") or "")[:10])
    if sg:
        add_part(tr, 8, "报名过活动")
    if cl:
        add_part(tr, 8, "近 14 天有通话纪要")
    if gu >= 4:
        add_part(tr, 8, "沟通层 %s" % G_LABEL[gu])
    if wait_hits:
        add_part(tr, -min(12, wait_hits * 4), "沟通里出现观望类表述 %d 次" % wait_hits)
    trust = int(max(0, min(100, round(tr[0]))))

    if trust >= 45:
        quad = "核心维护" if market < 45 else "行情敏感"
    elif market >= 45:
        quad = "行情型"
    elif spend >= 2680:
        quad = "沉默资产"
    else:
        quad = "未激活"

    rows.append({
        "id": cid, "name": r.get("称呼") or "（未命名）", "stage": stage,
        "intent": intent, "orders": orders, "spend": round(spend, 2),
        "tier": tier_of(spend), "pool": r.get("所在公海池") or "—",
        "source": r.get("获客来源") or "—", "friend": friend, "deleted": deleted,
        "del": r.get("删好友原因") or "", "fu": fu or "", "fuDays": fu_days,
        "drop": drop if isinstance(drop, (int, float)) else None,
        "owner": r.get("招生跟进人") or "",
        "learn": ({"d": ln.get("看了几天") or 0, "m": ln.get("总时长分钟") or 0,
                   "last": ln.get("最近一天"), "paid": bool(ln.get("之后付过款"))} if ln else None),
        "unpaid": [{"商品": u.get("商品"), "金额": u.get("金额元"), "状态": u.get("状态"),
                    "平台": u.get("平台"), "时间": u.get("下单时间")} for u in up],
        "opp": [{"名称": o.get("名称"), "阶段": o.get("阶段"), "金额": o.get("金额元"),
                 "预计": o.get("预计结单")} for o in op],
        "paid30": {"n": pd["n"], "amt": round(pd["amt"], 2), "last": pd["last"]},
        "due": ({"日期": du.get("约的下次跟进日期"), "逾期": du.get("逾期天数"),
                 "over": du_over, "上次": du.get("上次跟进内容")} if du else None),
        "signup": [s2.get("活动") for s2 in sg],
        "call": [{"时间": c.get("通话时间"), "秒": c.get("时长秒"), "纪要": c.get("通话纪要") or c.get("AI纪要")} for c in cl],
        "tags": TAGS.get(cid, []),
        "jr_n": (TEACH.get(cid) or {}).get("jr", 0),
        "hv": HV.get(cid),
        "tc": TEACH.get(cid),
        "pc": "|".join(p2["c"][:16] for p2 in PURCH.get(cid, [])[:14]),
        "pcLast": (PURCH.get(cid) or [{}])[0].get("last", "") if PURCH.get(cid) else "",
        "spendBackend": round(spend_backend),
        "wire": round(wire) if wire else 0,
        "score": score, "bucket": bucket, "action": act, "reason": parts,
        "L": lu, "Lt": L_LABEL[lu], "C": cu, "Ct": C_LABEL[cu], "G": gu, "Gt": G_LABEL[gu],
        "R": ru, "Rt": R_LABEL[ru], "stick": stick, "sparts": st[1],
        "liveMin": round(live_min), "replayMin": round(replay_min),
        "contentMin": round(content_min), "undatedMin": round(undated_min),
        "learn30": ({"d": l30.get("看了几天") or 0, "m": l30.get("总时长分钟") or 0,
                     "kinds": sorted(kinds), "hqMin": round(topic_n["hangqing"]),
                     "tixiMin": round(topic_n["tixi"]), "offMin": round(topic_n["offline"]),
                     "hqShare": round(hq_share * 100)} if l30 else None),
        "fuN": len(fu_list), "fuText": fu_text, "fuWait": wait_hits, "fuTrust": trust_hits,
        "fuGood": sum(1 for f0 in fu_list if len(str(f0.get("内容") or "").strip()) > 20),
        "market": market, "mparts": mo[1], "trust": trust, "tparts": tr[1],
        "quad": quad,
    })

# ---------------------------------------------------------------- 开课节点与复盘
SESS_FILE = HERE / "开课节点.csv"
PERM_FILE = HERE / "课程权限.csv"


def load_perms():
    """课程权限表（从小鹅通/后台导出后整理）：有权限且未过期＝还在这门课里。

    列：客户编号,称呼,课程,权限(有/无),到期日(可空),依据
    """
    if not PERM_FILE.exists():
        return {}
    import csv as _csv
    out = {}
    with PERM_FILE.open(encoding="utf-8-sig", newline="") as f:
        for r in _csv.DictReader(f):
            try:
                cid = int((r.get("客户编号") or "").strip())
            except ValueError:
                continue
            course = (r.get("课程") or "").strip()
            if not course:
                continue
            flag = (r.get("权限") or "").strip()
            if flag not in ("有", "无"):
                continue
            exp = (r.get("到期日") or "").strip()[:10]
            try:
                exp_d = datetime.datetime.strptime(exp, "%Y-%m-%d").date() if exp else None
            except ValueError:
                exp_d = None
            out[(cid, course)] = {"has": flag == "有", "exp": exp_d}
            out.setdefault((cid, "__any__"), {"has": False, "exp": None})
            if flag == "有":
                out[(cid, "__any__")]["has"] = True
    return out


PERMS = load_perms()


def perm_state(cid, kws):
    """返回 True（有权限且未过期）/ False（明确无）/ None（表里没这个人的记录）。"""
    if not PERMS:
        return None
    known = False
    ok = False
    for (c2, course), v in PERMS.items():
        if c2 != cid or course == "__any__":
            continue
        if any(k in course for k in kws):
            known = True
            if v["has"] and (not v["exp"] or v["exp"] >= TODAY):
                ok = True
    return ok if known else None


def load_sessions():
    """你每月维护这张表；关键词用 | 分隔，能写多个。"""
    if not SESS_FILE.exists():
        import csv as _csv
        seeds = [
            ["半月谈 五五", "五五", str(TODAY - datetime.timedelta(days=1)), str(TODAY - datetime.timedelta(days=1)), "30", "半月谈", "示例：续费＝又买了半月谈"],
            ["半月谈 五四", "五四", "2026-10-16", "2026-10-16", "30", "半月谈", "示例"],
            ["古今谈 十月", "古今谈】十月|古今谈十月", "2026-10-01", "2026-10-31", "30", "古今谈", "示例：整月专栏"],
            ["股海 9 期", "股海9|股海 9期", "2026-06-01", "2026-08-31", "30", "", "示例：训练营班期，请改成实际日期"],
        ]
        with SESS_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["期次", "匹配关键词", "开课日期", "结课日期", "续费窗口天数", "续费产品关键词（留空=买任何非本期课程都算）", "备注"])
            w.writerows(seeds)
        print("已生成开课节点表：%s（请按月编辑）" % SESS_FILE.name)
    import csv as _csv
    out = []
    with SESS_FILE.open(encoding="utf-8-sig", newline="") as f:
        for r in _csv.DictReader(f):
            name = (r.get("期次") or "").strip()
            kw = (r.get("匹配关键词") or "").strip()
            if not name or not kw:
                continue
            try:
                st = datetime.datetime.strptime((r.get("开课日期") or "").strip()[:10], "%Y-%m-%d").date()
                en = datetime.datetime.strptime((r.get("结课日期") or "").strip()[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            try:
                win = int((r.get("续费窗口天数") or "30").strip())
            except ValueError:
                win = 30
            renew_kw = [k.strip() for k in (r.get("续费产品关键词（留空=买任何非本期课程都算）") or r.get("续费产品关键词") or "").split("|") if k.strip()]
            out.append({"名": name, "kws": [k.strip() for k in kw.split("|") if k.strip()],
                        "start": st, "end": en, "win": win, "renewKws": renew_kw,
                        "备注": (r.get("备注") or "").strip()})
    return out


SERIES_HINT = [("半月谈", ["半月谈"]), ("相约古吧", ["古吧"]),
               ("古今谈", ["古今谈"]), ("股海", ["股海"]), ("金融班", ["金融"])]


def series_of(s0):
    """按关键词/期次名判断属于哪个系列。"""
    def _j(v):
        return " ".join(v) if isinstance(v, (list, tuple)) else str(v or "")
    blob = _j(s0.get("名")) + " " + _j(s0.get("kws")) + " " + _j(s0.get("renewKws"))
    for name, keys in SERIES_HINT:
        if any(k in blob for k in keys):
            return name
    return s0.get("名", "")[:4]


def make_person(row_by_id):
    def person(cid, mins=0):
        r = row_by_id.get(cid) or {}
        return {"id": cid, "name": r.get("name", ""), "分钟": round(mins),
                "Ct": r.get("Ct", ""), "spend": r.get("spend", 0), "quad": r.get("quad", ""),
                "fuDays": r.get("fuDays"), "action": r.get("action", "")}
    return person


def attach_series_compare(reports, sessions, row_by_id):
    """同系列按开课日排序，逐期对比：留存 / 流失 / 新增。"""
    by_series = {}
    for r in reports:
        by_series.setdefault(r["系列"], []).append(r)
    for name, items in by_series.items():
        items.sort(key=lambda r: r["开课"])
        for k, r in enumerate(items):
            cur = {c for c, _ in (r.get("新学员") or [])} | {c for c, _ in (r.get("老学员") or [])}
            if k == 0:
                r["上期"] = None
                continue
            prev = items[k - 1]
            prev_ids = {c for c, _ in (prev.get("新学员") or [])} | {c for c, _ in (prev.get("老学员") or [])}
            keep = cur & prev_ids
            lost = prev_ids - cur
            add = cur - prev_ids
            person = make_person(row_by_id)
            prev_min = dict(prev.get("新学员") or []) | dict(prev.get("老学员") or [])
            cur_min = dict(r.get("新学员") or []) | dict(r.get("老学员") or [])
            r["上期"] = {
                "名": prev["名"], "开课": prev["开课"], "到课": len(prev_ids),
                "留存": len(keep), "流失": len(lost), "新增": len(add),
                "留存率": round(len(keep) / len(prev_ids) * 100) if prev_ids else 0,
                "流失名单": sorted((person(c, prev_min.get(c, 0)) for c in lost), key=lambda x: -x["分钟"])[:80],
                "新增名单": sorted((person(c, cur_min.get(c, 0)) for c in add), key=lambda x: -x["spend"])[:80],
            }
    return reports


def build_reviews(sessions):
    row_by_id = {r["id"]: r for r in rows}
    name_by_id = {r["id"]: r["name"] for r in rows}
    # 每个客户最早买课日（买过就是老学员；学习明细只有 30 天，靠这个补齐）
    first_buy = {}
    for cid2, lst in PURCH.items():
        ds = [x.get("first") for x in lst if x.get("first")]
        if ds:
            first_buy[cid2] = min(ds)
    # 每个客户在 30 天窗口里的最早看课日（判断新老学员用）
    first_seen = {}
    for r2 in learn30["rows"]:
        cid2 = r2.get("客户编号")
        for x in (r2.get("明细") or []):
            d0 = days_since(x.get("日期"))
            if d0 is None:
                continue
            day = TODAY - datetime.timedelta(days=d0)
            if cid2 not in first_seen or day < first_seen[cid2]:
                first_seen[cid2] = day
    reports = []
    for s0 in sessions:
        kws = s0["kws"]
        hit = lambda t: any(k in (t or "") for k in kws)
        # 到课：学习明细里名称匹配、日期落在班期内
        learners, minutes = {}, {}
        for r2 in learn30["rows"]:
            cid2 = r2.get("客户编号")
            for x in (r2.get("明细") or []):
                if not hit(x.get("名称")):
                    continue
                d0 = days_since(x.get("日期"))
                if d0 is None:
                    continue
                day = TODAY - datetime.timedelta(days=d0)
                if not (s0["start"] <= day <= s0["end"]):
                    continue
                m0 = float(x.get("分钟") or 0)
                minutes[cid2] = minutes.get(cid2, 0) + m0
                learners[cid2] = True
        # 购买：本期商品
        buyers, paid_amt = {}, {}
        for o in paid30["rows"]:
            if not hit(o.get("商品")):
                continue
            d0 = days_since(o.get("付款时间"))
            if d0 is None or d0 > 60:
                continue
            day = TODAY - datetime.timedelta(days=d0)
            if not (s0["start"] <= day <= s0["end"] + datetime.timedelta(days=7)):
                continue
            cid2 = o.get("客户编号")
            buyers[cid2] = True
            paid_amt[cid2] = paid_amt.get(cid2, 0) + float(o.get("金额元") or 0)
        members = set(learners) | set(buyers)
        # 口径：相对「这个系列」
        #   老学员（续费）＝本期开课之前，买过同系列的任一课程（或同系列更早看过课）
        #   新学员        ＝第一次出现在这个系列
        # 学习明细只有 30 天，所以主要靠购买历史（含全部历史）判
        ser_kws = (s0.get("renewKws") or []) + [v for v in [series_of(s0)] if v]
        ser_kws = [k for k in dict.fromkeys(ser_kws) if k]

        # 通用 SKU：入口/充值/赠送类商品，不代表「以前来过某一期」
        GENERIC = ("短信发货", "续费", "赠送", "通用", "充值", "会员", "年卡", "季卡")

        def bought_earlier_issue(c):
            """买过同系列「别的期次」才算老学员。
            判法：同系列 + 不是本期 + 不是通用 SKU + 购买日早于本期开课。
            这样 11-01 买「半月谈(短信发货)」的新客不会被误判成老。"""
            for p2 in PURCH.get(c, []):
                name = p2.get("c") or ""
                if not any(k in name for k in ser_kws):
                    continue
                if any(k in name for k in kws):        # 本期自己的票
                    continue
                if any(g in name for g in GENERIC):    # 通用/充值 SKU
                    continue
                if (p2.get("first") or "9999-99-99") < str(s0["start"]):
                    return True
            return False

        def is_new(c):
            if bought_earlier_issue(c):
                return False
            # 保底：同系列更早看过课也算老
            fs = first_seen.get(c)
            return not (fs is not None and fs < s0["start"])
        fresh_ids = [c for c in learners if is_new(c)]
        old_set = set(learners) - set(fresh_ids)
        old_ids = [c for c in learners if c in old_set]

        # 本期新客（含买了课但没看课的人）：第一次买同系列、且购买落在本期前后 7 天
        win0 = s0["start"] - datetime.timedelta(days=7)
        win1 = s0["end"] + datetime.timedelta(days=7)
        new_buyers = []
        for cid2, lst in PURCH.items():
            series = [p2 for p2 in lst if any(k in (p2.get("c") or "") for k in ser_kws)]
            if not series:
                continue
            earlier = [p2 for p2 in series if any(g not in (p2.get("c") or "") for g in [""])
                       and not any(k in (p2.get("c") or "") for k in kws)
                       and not any(g in (p2.get("c") or "") for g in GENERIC)
                       and (p2.get("first") or "9999-99-99") < str(s0["start"])]
            if earlier:
                continue
            ds = [p2.get("first") for p2 in series if p2.get("first")]
            if not ds:
                continue
            first = min(ds)
            if str(win0) <= first <= str(win1):
                new_buyers.append(cid2)
        new_buyers.sort()

        # 把「本期新客」再拆成四档：真新客 / 久别回归 / 沉睡回归 / 活跃老客
        def classify_new(c):
            hist = [p2 for p2 in PURCH.get(c, [])
                    if (p2.get("first") or "9999") < str(win0)]
            tags2 = TAGS.get(c, []) or []
            had_before = any("半月谈场次" in t for t in tags2)
            if not hist:
                return ("真新客", None, had_before)
            last = max((p2.get("first") or "") for p2 in hist)
            try:
                days = (s0["start"] - datetime.date(*map(int, last.split("-")))).days
            except (ValueError, TypeError):
                days = None
            if days is None:
                return ("真新客", None, had_before)
            if days > 365:
                return ("久别回归", days, had_before)
            if days > 90:
                return ("沉睡回归", days, had_before)
            return ("活跃老客", days, had_before)

        buckets = {"真新客": [], "久别回归": [], "沉睡回归": [], "活跃老客": []}
        for c in new_buyers:
            kind, days, had = classify_new(c)
            buckets[kind].append([c, row_by_id.get(c, {}).get("name", ""),
                                  days if days is not None else -1, 1 if had else 0])
        # 观看深度：深看 / 中看 / 浅看 / 没看（买了没看）
        def pack(ids, lim=60):
            out = []
            for cid2 in ids:
                m0 = round(minutes.get(cid2, 0))
                o2 = row_by_id.get(cid2) or {}
                out.append({"id": cid2, "name": o2.get("name") or name_by_id.get(cid2, ""),
                            "分钟": m0, "Ct": o2.get("Ct", ""), "spend": o2.get("spend", 0),
                            "quad": o2.get("quad", ""), "fuDays": o2.get("fuDays"),
                            "action": o2.get("action", "")})
            out.sort(key=lambda x: -x["分钟"])
            return {"n": len(out), "avg": round(sum(x["分钟"] for x in out) / max(1, len(out))),
                    "list": out[:lim]}

        deep = [c for c in learners if minutes.get(c, 0) >= 80]
        mid = [c for c in learners if 30 <= minutes.get(c, 0) < 80]
        light = [c for c in learners if 0 < minutes.get(c, 0) < 30]
        watch_depth = {"深看": pack(deep), "中看": pack(mid), "浅看": pack(light),
                       "没看": pack([c for c in buyers if c not in learners])}
        # 续费判定：权限表覆盖够（>=60% 成员有明确值）才按权限算，否则退回订单口径
        states = {c: perm_state(c, s0["renewKws"]) for c in members} if s0["renewKws"] else {}
        covered = sum(1 for v in states.values() if v is not None)
        coverage = covered / len(members) if members else 0
        by_perm = bool(PERMS) and bool(s0["renewKws"]) and coverage >= 0.6
        by_pc = (not by_perm) and bool(PURCH) and bool(s0["renewKws"])
        deadline = s0["end"] + datetime.timedelta(days=s0["win"])
        renewed, renew_amt = {}, {}
        if by_perm:
            for cid2, v in states.items():
                if v:
                    renewed[cid2] = True
                    renew_amt[cid2] = 0.0
        elif by_pc:
            # 已购全集：结课后买过同系列任一课程即算续费（不受 30 天窗口限制）
            for cid2 in members:
                for p2 in PURCH.get(cid2, []):
                    if not any(k in p2["c"] for k in s0["renewKws"]):
                        continue
                    if (p2["last"] or "") > str(s0["end"]):
                        renewed[cid2] = True
                        if p2["last"] <= str(deadline):
                            renew_amt[cid2] = renew_amt.get(cid2, 0) + p2["amt"]
                        break
        deadline = s0["end"] + datetime.timedelta(days=s0["win"])
        for o in ([] if (by_perm or by_pc) else paid30["rows"]):
            cid2 = o.get("客户编号")
            if cid2 not in members:
                continue
            d0 = days_since(o.get("付款时间"))
            if d0 is None:
                continue
            day = TODAY - datetime.timedelta(days=d0)
            if not (s0["end"] < day <= min(deadline, TODAY)):
                continue
            if float(o.get("金额元") or 0) <= 0:      # 0 元赠课 / 试听不算续费
                continue
            prod = o.get("商品") or ""
            if s0["renewKws"]:
                if not any(k in prod for k in s0["renewKws"]):
                    continue
            elif hit(prod):
                continue
            renewed[cid2] = True
            renew_amt[cid2] = renew_amt.get(cid2, 0) + float(o.get("金额元") or 0)

        def row_of(cid2):
            r0 = row_by_id.get(cid2) or {}
            return {"id": cid2, "name": r0.get("name") or name_by_id.get(cid2) or "（未命名）",
                    "分钟": round(minutes.get(cid2, 0)), "spend": r0.get("spend") or 0,
                    "Ct": r0.get("Ct", "—"), "quad": r0.get("quad", "—"),
                    "renew": round(renew_amt.get(cid2, 0)), "paid": round(paid_amt.get(cid2, 0))}

        if not by_perm and s0["renewKws"] and members:
            reports_note = None
        if by_perm:
            # 权限口径下，续费金额按结课后窗口内的实际付款补算
            for o in paid30["rows"]:
                cid2 = o.get("客户编号")
                if cid2 not in renewed:
                    continue
                d0 = days_since(o.get("付款时间"))
                if d0 is None:
                    continue
                day = TODAY - datetime.timedelta(days=d0)
                if s0["end"] < day <= min(deadline, TODAY) and float(o.get("金额元") or 0) > 0:
                    renew_amt[cid2] = renew_amt.get(cid2, 0) + float(o.get("金额元") or 0)
        renew_list = sorted((row_of(c) for c in renewed), key=lambda x: -x["renew"])
        non_list = sorted((row_of(c) for c in members if c not in renewed),
                          key=lambda x: (-(x["分钟"] or 0), -x["spend"]))
        if s0["end"] > TODAY:
            status = "未结课"
        elif TODAY - s0["end"] > datetime.timedelta(days=30):
            status = "窗口不足"
        else:
            status = "已结课"
        reports.append({
            "名": s0["名"], "关键词": " / ".join(kws), "开课": str(s0["start"]), "结课": str(s0["end"]),
            "窗口": s0["win"], "状态": status,
            "到课人数": len(learners), "观看分钟": round(sum(minutes.values())),
            "人均分钟": round(sum(minutes.values()) / len(learners)) if learners else 0,
            "购买人数": len(buyers), "购买金额": round(sum(paid_amt.values())),
            "成员": len(members), "续费人数": len(renewed),
            "续费率": round(len(renewed) / len(members) * 100) if members else 0,
            "续费金额": round(sum(renew_amt.values())),
            "口径": "课程权限" if by_perm else ("已购全集" if by_pc else "订单"),
            "权限覆盖": "%d/%d" % (covered, len(members)),
            "权限覆盖数": covered,
            "观看深度": watch_depth,
            "系列": series_of(s0),
            "新学员数": len(fresh_ids), "老学员数": len(old_ids),
            "老学员里买过课的": sum(1 for c in old_ids if bought_earlier_issue(c)),
            "本期新客": len(new_buyers),
            "本期新客名单": [[c, row_by_id.get(c, {}).get("name", "")] for c in new_buyers[:80]],
            "本期新客没看课": len([c for c in new_buyers if c not in learners]),
            "新客分档": {k: {"n": len(v), "list": v[:40]} for k, v in buckets.items()},
            "新学员": [[c, round(minutes.get(c, 0))] for c in fresh_ids],
            "老学员": [[c, round(minutes.get(c, 0))] for c in old_ids],
            "续费名单": renew_list[:200], "未续费名单": non_list[:200],
        })
    reports.sort(key=lambda r: (r["状态"] != "已结课", r["结课"]), reverse=False)
    return reports


def build_touch_plan():
    """行情状态 → 今天该精细触达谁、剩下怎么批量。"""
    st = (MARKET or {}).get("状态", "")
    good = st in ("强势", "偏强")
    if good:
        fine = [r for r in rows if r["quad"] == "行情型" and r["C"] >= 5
                and (r["paid30"]["n"] or r["learn30"])]
        fine.sort(key=lambda r: (-(r["spend"] or 0), -r["market"]))
        why = "行情在走强：行情型的高价值客户正在关注盘面，现在发给他们的成交概率最高"
        batch = "沉默资产 + 未激活 走群发；核心维护可以等这一波结束再聊"
    else:
        fine = [r for r in rows if r["quad"] in ("核心维护", "行情敏感") and r["trust"] >= 45
                and (r["spend"] or 0) >= 5000]
        fine.sort(key=lambda r: (-r["trust"], -(r["spend"] or 0)))
        why = "行情在走弱：等行情的人现在不会动，反而是认人的老客户需要被维护"
        batch = "行情型先别碰，等指数站回 MA20 再说；沉默资产靠活动批量唤"
    fine_ids = {r["id"] for r in fine}
    rest = [r for r in rows if r["id"] not in fine_ids]
    groups = {}
    for r in rest:
        groups.setdefault(r["bucket"], []).append(r)
    batch_groups = []
    for k in ("即刻打", "复购升单", "在读保温", "沉默唤醒", "待转化", "低优先"):
        if k in groups:
            batch_groups.append({"名": k, "人数": len(groups[k]),
                                 "说明": {"即刻打": "有未付款 / 快掉公 / 逾期，今天必须联系", "复购升单": "中客单以上，续费或升单", "在读保温": "还在上课，靠学习进度焊住", "沉默唤醒": "付过费但没动静，用内容唤起", "待转化": "没付过费，先判断值不值得", "低优先": "已删好友且长期无动作"}.get(k, "")})
    return {
        "状态": st, "行情好": good, "策略": why, "批量": batch,
        "精细": [{"id": r["id"], "name": r["name"], "spend": r["spend"], "Ct": r["Ct"],
                  "quad": r["quad"], "market": r["market"], "trust": r["trust"],
                  "fuDays": r["fuDays"], "learn": (r["learn30"] or {}).get("d", 0),
                  "paidN": r["paid30"]["n"], "action": r["action"]} for r in fine[:60]],
        "精细总数": len(fine),
        "批量": batch_groups,
        "批量总数": len(rest),
    }


SESSIONS = load_sessions()


def find_unscheduled(sessions):
    """最近 30 天有人看的课，但没有一条排课关键词能匹配到——漏排的提醒。"""
    kws = [k for s0 in sessions for k in s0["kws"]]
    agg = {}
    for r2 in learn30["rows"]:
        for x in (r2.get("明细") or []):
            n = (x.get("名称") or "").strip()
            if not n:
                continue
            if any(k in n for k in kws):
                continue
            a = agg.setdefault(n, {"课程": n, "人数": 0, "分钟": 0})
            a["人数"] += 1
            a["分钟"] += float(x.get("分钟") or 0)
    out = sorted(agg.values(), key=lambda x: -x["人数"])[:12]
    for o in out:
        o["分钟"] = round(o["分钟"])
    return out


def seed_perms(sessions):
    """第一次运行时给一份「待确认」初稿：课程 / 依据已经填好，权限和到期日你来定。"""
    if PERM_FILE.exists():
        return
    import csv as _csv
    rows = []
    seen = set()
    for s0 in sessions:
        for kw in s0["renewKws"]:
            for r2 in learn30["rows"]:
                cid2 = r2.get("客户编号")
                if (cid2, kw) in seen:
                    continue
                if any(kw in (x.get("名称") or "") for x in (r2.get("明细") or [])):
                    seen.add((cid2, kw))
                    rows.append([cid2, name_of.get(cid2) or "", kw, "", "", "学习记录"])
            for o in paid30["rows"]:
                cid2 = o.get("客户编号")
                if (cid2, kw) in seen or float(o.get("金额元") or 0) <= 0:
                    continue
                if kw in (o.get("商品") or ""):
                    seen.add((cid2, kw))
                    rows.append([cid2, name_of.get(cid2) or "", kw, "", "", "订单"])
    if not rows:
        return
    with PERM_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["客户编号", "称呼", "课程", "权限", "到期日", "依据"])
        w.writerows(rows)
    print("已生成课程权限初稿：%s（%d 行，权限列留空待你确认）" % (PERM_FILE.name, len(rows)))


name_of = {r["id"]: r["name"] for r in rows}
seed_perms(SESSIONS)
PERMS = load_perms()
def build_months(reports):
    """月度汇总：把同一个月里所有期次合成一组数。"""
    from collections import defaultdict
    bym = defaultdict(list)
    for r in reports:
        if r["状态"] == "未结课":
            continue
        bym[r["开课"][:7]].append(r)
    out = []
    for m in sorted(bym, reverse=True):
        rs = bym[m]
        ids = set()
        for r in rs:
            ids |= {c[0] for c in (r.get("新学员") or [])}
            ids |= {c[0] for c in (r.get("老学员") or [])}
        withprev = [r for r in rs if r.get("上期")]
        series = {}
        for r in rs:
            s2 = series.setdefault(r["系列"], {"场次": 0, "到课": 0, "新": 0, "老": 0,
                                               "留存": 0, "流失": 0, "新增": 0, "上期到课": 0})
            s2["场次"] += 1
            s2["到课"] += r["到课人数"]
            s2["新"] += r["新学员数"]
            s2["老"] += r["老学员数"]
            if r.get("上期"):
                s2["留存"] += r["上期"]["留存"]
                s2["流失"] += r["上期"]["流失"]
                s2["新增"] += r["上期"]["新增"]
                s2["上期到课"] += r["上期"]["到课"]
        lost_ids = []
        for r in withprev:
            lost_ids += [c["id"] for c in (r["上期"].get("流失名单") or [])]
        lost_ids = list(dict.fromkeys(lost_ids))
        out.append({
            "月": m, "场次": len(rs), "系列数": len(series),
            "到课人次": sum(r["到课人数"] for r in rs), "去重人数": len(ids),
            "新": sum(r["新学员数"] for r in rs), "老": sum(r["老学员数"] for r in rs),
            "分钟": sum(r["观看分钟"] for r in rs),
            "新客": sum(r.get("本期新客") or 0 for r in rs),
            "留存": sum(r["上期"]["留存"] for r in withprev),
            "流失": sum(r["上期"]["流失"] for r in withprev),
            "新增": sum(r["上期"]["新增"] for r in withprev),
            "上期到课": sum(r["上期"]["到课"] for r in withprev),
            "有对比场次": len(withprev),
            "系列": [dict(名=k, **v) for k, v in sorted(series.items(), key=lambda kv: -kv[1]["到课"])],
            "流失名单": lost_ids,
            "场次名": [r["名"] for r in rs],
        })
    return out


REPORTS = attach_series_compare(build_reviews(SESSIONS), SESSIONS,
                                {r["id"]: r for r in rows})
unscheduled = find_unscheduled(SESSIONS)
MONTHS = build_months(REPORTS)
touch_plan = build_touch_plan()

# 访问地址：本机 / 局域网 / mDNS / 公网 / Tailscale
def build_access():
    import socket as _s, subprocess as _sp
    lan, host = "", ""
    try:
        out = _sp.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=3)
        lan = (out.stdout or "").strip()
    except Exception:
        pass
    if not lan:
        try:
            s2 = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            s2.connect(("8.8.8.8", 80))
            lan = s2.getsockname()[0]
            s2.close()
        except Exception:
            pass
    try:
        host = (_sp.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=3).stdout or "").strip()
    except Exception:
        host = ""
    pub = ""
    pf = HERE / "公网地址.txt"
    if pf.exists():
        pub = pf.read_text(encoding="utf-8").strip().splitlines()[0] if pf.read_text(encoding="utf-8").strip() else ""
    ts = ""
    try:
        o = _sp.run(["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "ip", "-4"],
                    capture_output=True, text=True, timeout=5)
        ts = (o.stdout or "").strip().splitlines()[0] if o.stdout.strip() else ""
    except Exception:
        pass
    tok = ""
    af = pathlib.Path.home() / ".workbuddy_web_auth"
    if af.exists():
        for ln in af.read_text(encoding="utf-8").splitlines():
            if ln.startswith("token:"):
                tok = ln[6:].strip()
    return {
        "令牌": tok,
        "本机": "http://127.0.0.1:8787/",
        "局域网": f"http://{lan}:8787/" if lan else "",
        "主机名": f"http://{host}.local:8787/" if host else "",
        "公网": pub,
        "Tailscale": f"http://{ts}:8787/" if ts else "",
        "要登录": (pathlib.Path.home() / ".workbuddy_web_auth").exists(),
        "内网IP": lan,
    }


CHAT_FILE = HERE / "会话分析.json"
CHAT = json.loads(CHAT_FILE.read_text(encoding="utf-8")) if CHAT_FILE.exists() else None

LOCKS_FILE = HERE / "锁定名单.json"
LOCKS = json.loads(LOCKS_FILE.read_text(encoding="utf-8")) if LOCKS_FILE.exists() else {}

ACCESS = build_access()

# 高客单产品库：开课锁定时按这个匹配候选
# 真正「参加过面对面」的判据（不含只买了俱乐部的）
ATTEND_KW = ["面对面", "2天线下", "线下闭门讲座", "面对面交流", "2天面对面"]

PROD_FILE = HERE / "高客单课程.csv"


def load_products():
    """高客单课程表（可在页面里增删改，存 高客单课程.csv）"""
    import csv as _csv
    if not PROD_FILE.exists():
        return []
    out = []
    with PROD_FILE.open(encoding="utf-8-sig") as f:
        for r in _csv.DictReader(f):
            name = (r.get("名称") or "").strip()
            if not name:
                continue
            kws = [k.strip() for k in re.split(r"[|,，、]", r.get("匹配关键词") or "") if k.strip()]
            try:
                price = int(float(r.get("价格") or 0))
            except ValueError:
                price = 0
            out.append({
                "名": name, "价": price,
                "档": (r.get("档位") or "").strip() or "高客单",
                "kw": kws or [name],
                "说明": (r.get("说明") or "").strip(),
                "exclude_attend": (r.get("排除参加过面对面") or "").strip() in ("是", "true", "1", "yes"),
            })
    return out


PRODUCTS = load_products()


def build_product_picks():
    """每门高客单课，锁定一批优先沟通的学员（排除已买过本课的）。"""
    row_by_id = {r["id"]: r for r in rows}
    out = []
    for prod in PRODUCTS:
        kw = prod["kw"]
        buyers, picks = set(), []
        for cid, lst in PURCH.items():
            if any(any(k in (p2.get("c") or "") for k in kw) for p2 in lst):
                buyers.add(cid)
        # 参加过面对面的，从「首参加」名单里排除（二次价 9800，基本不会来）
        attended = set()
        if prod.get("exclude_attend"):
            for cid0, lst0 in PURCH.items():
                if any(any(k in (p0.get("c") or "") for k in ATTEND_KW) for p0 in lst0):
                    attended.add(cid0)
        for r in rows:
            cid = r["id"]
            if cid in buyers:
                continue
            if cid in attended:
                continue
            if any(k in (r.get("name") or "") for k in ("内部同事", "测试", "加速同事")):
                continue
            spend = r.get("spend") or 0
            if spend < 2680:                     # 高客单课不投未付费
                continue
            if r.get("del") or r.get("deleted"):  # 已删好友
                continue
            score, why = 0, []
            # 消费档
            for th, pts, label in ((100000, 40, "消费 10 万以上"), (50000, 32, "消费 5 万以上"),
                                   (20000, 22, "消费 2 万以上"), (10000, 16, "消费 1 万以上"),
                                   (2680, 8, "中客单")):
                if spend >= th:
                    score += pts; why.append(label); break
            # 关系深度（认人不认行情）
            R = r.get("R") or 1
            if R >= 5:
                score += 22; why.append("关系 R5 深度黏着")
            elif R >= 4:
                score += 15; why.append("关系 R4 稳定")
            elif R == 3:
                score += 8
            # 近期学习
            d30 = (r.get("learn30") or {}).get("d") or 0
            if d30 >= 5:
                score += 14; why.append("近 30 天学习 %d 天" % d30)
            elif d30 > 0:
                score += 7; why.append("近 30 天有学习")
            # 近期付款
            pn = (r.get("paid30") or {}).get("n") or 0
            if pn >= 2:
                score += 12; why.append("近 30 天付款 %d 笔" % pn)
            elif pn == 1:
                score += 6
            # 有未付款：可能卡在支付
            if r.get("unpaid"):
                score += 5; why.append("有未付款订单")
            # 品类相近（买过同系列其它课）
            if r.get("pc") and any(k in r["pc"] for k in kw):
                score += 10; why.append("买过相近的课")
            # 行情敏感（低信任）降权
            if r.get("quad") == "行情敏感":
                score -= 12; why.append("行情敏感，需先建立信任")
            # 太久没联系降权
            fd = r.get("fuDays")
            if fd is None:
                score -= 6
            elif fd > 180:
                score -= 8
            elif fd <= 30:
                score += 6; why.append("近 30 天有跟进")
            picks.append({"id": cid, "name": r.get("name"), "score": score,
                          "spend": round(spend), "Ct": r.get("Ct"), "Rt": r.get("Rt"),
                          "quad": r.get("quad"), "learn": d30, "paidN": pn,
                          "fuDays": fd, "why": why[:5],
                          "tier": "A" if score >= 55 else ("B" if score >= 35 else "C")})
        picks.sort(key=lambda x: -x["score"])
        out.append({"名": prod["名"], "价": prod["价"], "档": prod["档"], "说明": prod["说明"],
                    "已买过": len(buyers), "候选": len(picks),
                    "已排除参加过": len(attended) if prod.get("exclude_attend") else 0,
                    "A": sum(1 for x in picks if x["tier"] == "A"),
                    "B": sum(1 for x in picks if x["tier"] == "B"),
                    "名单": picks[:120]})
    return out


def build_attend_pool():
    """参加过面对面的老学员：二次价 9800，不做首参加推广，但可以做换城市/转介绍。"""
    out = []
    for cid, lst in PURCH.items():
        hit = [p2 for p2 in lst if any(k in (p2.get("c") or "") for k in ATTEND_KW)]
        if not hit:
            continue
        r = next((x for x in rows if x["id"] == cid), None)
        if r is None:
            continue
        if any(k in (r.get("name") or "") for k in ("内部同事", "测试", "加速同事")):
            continue
        tags = TAGS.get(cid, []) or []
        # 转介绍迹象：标签/跟进正文里出现介绍、朋友、同行
        blob = " ".join(tags) + " " + (r.get("fuText") or "")
        refer = any(k in blob for k in ("介绍", "朋友", "同行", "带人", "团报"))
        last = max((p2.get("first") or "") for p2 in hit)
        R = r.get("R") or 1
        spend = r.get("spend") or 0
        d30 = (r.get("learn30") or {}).get("d") or 0
        # 二次机会分：关系深度为主，活跃为辅
        score = R * 6 + (12 if d30 >= 3 else 6 if d30 else 0) + (10 if refer else 0) \
                + (8 if spend >= 30000 else 4 if spend >= 10000 else 0)
        out.append({"id": cid, "name": r.get("name"), "score": score,
                    "spend": round(spend), "R": R, "Rt": r.get("Rt"),
                    "Ct": r.get("Ct"), "quad": r.get("quad"),
                    "参加过": (hit[0].get("c") or "")[:26], "期数": len(hit), "最近参加": last,
                    "learn": d30, "fuDays": r.get("fuDays"), "refer": refer,
                    "tags": tags[:2]})
    out.sort(key=lambda x: -x["score"])
    return {"总人数": len(out), "名单": out,
            "换城市": [x for x in out if x["R"] >= 3][:300],
            "转介绍": [x for x in out if x["refer"] or x["R"] >= 4 or x["spend"] >= 30000][:300]}


ATTEND_POOL = build_attend_pool()

PICKS = build_product_picks()

# 交叉命中：同一个人在哪些课的 A 类名单里（避免重复打）
_where = {}
for _p in PICKS:
    for _x in _p["名单"]:
        if _x["tier"] == "A":
            _where.setdefault(_x["id"], []).append(_p["名"])
for _p in PICKS:
    for _x in _p["名单"]:
        _others = [n for n in _where.get(_x["id"], []) if n != _p["名"]]
        _x["also"] = _others


def build_today(chat, locks):
    """今天做什么：只放能点开、能动手的事，不放分数。"""
    import datetime as _dt
    items = []
    # 1) 客户最后说话、我方还没回
    wait = (chat or {}).get("待回复") or []
    if wait:
        items.append({"key": "wait", "名": "客户最后发消息，你还没回",
                      "n": len(wait), "urgent": True,
                      "说明": "最近 3 天内，对话最后一条是客户发的",
                      "list": [{"name": x["人"], "最近": x["最近"], "对方": x["对方"]} for x in wait[:60]]})
    # 2) 锁定的课，开课临近且没聊完
    for name, v in (locks or {}).items():
        try:
            day = _dt.date(*map(int, (v.get("开课日") or "").split("-")))
            left = (day - TODAY).days
        except (ValueError, TypeError):
            left = None
        done = len(v.get("已聊") or {})
        total = len(v.get("ids") or [])
        todo = total - done
        if todo <= 0:
            continue
        items.append({"key": "lock", "名": "锁定场次还没聊完：%s" % name,
                      "n": todo, "urgent": left is not None and left <= 7,
                      "说明": ("开课还有 %d 天" % left if left is not None and left >= 0 else "开课日已过"),
                      "ids": [i for i in (v.get("ids") or []) if str(i) not in (v.get("已聊") or {})][:200]})
    # 3) 未付款
    us = unpaid_stat or {}
    if us.get("昨天"):
        items.append({"key": "unpaid", "名": "昨天的未付款要捞", "n": us.get("昨天"),
                      "urgent": True, "说明": "合计 %s 元" % round(us.get("昨天金额") or 0),
                      "ids": [r["id"] for r in unpaid_rows if r["日"] == str(TODAY - datetime.timedelta(days=1))]})
    # 4) 昨晚到课没跟进
    ws = watch_stat or {}
    if ws.get("90天没跟进"):
        items.append({"key": "watch", "名": "昨晚到课、90 天没跟进的人", "n": ws["90天没跟进"],
                      "urgent": False, "说明": "人在课上，库里没人管",
                      "ids": [m["id"] for m in (watch_list or [])
                              if (m.get("fuDays") is None or m["fuDays"] > 90)]})
    # 5) 真新客从没跟进
    nb = [x for x in NEWCOMERS if x["跟进"] is None]
    if nb:
        items.append({"key": "newbie", "名": "新客一条跟进都没写过", "n": len(nb),
                      "urgent": True, "说明": "45 天内进来的新人",
                      "ids": [x["id"] for x in nb]})
    return {"items": items, "总数": sum(i["n"] for i in items)}


def build_spend_bands():
    """消费分档（按老板的口径合并）：
       未付费 / 1–2680 / 2680–1万 / 1–5万 / 5–10万 / 10万以上
       每档带 ids，页面点一下就能筛出这批人。"""
    bands = [(100000, "10 万以上", "var(--danger)"),
             (50000, "5–10 万", "var(--danger)"),
             (10000, "1–5 万", "var(--brand2)"),
             (2680, "2680–1 万", "var(--brand2)"),
             (1, "1–2680", "var(--gold)")]
    out, prev = [], 10 ** 12
    for lo, name, color in bands:
        sel = [r for r in rows if lo <= (r.get("spend") or 0) < prev]
        out.append({"名": name, "n": len(sel),
                    "amt": round(sum(r.get("spend") or 0 for r in sel)),
                    "color": color, "ids": [r["id"] for r in sel]})
        prev = lo
    z = [r for r in rows if (r.get("spend") or 0) == 0]
    out.append({"名": "未付费", "n": len(z), "amt": 0, "color": "var(--muted)",
                "ids": [r["id"] for r in z]})
    top = {
        "5万": sum(1 for r in rows if (r.get("spend") or 0) >= 50000),
        "10万": sum(1 for r in rows if (r.get("spend") or 0) >= 100000),
        "20万": sum(1 for r in rows if (r.get("spend") or 0) >= 200000),
        "5万amt": round(sum(r.get("spend") or 0 for r in rows if (r.get("spend") or 0) >= 50000)),
    }
    return {"bands": out, "top": top}


SPEND = build_spend_bands()


def build_newcomers(days=45):
    """真新客池：近 N 天第一次买课的人（此前没有任何购买记录）。"""
    first_day, first_course, first_amt = {}, {}, {}
    for cid, lst in PURCH.items():
        best = min(lst, key=lambda x: (x.get("first") or "9999", x.get("c") or ""))
        d = (best.get("first") or "").strip()
        if not d:
            continue
        first_day[cid] = d
        first_course[cid] = best.get("c") or ""
        first_amt[cid] = best.get("amt") or 0
    cutoff = str(TODAY - datetime.timedelta(days=days))
    out = []
    for cid, d in first_day.items():
        if d < cutoff:
            continue
        r = next((x for x in rows if x["id"] == cid), None)
        if r is None:
            continue
        if any(k in (r.get("name") or "") for k in ("内部同事", "测试", "加速同事")):
            continue
        try:
            ago = (TODAY - datetime.date(*map(int, d.split("-")))).days
        except (ValueError, TypeError):
            continue
        out.append({
            "id": cid, "name": r.get("name", ""), "首单日": d, "距今": ago,
            "首单课": first_course[cid][:40], "首单金额": round(first_amt[cid]),
            "累计消费": round(r.get("spend") or 0),
            "看过课": (r.get("learn30") or {}).get("d", 0),
            "跟进": r.get("fuDays"), "来源": r.get("source") or "—",
            "Ct": r.get("Ct", ""), "quad": r.get("quad", ""),
            "tags": (r.get("tags") or [])[:3],
        })
    out.sort(key=lambda x: (x["距今"], -x["累计消费"]))
    return out


NEWCOMERS = build_newcomers(45)

# 未付款清单（近 14 天，按日期倒序）
unpaid_rows = []
for u in unpaid14["rows"]:
    day = str(u.get("下单时间") or "")[:10]
    st = (u.get("状态") or "")
    unpaid_rows.append({
        "日": day,
        "时间": str(u.get("下单时间") or "")[:16],
        "id": u.get("客户编号"),
        "name": u.get("称呼") or name_by_id.get(u.get("客户编号")) or "",
        "商品": (u.get("商品") or "")[:40],
        "金额": u.get("金额元"),
        "平台": u.get("平台"),
        "状态": st,
        "已付后来": bool(u.get("同商品已另付款")),
        "取消": ("取消" in st) or ("关闭" in st),
    })
unpaid_rows.sort(key=lambda r: r["时间"], reverse=True)
_y = str(TODAY - datetime.timedelta(days=1))
_two = str(TODAY - datetime.timedelta(days=2))
unpaid_stat = {
    "昨天": sum(1 for r in unpaid_rows if r["日"] == _y),
    "昨天金额": round(sum(float(r["金额"] or 0) for r in unpaid_rows if r["日"] == _y)),
    "前天": sum(1 for r in unpaid_rows if r["日"] == _two),
    "近7天": sum(1 for r in unpaid_rows if r["日"] >= str(TODAY - datetime.timedelta(days=7))),
    "近7天金额": round(sum(float(r["金额"] or 0) for r in unpaid_rows
                       if r["日"] >= str(TODAY - datetime.timedelta(days=7)))),
    "近14天": len(unpaid_rows),
    "未付客户": len({r["id"] for r in unpaid_rows if not r["已付后来"]}),
}

# ---------------------------------------------------------------- 汇总
BUCKETS = ["即刻打", "复购升单", "在读保温", "沉默唤醒", "待转化", "低优先"]
bucket_cnt = Counter(r["bucket"] for r in rows)
tier_cnt = Counter(r["tier"] for r in rows)
stage_cnt = Counter(r["stage"] for r in rows)

def value_band(r):
    return "高" if r["spend"] >= 5000 else ("中" if r["spend"] >= 2680 else "低")

def activity_band(r):
    if r["learn"] or r["paid30"]["n"] or (r["fuDays"] is not None and r["fuDays"] <= 30):
        return "活跃"
    if r["fuDays"] is not None and r["fuDays"] <= 90:
        return "一般"
    return "沉默"

matrix = defaultdict(int)
matrix_ids = defaultdict(list)
for r in rows:
    k = value_band(r) + "·" + activity_band(r)
    matrix[k] += 1
    matrix_ids[k].append(r["id"])

def silence_band(d):
    if d is None:
        return "从无跟进"
    if d <= 7:
        return "7 天内"
    if d <= 30:
        return "8–30 天"
    if d <= 60:
        return "31–60 天"
    if d <= 90:
        return "61–90 天"
    return "90 天以上"

silence_cnt = Counter(silence_band(r["fuDays"]) for r in rows)
Lcnt = Counter(r["L"] for r in rows)
Rcnt = Counter(r["R"] for r in rows)

YESTERDAY = TODAY - datetime.timedelta(days=1)
name_by_id = {r["id"]: r["name"] for r in rows}
row_by_id = {r["id"]: r for r in rows}
watch = {}
for r2 in learn2["rows"]:
    cid2 = r2.get("客户编号")
    for x in (r2.get("明细") or []):
        if str(x.get("日期")) != str(YESTERDAY):
            continue
        nm = x.get("名称") or "（未命名课程）"
        wc = watch.setdefault(nm, {"课程": nm, "分钟": 0, "学员": {}})
        mins = float(x.get("分钟") or 0)
        wc["分钟"] += mins
        et = wc["学员"].get(cid2) or {"id": cid2, "name": name_by_id.get(cid2) or "", "分钟": 0, "类型": x.get("类型")}
        et["分钟"] += mins
        wc["学员"][cid2] = et
daily_watch = []
for nm, wc in watch.items():
    cd = course_date_of(nm)
    kind = "当晚直播" if (cd and cd == YESTERDAY) else ("回放/未排期" if not cd else "非当日直播")
    members = sorted(wc["学员"].values(), key=lambda m: -m["分钟"])
    for m in members:
        rr = row_by_id.get(m["id"]) or {}
        m["Rt"] = rr.get("Rt", "—")
        m["Ct"] = rr.get("Ct", "—")
        m["Gt"] = rr.get("Gt", "—")
        m["R"] = rr.get("R") or 0
        m["C"] = rr.get("C") or 0
        m["L"] = rr.get("L") or 0
        m["bucket"] = rr.get("bucket", "—")
        m["quad"] = rr.get("quad", "—")
        m["spend"] = round(rr.get("spend") or 0)
        m["fuDays"] = rr.get("fuDays")
        m["unpaid"] = len(rr.get("unpaid") or [])
    daily_watch.append({"课程": nm, "类别": kind, "分钟": round(wc["分钟"]), "人数": len(members),
                        "学员": members})
daily_watch.sort(key=lambda c: -c["人数"])

_flat = {}
for c0 in daily_watch:
    for m0 in c0["学员"]:
        cur = _flat.get(m0["id"])
        if cur is None:
            _flat[m0["id"]] = dict(m0)
        else:
            cur["分钟"] = cur.get("分钟", 0) + m0.get("分钟", 0)
watch_stat = {
    "总数": len(_flat),
    "中客单及以上": sum(1 for m0 in _flat.values() if (m0.get("spend") or 0) >= 2680),
    "未付费": sum(1 for m0 in _flat.values() if not (m0.get("spend") or 0)),
    "沉默资产": sum(1 for m0 in _flat.values() if m0.get("quad") == "沉默资产"),
    "行情型": sum(1 for m0 in _flat.values() if m0.get("quad") == "行情型"),
    "核心维护": sum(1 for m0 in _flat.values() if m0.get("quad") == "核心维护"),
    "有未付款": sum(1 for m0 in _flat.values() if m0.get("unpaid")),
    "90天没跟进": sum(1 for m0 in _flat.values() if m0.get("fuDays") is None or m0.get("fuDays") > 90),
}
watch_sorted = sorted(_flat.values(), key=lambda m0: (
    -(m0.get("R") or 0), -(m0.get("C") or 0), -(m0.get("分钟") or 0)))
for i, m0 in enumerate(watch_sorted, 1):
    m0["rank"] = i
watch_list = watch_sorted[:400]
top50 = [dict(m0) for m0 in watch_sorted[:50]]
rest = watch_sorted[50:]

# 剩下的人按「给什么」分组
GROUPS = [
    ("沉默资产", "付过 2,680 以上、近期不学不聊，昨晚自己回来了", "发回放 + 下期预告，不推销"),
    ("行情型", "只在行情热的时候出现", "发一段行情观点，不带课程链接"),
    ("核心维护", "认人不认行情，长期关系", "发深度内容 / 研修营名额"),
    ("未激活", "没付过费或金额很低", "发低价体验课 / 公开直播"),
]
group_buckets = {}
for gname, why, what in GROUPS:
    ids = [m0 for m0 in rest if (m0.get("quad") == gname) or (gname == "未激活" and m0.get("quad") in ("未激活", "行情敏感"))]
    group_buckets[gname] = {"名": gname, "说明": why, "动作": what, "人数": len(ids),
                            "名单": [{"id": m0["id"], "name": m0["name"], "Rt": m0.get("Rt"),
                                    "Ct": m0.get("Ct"), "分钟": round(m0.get("分钟") or 0),
                                    "spend": m0.get("spend") or 0, "quad": m0.get("quad")} for m0 in ids]}
covered = set()
for g in group_buckets.values():
    covered |= {x["id"] for x in g["名单"]}
leftover = [m0 for m0 in rest if m0["id"] not in covered]
if leftover:
    group_buckets.setdefault("其他", {"名": "其他", "说明": "不在上面几类里", "动作": "统一活动通知",
                                    "人数": 0, "名单": []})
    group_buckets["其他"]["名单"] += [{"id": m0["id"], "name": m0["name"], "Rt": m0.get("Rt"),
                                     "Ct": m0.get("Ct"), "分钟": round(m0.get("分钟") or 0),
                                     "spend": m0.get("spend") or 0, "quad": m0.get("quad")} for m0 in leftover]
    group_buckets["其他"]["人数"] = len(group_buckets["其他"]["名单"])

daily_unpaid = []
for u in unpaid2["rows"]:
    if str(u.get("下单时间"))[:10] != str(YESTERDAY):
        continue
    cid2 = u.get("客户编号")
    rr = row_by_id.get(cid2) or {}
    daily_unpaid.append({"id": cid2, "name": u.get("称呼") or name_by_id.get(cid2) or "",
                         "平台": u.get("平台"), "商品": u.get("商品"), "金额": u.get("金额元"),
                         "时间": u.get("下单时间"), "状态": u.get("状态"),
                         "Ct": rr.get("Ct", "—"), "Rt": rr.get("Rt", "—"), "Gt": rr.get("Gt", "—")})

# 3) 课程日历（首次生成，之后按你的填写为准）
if not CAL_FILE.exists():
    import csv as _csv
    names = {}
    for r2 in learn30["rows"]:
        for x in (r2.get("明细") or []):
            if x.get("类型") != "直播":
                continue
            nm = x.get("名称") or ""
            if nm and nm not in names:
                cd = parse_course_date(nm)
                names[nm] = cd.isoformat() if cd else ""
    with CAL_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["课程名", "直播日期", "备注"])
        for nm in sorted(names):
            w.writerow([nm, names[nm], "自动推断" if names[nm] else "请填直播日期 YYYY-MM-DD"])
    print("已生成课程日历: %s（%d 门课）" % (CAL_FILE.name, len(names)))
Ccnt = Counter(r["C"] for r in rows)
Gcnt = Counter(r["G"] for r in rows)
quadCnt = Counter(r["quad"] for r in rows)
cross = defaultdict(int)
for r in rows:
    cross["L%d·C%d·G%d" % (r["L"], r["C"], r["G"])] += 1
learn_kind_cnt = Counter()
for r in rows:
    if r["learn30"]:
        for k in r["learn30"]["kinds"]:
            learn_kind_cnt[k] += 1
silence_order = ["7 天内", "8–30 天", "31–60 天", "61–90 天", "90 天以上", "从无跟进"]

paid_customers = sum(1 for r in rows if r["spend"] > 0)
summary = {
    "生成时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "数据日": str(TODAY),
    "客户总数": len(rows),
    "已付费人数": paid_customers,
    "中客单及以上": sum(1 for r in rows if r["spend"] >= 2680),
    "高价值及以上": sum(1 for r in rows if r["spend"] >= 5000),
    "累计消费": round(sum(r["spend"] for r in rows)),
    "当下好友": sum(1 for r in rows if not r["deleted"]),
    "已被删除": sum(1 for r in rows if r["deleted"]),
    "有跟进记录": sum(1 for r in rows if r["fu"]),
    "从无跟进": sum(1 for r in rows if not r["fu"]),
    "逾期跟进": sum(1 for r in due["rows"] if (r.get("逾期天数") or 0) > 0),
    "七天内到期": sum(1 for r in due["rows"] if (r.get("逾期天数") or 0) <= 0),
    "未付款客户": len(unpaid_by),
    "未付款金额": round(sum(float(u.get("金额元") or 0) for u in unpaid["rows"])),
    "有学习客户": len(learn_by),
    "有商机客户": len(opp_by),
    "近30天付款客户": len(paid_by),
    "近30天实收": round(sum(v["amt"] for v in paid_by.values())),
    "快掉公72h": sum(1 for r in rows if r["drop"] is not None and r["drop"] <= 72),
}

payload = {
    "meta": summary,
    "bucketCnt": {b: bucket_cnt.get(b, 0) for b in BUCKETS},
    "tierCnt": dict(tier_cnt),
    "stageCnt": dict(stage_cnt),
    "matrix": {k: v for k, v in matrix.items()},
    "silence": {k: silence_cnt.get(k, 0) for k in silence_order},
    "silenceOrder": silence_order,
    "activities": [{"名称": a.get("名称"), "开始": a.get("开始"), "结束": a.get("结束"),
                    "已报名": a.get("已报名人数")} for a in acts["rows"]],
    "materials": [{"标题": m.get("title") or m.get("标题"), "公众号": m.get("account") or m.get("公众号"),
                   "已发表": bool(m.get("published")), "编号": m.get("id") or m.get("素材编号"),
                   "摘要": (m.get("excerpt") or "").strip()[:70]} for m in mats["rows"]],
    "Lcnt": {str(k): v for k, v in Lcnt.items()},
    "Rcnt": {str(k): v for k, v in Rcnt.items()},
    "liveMin": sum(r["liveMin"] for r in rows),
    "replayMin": sum(r["replayMin"] for r in rows),
    "contentMin": sum(r["contentMin"] for r in rows),
    "undatedMin": sum(r["undatedMin"] for r in rows),
    "日历": {"文件": CAL_FILE.name, "已填": len(CALENDAR),
             "可推断": sum(1 for r in learn30["rows"] for x in (r.get("明细") or []) if parse_course_date(x.get("名称")))},
    "today": build_today(CHAT, LOCKS),
    "daily": {"日期": str(YESTERDAY), "看课": daily_watch, "未付款": daily_unpaid,
              "到课结构": watch_stat, "到课名单": watch_list,
              "前50": top50, "群发": [g for g in group_buckets.values() if g["人数"] > 0],
              "已跟进": sum(1 for m0 in _flat.values() if m0.get("fuDays") is not None and m0["fuDays"] <= 1)},
    "Ccnt": {str(k): v for k, v in Ccnt.items()},
    "Gcnt": {str(k): v for k, v in Gcnt.items()},
    "quadCnt": dict(quadCnt),
    "topCross": [{"k": k, "n": v} for k, v in sorted(cross.items(), key=lambda x: -x[1])[:8]],
    "learnKindCnt": dict(learn_kind_cnt),
    "有学习30": len([r for r in rows if r["learn30"]]),
    "有跟进正文": len([r for r in rows if r["fuN"]]),
    "跟进质量": {
        "有记录": len([r for r in rows if r["fuN"]]),
        "有实质": len([r for r in rows if r.get("fuGood")]),
        "只有模板": len([r for r in rows if r["fuN"] and not r.get("fuGood")]),
        "总条数": sum(r["fuN"] for r in rows),
        "实质条数": sum(r.get("fuGood") or 0 for r in rows),
    },
    "tagCnt": dict(sorted(TAG_CNT.items(), key=lambda kv: -kv[1])),
    "hvCnt": {t: sum(1 for v in HV.values() if v["tier"] == t) for t in ("S 全品类", "A 双品类", "B 单品类", "C 其他大额", "C 无大额")},
    "tcCnt": {k: sum(1 for v in TEACH.values() if v["cls"] == k)
              for k in ("只买金岩石", "只买向松祚", "两位都买")},
    "pcCnt": dict(sorted(PC_CNT.items(), key=lambda kv: -kv[1])[:80]),
    "pcTotal": len(PURCH),
    "unpaid": unpaid_rows,
    "unpaidStat": unpaid_stat,
    "unscheduled": unscheduled,
    "market": MARKET,
    "access": ACCESS,
    "chat": CHAT,
    "noPurch": not PURCH,
    "noChat": not CHAT,
    "products": PICKS,
    "attendPool": {k: (v if k == "总人数" else len(v)) for k, v in ATTEND_POOL.items() if k != "名单"},
    "attendList": ATTEND_POOL["名单"][:400],
    "spendTotal": round(sum(r["spend"] for r in rows)),
    "spendBackendTotal": round(sum(r.get("spendBackend") or 0 for r in rows)),
    "spend": SPEND,
    "newcomers": NEWCOMERS,
    "touchPlan": touch_plan,
    "reviews": REPORTS,
    "months": MONTHS,
    "sessFile": SESS_FILE.name,
    "customers": rows,
}

# ---------------------------------------------------------------- 渲染
tpl = (HERE / "template.html").read_text(encoding="utf-8")
html = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
OUT.write_text(html, encoding="utf-8")

# 轻量索引：给本地服务的「导出打标签清单」用，避免读 11 MB 的页面
IDX = HERE / "客户索引.json"
IDX.write_text(json.dumps({str(r["id"]): {"name": r.get("name") or "", "spend": round(r.get("spend") or 0),
                                          "fuDays": r.get("fuDays")}
                           for r in rows}, ensure_ascii=False), encoding="utf-8")
print("已生成: %s  (%.0f KB, %d 个客户)" % (OUT, OUT.stat().st_size / 1024, len(rows)))

# 课件跟着工作台一起更新
try:
    r = subprocess.run([sys.executable, str(HERE / "build_course.py")], cwd=str(HERE),
                       capture_output=True, text=True)
    print((r.stdout or "").strip() or "课程页已同步")
except Exception as e:
    print("课程页没生成：%s" % e)
