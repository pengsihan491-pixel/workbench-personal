#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作台壳服务：每个同事填自己的凭证，本地生成自己的工作台

打开 http://127.0.0.1:8901 → 首次进来填 token → 自动拉数 → 看到自己的工作台
"""
import http.server, json, os, pathlib, socketserver, subprocess, sys, threading, time, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
TOKEN_FILE = pathlib.Path.home() / ".workbuddy_token"
OUT = HERE / "用户整理工作台.html"
PORT = int(os.environ.get("WB_PORT", "8901"))

STATE = {"running": False, "log": [], "ok": False, "why": "", "step": "", "ready": False}
STAMP = HERE / "上次更新.txt"
STALE_HOURS = 12

INJECT = """
<div id="wbBar" style="position:fixed;right:16px;bottom:16px;z-index:99999;
 font:13px/1.5 -apple-system,'PingFang SC',sans-serif">
  <div id="wbCard" style="background:#1f4a3d;color:#fff;border-radius:8px;padding:10px 14px;
   box-shadow:0 4px 16px rgba(0,0,0,.18);display:flex;gap:10px;align-items:center">
    <span id="wbTxt">数据截至 {STAMP}{BUSY}</span>
    <button id="wbBtn" style="background:#fff;color:#1f4a3d;border:0;border-radius:5px;
     padding:5px 10px;font-size:12px;cursor:pointer;font-weight:600">更新数据</button>
  </div>
</div>
<script>
(function(){
  const btn = document.getElementById('wbBtn'), txt = document.getElementById('wbTxt');
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = '更新中…';
    txt.textContent = '正在拉最新数据，约 3-8 分钟';
    const r = await fetch('/api/rebuild', {method:'POST'});
    if(!r.ok){ txt.textContent = '启动失败'; btn.disabled=false; return; }
    const poll = async () => {
      const d = await (await fetch('/api/status')).json();
      const last = (d.log||[]).slice(-1)[0] || '';
      txt.textContent = last ? last.slice(0, 40) : '拉取中…';
      if(d.running){ setTimeout(poll, 2000); return; }
      if(d.ok){ txt.textContent = '更新完成，正在刷新…'; setTimeout(()=>location.reload(), 800); }
      else { txt.textContent = '更新失败，看服务窗口'; btn.disabled = false; btn.textContent = '重试'; }
    };
    poll();
  };
})();
</script>
"""


def token():
    return os.environ.get("WORKBUDDY_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")


def save_token(t):
    TOKEN_FILE.write_text(t.strip(), encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def check_token(t):
    """用 guide 接口验一下凭证是否有效"""
    import urllib.request
    req = urllib.request.Request("https://jiasujiaoyu.cn/api/workbuddy/guide",
                                 headers={"Authorization": "Bearer " + t, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
        return bool(d.get("ok")), d.get("档") or ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


def stamp():
    if STAMP.exists():
        return STAMP.read_text(encoding="utf-8").strip()
    return "未生成"


def is_stale():
    if not OUT.exists():
        return True
    try:
        age = time.time() - OUT.stat().st_mtime
        return age > STALE_HOURS * 3600
    except OSError:
        return True


def serve_html():
    """给页面注入「更新数据」浮条"""
    html = OUT.read_bytes().decode("utf-8", "replace")
    busy = "（后台补数据中）" if STATE["running"] else ""
    bar = INJECT.replace("{STAMP}", stamp()).replace("{BUSY}", busy)
    if "</body>" in html:
        html = html.replace("</body>", bar + "</body>", 1)
    else:
        html += bar
    return html.encode()


STEPS = [
    ("基础数据", ["build_workbench.py"]),
    ("聊天记录", ["抓会话存档.py", "--days", "30", "--max-pages", "160"]),
    ("聊天分析", ["分析会话.py"]),
    ("已购课程", ["抓已购课程.py", "--workers", "6"]),
    ("重算总表", ["build_workbench.py"]),
]


def run_pipeline():
    """贴完凭证后一条龙：逐步补数据，每步完成都重算，用户随时能进"""
    if STATE["running"]:
        return
    STATE.update(running=True, ok=False, log=[], step="", ready=False)
    env = dict(os.environ, WORKBUDDY_TOKEN=token())

    def _go():
        okall = True
        for i, (name, cmd) in enumerate(STEPS, 1):
            STATE["step"] = "第 %d/%d 步 · %s" % (i, len(STEPS), name)
            STATE["log"].append("—— " + STATE["step"] + " ——")
            try:
                p = subprocess.Popen([sys.executable, "-u", str(HERE / cmd[0])] + cmd[1:],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, env=env, cwd=str(HERE))
                for line in p.stdout:
                    STATE["log"].append(line.rstrip()[:200])
                    STATE["log"] = STATE["log"][-80:]
                p.wait()
                if p.returncode != 0:
                    STATE["log"].append("这一步失败了，跳过继续")
                    okall = False
            except Exception as e:  # noqa: BLE001
                STATE["log"].append("出错：" + str(e)[:160])
                okall = False
            if i == 1 and OUT.exists():
                STATE["ready"] = True          # 第一步完成就能进去看
        STATE["ok"] = OUT.exists()
        STATE["step"] = "全部完成" if okall else "部分完成（看日志）"
        if OUT.exists():
            STAMP.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        STATE["running"] = False

    threading.Thread(target=_go, daemon=True).start()


def run_job(cmds, why=""):
    """顺序跑几个脚本，日志进 STATE"""
    STATE.update(running=True, ok=False, log=[], why=why)
    env = dict(os.environ, WORKBUDDY_TOKEN=token())

    def _go():
        ok = True
        for cmd in cmds:
            STATE["log"].append("→ " + " ".join(pathlib.Path(c).name for c in cmd))
            try:
                p = subprocess.Popen([sys.executable, "-u"] + cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, env=env, cwd=str(HERE))
                for line in p.stdout:
                    STATE["log"].append(line.rstrip()[:200])
                    STATE["log"] = STATE["log"][-60:]
                p.wait()
                if p.returncode != 0:
                    ok = False
                    break
            except Exception as e:  # noqa: BLE001
                STATE["log"].append("出错：" + str(e)[:200])
                ok = False
                break
        STATE["ok"] = ok and OUT.exists()
        if STATE["ok"]:
            STAMP.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        STATE["running"] = False

    threading.Thread(target=_go, daemon=True).start()


def run_build():
    """后台跑 build_workbench.py"""
    STATE.update(running=True, ok=False, log=[])
    env = dict(os.environ, WORKBUDDY_TOKEN=token())

    def _go():
        try:
            p = subprocess.Popen([sys.executable, str(HERE / "build_workbench.py")],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, env=env, cwd=str(HERE))
            for line in p.stdout:
                STATE["log"].append(line.rstrip()[:200])
                STATE["log"] = STATE["log"][-40:]
            p.wait()
            STATE["ok"] = p.returncode == 0 and OUT.exists()
            if STATE["ok"]:
                STAMP.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            STATE["log"].append("出错：" + str(e)[:200])
        finally:
            STATE["running"] = False

    threading.Thread(target=_go, daemon=True).start()


SETUP = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>用户整理工作台 · 初始化</title><style>
body{margin:0;background:#f4f2ee;color:#1d2321;font-family:-apple-system,'PingFang SC',sans-serif}
.box{max-width:560px;margin:12vh auto;background:#fff;padding:36px 34px;border:1px solid #e7e4de}
h1{font-size:20px;margin:0 0 6px;font-weight:650}
p{font-size:13px;color:#6b7570;line-height:1.8;margin:0 0 18px}
input{width:100%;padding:11px 12px;border:1px solid #d9d5cd;font-size:13px;border-radius:4px;
font-family:ui-monospace,Menlo,monospace}
button{margin-top:14px;padding:10px 22px;background:#1f4a3d;color:#fff;border:0;border-radius:4px;
font-size:13.5px;cursor:pointer}
button:disabled{background:#9aa39e}
.msg{font-size:12.5px;margin-top:14px;line-height:1.7}
.err{color:#a63a2b}.ok{color:#2f6f4b}
pre{background:#faf9f6;border:1px solid #eee9e1;padding:12px;font-size:11.5px;max-height:260px;
overflow:auto;margin-top:14px;white-space:pre-wrap}
</style></head><body><div class="box">
<h1>用户整理工作台</h1>
<p>贴一次凭证，之后就再也不用管了。<br>
<span style="font-size:12.5px;color:#9aa39e">凭证只存在这台电脑上，不会上传。</span></p>
<input id="t" placeholder="jsu_xxxxxxxxxxxxxxxx" autocomplete="off">
<button id="go">开始使用</button>
<a id="enter" href="/" style="display:none;margin-top:14px;padding:10px 20px;background:#2f6f4b;
 color:#fff;border-radius:4px;font-size:13.5px;text-decoration:none">进入工作台 →</a>
<div class="msg" id="m"></div>
<pre id="log" style="display:none"></pre>
</div>
<script>
const btn = document.getElementById('go'), inp = document.getElementById('t'), m = document.getElementById('m');
btn.onclick = async () => {
  const t = inp.value.trim();
  if(!t){ m.className='msg err'; m.textContent='请先贴凭证'; return; }
  btn.disabled = true; m.className='msg'; m.textContent='正在验证凭证…';
  const r = await fetch('/api/setup', {method:'POST', body: JSON.stringify({token:t})});
  const d = await r.json();
  if(!d.ok){ btn.disabled=false; m.className='msg err'; m.textContent = '凭证无效：' + (d.error||''); return; }
  m.className='msg ok'; m.textContent = '凭证有效，正在生成你的工作台（约 2 分钟，这个窗口不要关）…';
  document.getElementById('log').style.display='block';
  poll();
};
let left = 120;
async function poll(){
  const d = await (await fetch('/api/status')).json();
  if(d.ready){ m.textContent = '好了，正在进入…'; location.href = '/'; return; }
  if(d.running){
    left = Math.max(10, left - 2);
    m.textContent = '正在生成你的工作台，约还要 ' + left + ' 秒（不要关窗口）';
    setTimeout(poll, 2000);
    return;
  }
  if(d.ok){ location.href = '/'; return; }
  m.className = 'msg err';
  m.textContent = '生成失败。把浏览器里这段文字截图发给管理员：';
  document.getElementById('log').style.display = 'block';
  document.getElementById('log').textContent = (d.log||[]).slice(-12).join('\\n');
  btn.disabled = false;
}
</script></body></html>"""


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urllib.parse.urlsplit(self.path).path
        if p == "/api/status":
            return self._send(json.dumps(STATE, ensure_ascii=False), "application/json")
        if p in ("/", "/index.html"):
            if OUT.exists() and token():
                if is_stale() and not STATE["running"]:
                    run_build()          # 超过 12 小时自动后台更新
                return self._send(serve_html())
            if token() and STATE["running"]:
                return self._send(SETUP)  # 首次生成中，显示进度
            return self._send(SETUP)
        f = HERE / p.lstrip("/")
        if f.exists() and f.is_file() and f.resolve().parent == HERE.resolve():
            return self._send(f.read_bytes(), "application/octet-stream")
        return self._send("not found", "text/plain", 404)

    def do_POST(self):
        p = urllib.parse.urlsplit(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode() if n else "{}"
        if p == "/api/setup":
            try:
                t = json.loads(raw).get("token", "").strip()
            except ValueError:
                return self._send(json.dumps({"ok": False, "error": "bad json"}), "application/json", 400)
            ok, info = check_token(t)
            if not ok:
                return self._send(json.dumps({"ok": False, "error": info}, ensure_ascii=False), "application/json")
            save_token(t)
            run_pipeline()
            return self._send(json.dumps({"ok": True, "档": info}, ensure_ascii=False), "application/json")
        if p == "/api/chat":
            if STATE["running"]:
                return self._send(json.dumps({"ok": False, "error": "正在跑别的任务"}, ensure_ascii=False),
                                  "application/json")
            run_job([["抓会话存档.py", "--days", "30"],
                     ["分析会话.py"],
                     ["build_workbench.py"]], why="chat")
            return self._send(json.dumps({"ok": True}), "application/json")
        if p == "/api/rebuild":
            run_build()
            return self._send(json.dumps({"ok": True}), "application/json")
        return self._send("not found", "text/plain", 404)


if __name__ == "__main__":
    print("=" * 52)
    print(" 用户整理工作台（个人版）")
    print(" 打开： http://127.0.0.1:%d" % PORT)
    print(" 凭证： %s" % ("已保存" if token() else "第一次进来填"))
    print("=" * 52)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as srv:
        srv.serve_forever()
