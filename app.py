import os
import time
import unicodedata
import re
from typing import List, Dict, Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from scrape import get_showtimes

app = FastAPI()

# static 配信（PWAのmanifest/sw/iconsを配る）
app.mount("/static", StaticFiles(directory="static"), name="static")

DEBUG = os.getenv("EIGA_DEBUG", "0") == "1"

THEATERS = [
    ("シネプレックスつくば", "https://eiga.com/theater/8/80401/3211/"),
    ("MOVIXつくば", "https://eiga.com/theater/8/80401/3212/"),
    ("USシネマつくば", "https://eiga.com/theater/8/80401/3253/"),
    ("土浦セントラルシネマズ", "https://eiga.com/theater/8/80201/3209/"),
    ("シネマサンシャイン土浦", "https://eiga.com/theater/8/80201/3208/"),
    ("柏キネマ旬報シアター", "https://eiga.com/theater/12/120208/3251/"),
    ("TOHOシネマズ柏", "https://eiga.com/theater/12/120208/3269/"),
    ("TOHOシネマズ 流山おおたかの森", "https://eiga.com/theater/12/120204/"),
    ("グランドシネマサンシャイン池袋", "https://eiga.com/theater/13/130501/3291/"),
]

_CACHE = {"ts": 0.0, "data": []}
CACHE_SECONDS = 300  # 5分


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower().strip()
    s = s.replace("？", "?")

    # 記号・スペース削除
    s = re.sub(r"[^\wぁ-んァ-ン一-龥]", "", s)

    return s


def _today_md() -> str:
    t = time.localtime()
    return f"{t.tm_mon}/{t.tm_mday}"


def _next_day_md() -> str:
    lt = time.localtime(time.time() + 24 * 60 * 60)
    return f"{lt.tm_mon}/{lt.tm_mday}"


def fetch_all_theaters() -> List[Dict[str, Any]]:
    target_day = _today_md()
    next_day = _next_day_md()

    all_items: List[Dict[str, Any]] = []
    for theater_name, url in THEATERS:
        try:
            items = get_showtimes(url, target_day, next_day)

            if items is None or not isinstance(items, list):
                if DEBUG:
                    print(f"[APP] get_showtimes returned invalid: {theater_name} {url} -> {type(items)}")
                items = []

            for it in items:
                all_items.append(
                    {
                        "theater": theater_name,
                        "theater_url": url,  # ★カードタップで飛ばす先（劇場ページ）
                        "title": it.get("title", ""),
                        "times": it.get("times", []),  # ★Last回は "～終了" が混ざる想定
                    }
                )

        except Exception as e:
            if DEBUG:
                print(f"[APP] ERROR: {theater_name} {url} -> {repr(e)}")
            continue

    return all_items


def get_cached_all() -> List[Dict[str, Any]]:
    now = time.time()
    if (now - _CACHE["ts"]) < CACHE_SECONDS and _CACHE["data"]:
        return _CACHE["data"]
    data = fetch_all_theaters()
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data


def _page(title: str, q: str, body_html: str) -> str:
    css = """
    :root{
      --bg:#0b0d12;
      --muted:#9aa4b2;
      --text:#eef2ff;
      --accent:#6ee7ff;
      --border:rgba(255,255,255,.08);
      --shadow: 0 10px 30px rgba(0,0,0,.35);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans JP", sans-serif;
      background: radial-gradient(1200px 700px at 20% -10%, rgba(110,231,255,.15), transparent 60%),
                  radial-gradient(900px 600px at 90% 0%, rgba(167,139,250,.14), transparent 55%),
                  var(--bg);
      color:var(--text);
    }
    .wrap{max-width:920px;margin:0 auto;padding:18px 14px 40px}
    .title{font-size:22px;font-weight:800;letter-spacing:.02em;margin:6px 0 14px}
    .sub{color:var(--muted);font-size:13px;margin:0 0 14px}
    .box{
      background:rgba(255,255,255,.03);
      border:1px solid var(--border);
      border-radius:16px;
      padding:14px;
      box-shadow: var(--shadow);
    }
    form{display:flex; gap:10px; align-items:stretch; flex-wrap:wrap;}
    .input{
      flex: 1 1 260px;
      min-width: 0;
      padding:12px 12px;
      font-size:16px;
      border-radius:12px;
      border:1px solid var(--border);
      background:rgba(0,0,0,.25);
      color:var(--text);
      outline:none;
    }
    .input::placeholder{color:rgba(154,164,178,.7)}
    .btn{
      padding:12px 14px;
      font-size:16px;
      border-radius:12px;
      border:1px solid var(--border);
      background: linear-gradient(135deg, rgba(110,231,255,.25), rgba(167,139,250,.18));
      color:var(--text);
      font-weight:700;
      cursor:pointer;
      min-width:88px;
    }
    .btn:active{transform:translateY(1px)}
    .meta{margin-top:12px;color:var(--muted);font-size:13px;margin-bottom:6px}
    .results{margin-top:10px;display:grid;gap:10px}

    /* 1作品=1カード（カード全体リンク） */
    .cardlink{
      display:block;
      text-decoration:none;
      color:inherit;
      border-radius:16px;
      outline:none;
    }
    .card{
      background: rgba(255,255,255,.03);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 12px 12px;
      transition: transform .06s ease, border-color .06s ease, background .06s ease;
    }
    .cardlink:active .card{transform: translateY(1px)}
    .cardlink:hover .card{border-color: rgba(110,231,255,.25)}
    .movie{font-size:16px;font-weight:900;margin:0 0 6px;line-height:1.25}
    .theater{color:var(--muted);font-size:13px}
    .times{
      margin-top:8px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size:14px;
      color: var(--accent);
      line-height:1.55;
      word-break: break-word;
    }
    .empty{
      margin-top:14px;
      padding:14px;
      border-radius:16px;
      border:1px dashed var(--border);
      color:var(--muted);
      background: rgba(255,255,255,.02);
    }
    .footer{
      margin-top:18px;
      color:rgba(154,164,178,.7);
      font-size:12px;
    }
    @media (max-width: 420px){
      .title{font-size:20px}
      form{gap:8px}
      .btn{width:100%; min-width:0}
    }
    """

    # PWA用のhead追加（manifest / theme / iOS）
    pwa_head = """
        <link rel="manifest" href="/static/manifest.webmanifest">
        <meta name="theme-color" content="#0b0d12">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="default">
        <link rel="apple-touch-icon" href="/static/icons/icon-192.png">
    """

    # Service Worker登録（</body>直前）
    sw_register = """
        <script>
          if ("serviceWorker" in navigator) {
            window.addEventListener("load", () => {
              navigator.serviceWorker.register("/static/sw.js");
            });
          }
        </script>
    """

    return f"""
    <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        {pwa_head}
        <style>{css}</style>
      </head>
      <body>
        <div class="wrap">
          <div class="title">{title}</div>
          <div class="sub">映画タイトルで検索（例：WHO / 国宝 / 僕の心のヤバイやつ）</div>

          <div class="box">
            <form method="get" action="/">
              <input class="input" name="q" value="{q}" placeholder="映画タイトル" autocomplete="off" />
              <button class="btn" type="submit">検索</button>
            </form>
            <div class="meta">※検索したときだけ取得（キャッシュあり）</div>
          </div>

          {body_html}

          <div class="footer">カードを押すと劇場の上映ページへ飛びます（そこから購入導線）</div>
        </div>
        {sw_register}
      </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def index(q: str = Query(default="")):
    q2 = _norm(q)

    # =========================
    # 初期画面（検索してないとき）
    # =========================
    if not q2:
        body = """
        <div class="meta">登録済み映画館</div>
        <div class="box" style="margin-top:10px;">
          <ul style="margin:0; padding-left:18px; line-height:1.9;">
            {items}
          </ul>
        </div>
        """

        items = "\n".join(
            f'<li><a href="{url}" target="_blank" rel="noopener noreferrer" style="color:inherit;">{name}</a></li>'
            for name, url in THEATERS
        )

        return _page("上映検索", q, body.format(items=items))

    # =========================
    # 検索したとき（既存ロジック）
    # =========================
    all_items = get_cached_all()

    filtered = [x for x in all_items if q2 in _norm(x.get("title", ""))]

    if not filtered:
        body = f'<div class="empty">「{q}」に一致する上映が見つからなかった。</div>'
        return _page("上映検索", q, body)

    cards = []
    cards.append(f'<div class="meta">ヒット件数: {len(filtered)}</div>')
    cards.append('<div class="results">')

    for x in filtered:
        theater = x.get("theater", "")
        title = x.get("title", "")
        times = "　".join(x.get("times", []))
        url = x.get("theater_url", "#")

        cards.append(
            f"""
            <a class="cardlink" href="{url}" target="_blank" rel="noopener noreferrer">
              <div class="card">
                <div class="theater">{theater}</div>
                <div class="movie">{title}</div>
                <div class="times">{times}</div>
              </div>
            </a>
            """
        )

    cards.append("</div>")

    return _page("上映検索", q, "\n".join(cards))


@app.head("/")
def head_root():
    return HTMLResponse("")
