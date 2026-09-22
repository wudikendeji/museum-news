#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
石家庄博物馆 · 公告实时看 —— 自动实时后端服务
功能：定时抓取各博物馆官网 + 人社系统招聘公告，通过 /api/news 实时提供给前端。
部署后可做到「自动抓取 + 秒级实时」，配合 PWA 前端可添加到手机主屏幕当 App 长期使用。

部署：python3 server.py [--port 8000]   依赖：python3 + requests + beautifulsoup4
建议用 systemd / docker 保持常驻。
"""
import json, os, sys, time, threading, subprocess, datetime, argparse, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(ROOT, "index.html")
CACHE = {"news": [], "renli": [], "ts": "", "lock": threading.Lock()}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"}
MUSEUM_URL = "https://www.hebeimuseum.org.cn/list-79-1.html"
JOB_KEYS = ["招聘", "选聘", "拟聘", "人才", "考录", "招录", "公开选调"]
SEARCH_KEYWORDS = [
    "石家庄市 博物馆 事业单位 招聘 公告",
    "石家庄市 2026 事业单位 招聘 人社局",
    "河北省 事业单位 公开招聘 公告",
]

# 其他博物馆实时公告（每馆一组搜索词，结果按馆归类进 APP）
EXTRA_KEYWORDS = [
    ("河北省科学技术馆", "河北省科学技术馆 通知 公告 动态"),
    ("河北美术馆", "河北美术馆 展览 公告 动态"),
    ("石家庄市博物馆", "石家庄市博物馆 公告 通知"),
    ("西柏坡纪念馆", "西柏坡纪念馆 公告 招聘"),
    ("河北钱币博物馆", "河北钱币博物馆 公告"),
    ("河北地质大学地球科学博物馆", "河北地质大学 地球科学博物馆 公告"),
    ("河北文学馆", "河北文学馆 公告"),
    ("河北省文物考古研究院", "河北省文物考古研究院 公告"),
]
MUSEUM_KEYS = [n for n, _ in EXTRA_KEYWORDS]

# 馆名别名（放宽匹配，提高覆盖）+ 过滤的中介/导流站域名
ALIASES = {
    "河北省科学技术馆": ["科技馆"],
    "河北美术馆": ["美术馆"],
    "石家庄市博物馆": ["市博物馆", "石家庄市博物馆"],
    "西柏坡纪念馆": ["西柏坡"],
    "河北钱币博物馆": ["钱币"],
    "河北地质大学地球科学博物馆": ["地球科学博物馆", "地质大学"],
    "河北文学馆": ["文学馆"],
    "河北省文物考古研究院": ["文物考古研究院", "考古研究院"],
}
BAD_DOMAINS = ["huatu.com", "zgsydw", "jrzp", "kq36", "163.com", "offcn", "eoffcn", "sydw8", "sina", "baidu.com", "sohu", "zhipin", "qiancheng", "ganji.com", "58.com"]
# 标题中命中这些词视为招聘中介/导流，跳过
JUNK_WORDS = ["直聘", "附近招聘", "求职", "招聘网", "招聘信息", "boss直聘", "急招", "高薪"]
SEARCH_SCRIPT = os.path.expanduser("~/.openclaw/workspace/skills/xiaoyi-web-search/scripts/search.js")
REFRESH_SEC = 1800  # 每30分钟自动刷新(可调整)


def fetch(url, timeout=20):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception:
        return ""


def fetch_museum_news():
    items = []
    html = fetch(MUSEUM_URL)
    if not html:
        return items
    soup = BeautifulSoup(html, "html.parser")
    for li in soup.select("li.flex"):
        a = li.find_parent("a")
        if not a:
            continue
        href = a.get("href", "")
        t = li.select_one("span.f16")
        d = li.select_one("p.f14")
        title = t.get_text(strip=True) if t else ""
        date = d.get_text(strip=True) if d else ""
        if not title:
            continue
        url = href if href.startswith("http") else "https://www.hebeimuseum.org.cn" + href
        kind = "hire" if any(k in title for k in JOB_KEYS) else "info"
        items.append({"t": title, "d": date, "u": url, "k": kind, "src": "河北博物院官网"})
    return items


def parse_search(script, keyword):
    """调用 xiaoyi 搜索脚本，返回 (title,url,date) 列表。脚本缺省返回空。"""
    out = []
    if not os.path.exists(script):
        return out
    try:
        p = subprocess.run(["node", script, keyword, "-n", "10"],
                           capture_output=True, text=True, timeout=45,
                           cwd=os.path.dirname(script))
        text = p.stdout
        blocks = text.split("📌")
        for b in blocks[1:]:
            lines = b.splitlines()
            title = ""
            url = ""
            date = ""
            for ln in lines:
                s = ln.strip()
                m = re.match(r"^\d+\.\s*(.+)$", s)
                if m and not title:
                    title = m.group(1).strip()
                if s.startswith("🔗") and not url:
                    url = s.replace("🔗", "").strip()
                dm = re.search(r"(\d{4}-\d{2}-\d{2})", s)
                if dm and not date:
                    date = dm.group(1)
            if title and url and any(k in title for k in JOB_KEYS):
                out.append({"title": title, "url": url, "date": date})
    except Exception as e:
        print("[search err]", e, flush=True)
    return out


def refresh():
    news = fetch_museum_news()
    # 人社/招聘实时
    renli = []
    for kw in SEARCH_KEYWORDS:
        renli.extend(parse_search(SEARCH_SCRIPT, kw))
    # 各博物馆实时公告（搜索覆盖全馆，按馆归类）
    museums = {}
    for name, kw in EXTRA_KEYWORDS:
        got = []
        for it in parse_search(SEARCH_SCRIPT, kw):
            aliases = ALIASES.get(name, [name])
            if not any(a in it["title"] for a in aliases):
                continue
            if any(b in it["url"] for b in BAD_DOMAINS):
                continue
            if any(w in it["title"] for w in JUNK_WORDS):
                continue
            got.append(it)
        seen2, ded = set(), []
        for it in got:
            if it["url"] in seen2:
                continue
            seen2.add(it["url"]); ded.append(it)
        museums[name] = ded[:6]
    # 人社去重
    seen, rr = set(), []
    for it in renli:
        if it["url"] in seen:
            continue
        seen.add(it["url"]); rr.append(it)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CACHE["lock"]:
        CACHE["news"] = news
        CACHE["renli"] = rr[:15]
        CACHE["museums"] = museums
        CACHE["ts"] = now
    total_m = sum(len(v) for v in museums.values())
    print(f"[refresh] {now} news={len(news)} renli={len(rr)} museums={total_m}", flush=True)


def loop():
    while True:
        try:
            refresh()
        except Exception as e:
            print("[refresh err]", e, flush=True)
        time.sleep(REFRESH_SEC)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/news"):
            with CACHE["lock"]:
                self._json({"ts": CACHE["ts"], "news": CACHE["news"], "renli": CACHE["renli"], "museums": CACHE.get("museums", {})})
        elif self.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self._json({"error": "index missing"})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404")

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_snapshot(dest):
    """刷新一次并生成静态快照(data.json + 前端静态文件)，供 GitHub Pages 等静态部署。"""
    refresh()
    os.makedirs(dest, exist_ok=True)
    with CACHE["lock"]:
        data = {"ts": CACHE["ts"], "news": CACHE["news"], "renli": CACHE["renli"], "museums": CACHE["museums"]}
    with open(os.path.join(dest, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for name in ("index.html", "manifest.json", "sw.js", "icon.svg"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            with open(src, "rb") as f, open(os.path.join(dest, name), "wb") as g:
                g.write(f.read())
    print(f"[snapshot] written -> {dest}/ (news={len(data['news'])}, renli={len(data['renli'])})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--snapshot", type=str, default="", help="生成静态快照到目录并退出(供 GitPage 等静态托管)")
    args = ap.parse_args()
    if args.snapshot:
        make_snapshot(args.snapshot)
        return
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    print(f"Serving on :{args.port}")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
