import re
import os
import time
import traceback
import requests
from bs4 import BeautifulSoup
from itertools import count
from datetime import datetime, timedelta

DEBUG = os.getenv("EIGA_DEBUG", "0") == "1"
REQ_ID = count(1)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/121.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# 例: 11:00 / 11：00
time_pat = re.compile(r"\d{1,2}[:：]\d{2}")

# 例: 2/18（
date_pat = re.compile(r"\d{1,2}/\d{1,2}\s*（")

# 例: 100分
duration_pat = re.compile(r"(\d{2,3})\s*分")

# 例: 20:25 ～22:17 / 20：25 〜22：17
pair_pat = re.compile(r"(\d{1,2}[:：]\d{2})\s*[～〜]\s*(\d{1,2}[:：]\d{2})")


def _log(rid: int, msg: str):
    print(f"[SCRAPE#{rid}] {msg}")


def _to_hhmm(s: str) -> str:
    return s.replace("：", ":")


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    hh, mm = hhmm.split(":")
    return int(hh), int(mm)


def _min_of(hhmm: str) -> int:
    h, m = _parse_hhmm(hhmm)
    return h * 60 + m


def _add_minutes(hhmm: str, minutes: int) -> str:
    h, m = _parse_hhmm(hhmm)
    base = datetime(2000, 1, 1, h, m)
    dt2 = base + timedelta(minutes=minutes)
    return f"{dt2.hour:02d}:{dt2.minute:02d}"


def _extract_duration_minutes(head_text: str) -> int | None:
    m = duration_pat.search(head_text)
    if not m:
        return None
    mins = int(m.group(1))
    # 映画として変な値は弾く
    if mins < 30 or mins > 400:
        return None
    return mins


def _extract_pairs(part: str) -> dict[str, str]:
    """
    "開始～終了" を dict[start]=end で返す
    """
    out: dict[str, str] = {}
    for m in pair_pat.finditer(part):
        st = _to_hhmm(m.group(1))
        en = _to_hhmm(m.group(2))
        out[st] = en
    return out


def _extract_start_times(part: str) -> list[str]:
    """
    開始時刻だけ拾う（終了時刻 "～22:17" の 22:17 は除外）
    """
    out = []
    for m in time_pat.finditer(part):
        raw = _to_hhmm(m.group(0))
        i = m.start()

        # 直前の空白を飛ばして1文字見る
        j = i - 1
        while j >= 0 and part[j].isspace():
            j -= 1

        # 直前が「～」or「〜」なら終了時刻なので捨てる
        if j >= 0 and part[j] in ("～", "〜"):
            continue

        out.append(raw)

    # 重複除去（順序維持）
    uniq = []
    for t in out:
        if t not in uniq:
            uniq.append(t)
    return uniq


def get_showtimes(url: str, target_day: str, next_day: str):
    """
    映画.comの劇場ページから、指定日の items を返す
    items: [{"title": str, "times": [str, ...]}, ...]
    times は基本 "HH:MM"、ただし最終回だけ "HH:MM～HH:MM" を混ぜる
    """
    rid = next(REQ_ID)
    try:
        if DEBUG:
            _log(rid, f"START {time.strftime('%H:%M:%S')} url={url} target={target_day} next={next_day}")

        res = requests.get(url, headers=HEADERS, timeout=20)
        res.raise_for_status()

        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        if DEBUG:
            _log(rid, f"WHO in TEXT? {('WHO' in text)} / {('WHO？' in text)}")

        blocks = text.split("すべてのスケジュールを見る")
        items = []

        for block in blocks:
            if "作品情報を見る" not in block:
                continue

            # 「作品情報を見る」より前=タイトル情報、後=スケジュール
            head, tail = block.split("作品情報を見る", 1)

            # 日付検索は tail のみ（上部タブ日付の誤ヒット防止）
            mday = re.search(rf"{re.escape(target_day)}\s*（", tail)
            if not mday:
                continue

            part = tail[mday.end():]

            # （火）など曜日スキップ
            m_wd = re.match(r"\s*[^）]*）\s*", part)
            if m_wd:
                part = part[m_wd.end():]

            # 次の日付でカット
            nxt = date_pat.search(part)
            if nxt:
                part = part[:nxt.start()]

            # ----- タイトル抽出（販売終了以降優先）-----
            if "販売終了" in head:
                head2 = head.split("販売終了", 1)[1]
            else:
                head2 = head
            head2 = " ".join(head2.split())

            mtitle = re.search(r"(.+?)\s+\d+\.\d+\s+", head2)
            if mtitle:
                title = mtitle.group(1).strip()
            else:
                mtitle2 = re.search(r"(.+?)\s+\d{1,4}年\d{1,2}月\d{1,2}日公開", head2)
                if mtitle2:
                    title = mtitle2.group(1).strip()
                else:
                    title = " ".join(head2.split()[-8:]).strip()

            title = re.sub(r"\s+", " ", title).strip()

            # 上映時間（分）— 終了が無い最終回の推定用
            duration = _extract_duration_minutes(head2)

            # ----- 時刻抽出 -----
            # 明示の "開始～終了"（あれば最優先）
            start_to_end = _extract_pairs(part)

            # 開始時刻一覧
            starts = _extract_start_times(part)
            if not starts:
                continue

            # 並びを保証（開始で昇順）
            starts_sorted = sorted(starts, key=_min_of)

            # 最終回 start
            last_start = starts_sorted[-1]

            # 最終回の end を決定
            last_end = start_to_end.get(last_start)
            if last_end is None and duration is not None:
                last_end = _add_minutes(last_start, duration)

            # 表示用 times を作る（最終回だけ "～" 付き）
            display_times: list[str] = []
            for st in starts_sorted:
                if st == last_start and last_end:
                    display_times.append(f"{st}～{last_end}")
                else:
                    display_times.append(st)

            if DEBUG and ("who" in title.lower() or "WHO" in title or "WHO？" in title):
                _log(rid, f"HIT title={title!r} duration={duration} times={display_times}")

            items.append({"title": title, "times": display_times})

        if DEBUG:
            _log(rid, f"DONE items={len(items)}")

        return items

    except Exception as e:
        _log(rid, f"ERROR url={url} -> {repr(e)}")
        _log(rid, traceback.format_exc())
        return []
