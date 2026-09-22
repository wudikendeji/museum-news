#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""石家庄博物馆·公告实时看 —— 纯官网直抓版（不依赖任何密钥，GitHub Actions 可实时运行）
实时抓取：各博物馆官网 + 教育考试院 + 文物局 + 人社局的公开招聘/考试公告。
"""
import re, json, time, os, sys, datetime, threading
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# ---------- 常量 ----------
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}
MUSEUM_URL = "https://www.hebeimuseum.org.cn/list-79-1.html"   # 河北博物院公告列表
TECH_URL   = "https://www.hbstm.cn/"                            # 省科技馆
XBP_URL    = "http://www.xbpjng.cn/"                             # 西柏坡纪念馆
DQBWG_URL  = "https://dqbwg.hgu.edu.cn/"                         # 河北地质大学博物馆
KG_URL     = "https://www.hbswwkg.com/node_358734.html"          # 省文物考古研究院公告
RL_URL     = "https://rsj.sjz.gov.cn/"                           # 石家庄市人社局首页
EDU_URLS   = ["https://www.hebeea.edu.cn/zxdt/index.html",       # 教育考试院·最新动态
              "https://www.hebeea.edu.cn/ptgk/tzgg/index.html"]  # 教育考试院·普通高考通知
WWJ_URL    = "https://wenwu.hebei.gov.cn/tzgg/"                  # 省文物局·通知公告

# 各馆官网（有独立官网的）—— 只保留招聘/考试公告
MUSEUM_SOURCES = [
    ("河北省文物考古研究院", KG_URL),
    ("西柏坡纪念馆", XBP_URL),
    ("河北省科学技术馆", TECH_URL),
    ("河北地质大学地球科学博物馆", DQBWG_URL),
]
# 官方信息源 —— 招聘/考试公告
OFFICIAL_SOURCES = [
    ("河北省教育考试院", EDU_URLS),
    ("河北省文物局", [WWJ_URL]),
    ("河北人社", [RL_URL]),
]

# 统一公告过滤：只保留「招聘/考试/招生」相关
FILTER_KEYS = ["招聘","考试","选聘","招录","考录","报名","笔试","面试","拟聘",
               "招考","录用","成绩","准考证","招生","录取"]

def keep(it):
    t = it.get("title", "") or it.get("t", "") if isinstance(it, dict) else str(it)
    return any(k in t for k in FILTER_KEYS)

DATE_RES = [
    re.compile(r"(\d{4})[-年\.](\d{1,2})[-月\.](\d{1,2})"),      # 2026-09-17 / 2026年9月17日
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),                        # URL /c/2026-09-17/
    re.compile(r"/columns/[^/]+/(\d{6})/(\d{2})/"),               # /columns/xxx/202608/10/
    re.compile(r"/(\d{4})/(\d{2})/(\d{2})"),                      # /2026/08/10/
]
def pick_date(text, href):
    for rx in DATE_RES:
        for s in (text, href):
            m = rx.search(s)
            if m:
                try: return "%s-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except Exception: pass
    return ""

# ---------- 抓取 ----------
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

def fetch(url, timeout=25, retries=3):
    """带重试 + http/https 双通道回退 + 关闭证书校验的健壮抓取。"""
    urls = [url]
    if url.startswith("https://"):
        urls.append(url.replace("https://", "http://", 1))
    last = None
    for u in urls:
        for i in range(retries):
            try:
                r = requests.get(u, headers=UA, timeout=timeout, allow_redirects=True, verify=False)
                if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
                    r.encoding = "utf-8"
                if r.status_code == 200 and len(r.text) > 200:
                    return r.text
                print("[fetch weak]", u, r.status_code, len(r.text), flush=True)
                last = "status"
            except Exception as e:
                print("[fetch err]", u, str(e)[:40], flush=True)
                last = e
                time.sleep(min(3 * (i + 1), 8))
    return ""

def extract_list(url):
    """通用公告列表抓取：从标题或链接提取日期，返回 [{title,date,url}]。"""
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    skip = {"首页","下一页","上一页","更多","更多》", ">", "·"}
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        raw = a["href"].strip()
        if not t or len(t) < 8 or t in skip or raw.startswith("javascript") or raw == "#":
            continue
        href = urljoin(url, raw)
        date = pick_date(t, href)
        if not date:
            continue
        title = re.sub(r"[\[\（(]\d{4}[-年/\.]\d{1,2}[-月/\.]\d{1,2}[\]\）)]?", "", t).strip("· |\t")
        if href not in seen:
            seen.add(href)
            out.append({"title": title, "date": date, "url": href})
    return out

def fetch_museum_news():
    """河北博物院公告列表（专用解析 li.flex 结构）。"""
    items = []
    html = fetch(MUSEUM_URL)
    if not html:
        return items
    soup = BeautifulSoup(html, "html.parser")
    for li in soup.select("li.flex"):
        a = li.find_parent("a")
        if not a:
            continue
        t = li.select_one("span.f16")
        d = li.select_one("p.f14")
        title = t.get_text(strip=True) if t else ""
        date = d.get_text(strip=True) if d else ""
        if not title:
            continue
        url = a.get("href", "")
        url = url if url.startswith("http") else "https://www.hebeimuseum.org.cn" + url
        items.append({"t": title, "d": date, "u": url, "k": "hire" if keep({"t": title}) else "info"})
    return items

# ---------- 刷新 ----------
CACHE = {"lock": threading.Lock(), "news": [], "renli": [], "museums": {}, "official": {}, "ts": ""}

def refresh():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    news = [x for x in fetch_museum_news() if keep(x)]
    renli = [{"t": x["title"], "d": x.get("date", ""), "u": x["url"], "s": "石家庄市人社局"}
             for x in extract_list(RL_URL) if keep(x)][:15]
    museums = {name: [x for x in extract_list(url) if keep(x)][:6] for name, url in MUSEUM_SOURCES}
    official = {}
    for name, urls in OFFICIAL_SOURCES:
        got, seen = [], set()
        for u in urls:
            for x in extract_list(u):
                if x["url"] in seen:
                    continue
                seen.add(x["url"])
                if keep(x):
                    got.append(x)
        official[name] = got[:6]
    with CACHE["lock"]:
        CACHE["news"] = news
        CACHE["renli"] = renli
        CACHE["museums"] = museums
        CACHE["official"] = official
        CACHE["ts"] = now
    print("[refresh]", now, "news=%d renli=%d museums=%s official=%s" %
          (len(news), len(renli), {k: len(v) for k, v in museums.items()}, {k: len(v) for k, v in official.items()}), flush=True)

# ---------- HTTP / Snapshot ----------
def make_snapshot(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    refresh()
    with CACHE["lock"]:
        data = {"ts": CACHE["ts"], "news": CACHE["news"], "renli": CACHE["renli"],
                "museums": CACHE["museums"], "official": CACHE["official"]}
    # 同步前端同目录副本（若存在）
    html_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    html_dst = os.path.join(out_dir, "index.html")
    try:
        import shutil; shutil.copyfile(html_src, html_dst)
    except Exception as e:
        print("[copy index]", e, flush=True)
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # 复制静态资源
    for fn in ("manifest.json", "sw.js", "icon.svg"):
        try:
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
            if os.path.exists(src):
                import shutil; shutil.copyfile(src, os.path.join(out_dir, fn))
        except Exception:
            pass
    print("[snapshot] written -> %s (news=%d, renli=%d)" % (out_dir, len(news := data["news"]), len(data["renli"])), flush=True)

def main():
    if "--snapshot" in sys.argv:
        i = sys.argv.index("--snapshot")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else "./docs"
        make_snapshot(out)
        return
    from http.server import BaseHTTPRequestHandler, HTTPServer
    refresh()
    t = threading.Thread(target=lambda: (time.sleep(1800), refresh()), daemon=True)
    port = int(os.environ.get("PORT", "8000"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            if self.path.startswith("/api/news"):
                with CACHE["lock"]:
                    body = json.dumps({"ts": CACHE["ts"], "news": CACHE["news"], "renli": CACHE["renli"],
                                       "museums": CACHE.get("museums", {}), "official": CACHE.get("official", {})},
                                      ensure_ascii=False)
                b = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
            else:
                self.send_response(404); self.end_headers()
    print("server on :%d" % port, flush=True)
    HTTPServer(("0.0.0.0", port), H).serve_forever()

if __name__ == "__main__":
    main()
