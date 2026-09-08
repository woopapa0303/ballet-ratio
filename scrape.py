#!/usr/bin/env python3
"""
2027학년도 수시 무용(발레) 경쟁률 수집기.

각 대학이 공개 운영하는 실시간 지원현황 페이지(로그인 불필요)를 읽어
무용 전공 트랙별 모집/지원/경쟁률을 추출하고, index.html 을 생성한다.

의존성 없음(표준 라이브러리만 사용) — GitHub Actions에서 그대로 실행된다.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------- config

SCHOOLS = [
    {
        "key": "kookmin",
        "name": "국민대학교",
        "campus": "",
        "dept": "예술대학 공연예술학부 · 실기/실적위주(무용실기우수자)",
        "url": "http://ratio.uwayapply.com/Sl5KVyVNOWFhOUpmJSY6Jko3ZlRm",
        "period": "09.07 ~ 09.11 18:00",
    },
    {
        "key": "dongduk",
        "name": "동덕여자대학교",
        "campus": "",
        "dept": "공연예술대학 · 실기우수자전형",
        "url": "http://ratio.uwayapply.com/Sl5KOTpWcldhVkpmJSY6Jko3ZlRm",
        "period": "09.07 ~ 09.11 18:00",
    },
    {
        "key": "sangmyung",
        "name": "상명대학교",
        "campus": "서울",
        "dept": "스포츠무용학부 · 실기/실적(실기전형)",
        "url": "http://ratio.uwayapply.com/Sl5KOk0mSmYlJjomSjdmVGY=",
        "period": "09.07 ~ 09.11 18:00",
    },
    # 접수 시작일이 09.08 인 대학들 (경쟁률 주소 확인 완료)
    {
        "key": "khu",
        "name": "경희대학교",
        "campus": "서울·경기",
        "dept": "무용학부",
        "url": "https://ratio.uwayapply.com/Sl5KOnw5SmYlJjomSjdmVGY=",
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "cau",
        "name": "중앙대학교",
        "campus": "서울",
        "dept": "무용예술전공",
        "url": "https://ratio.uwayapply.com/Sl5KOjhMSmYlJjomSjdmVGY=",
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "dankook",
        "name": "단국대학교",
        "campus": "경기·충남",
        "dept": "무용과",
        "url": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio10420521.html",
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "sungshin",
        "name": "성신여자대학교",
        "campus": "서울",
        "dept": "무용예술학과",
        "url": "https://addon.jinhakapply.com/RatioV1/RatioH/Ratio10930201.html",
        "period": "09.08 ~ 09.11 18:00",
    },
]

TRACK_RE = re.compile(r"발레|한국무용|현대무용")
RATIO_RE = re.compile(r"^\d+(?:\.\d+)?\s*:\s*1$")
STAMP_RE = re.compile(r"(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d{2})시\s*(\d{2})분\s*기준")
STAMP_RE2 = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s*(오전|오후)\s*(\d{1,2}):(\d{2})")

# 진학어플라이 접수 대학은 이 목록에서 경쟁률 페이지 주소를 자동으로 찾는다.
JINHAK_LIST_URL = "https://apply.jinhakapply.com/SmartRatio"
JINHAK_ROW_RE = re.compile(r'\["[^"\[\]]+",[^\[\]]*\]')

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


# ---------------------------------------------------------------- fetch

def fetch(url, timeout=25):
    """페이지를 내려받아 문자열로 반환. 인코딩은 meta charset → utf-8 → euc-kr 순으로 시도."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()

    head = raw[:4096].decode("ascii", "ignore").lower()
    m = re.search(r'charset=["\']?\s*([\w-]+)', head)
    candidates = []
    if m:
        candidates.append(m.group(1))
    candidates += ["utf-8", "euc-kr", "cp949"]

    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- parse

def strip_tags(fragment):
    """태그를 제거하고 공백을 정리한 텍스트."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_rows(html):
    """무용 트랙(발레/한국무용/현대무용) 행을 [{track, capacity, applicants, ratio}] 로 반환."""
    out = []
    for row_html in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        cells = [strip_tags(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row_html)]
        cells = [c for c in cells if c != ""]
        if len(cells) < 4:
            continue

        name = next((c for c in cells if TRACK_RE.search(c)), None)
        if name is None:
            continue
        # 소계/합계 행은 트랙 행이 아니다.
        if any(k in name for k in ("소계", "합계", "총계")):
            continue
        # '실기우수자전형(한국무용·현대무용·발레)' 처럼 여러 전공을 묶은 전형 행은
        # 개별 트랙이 아니므로 제외한다(발레로 잘못 집계되는 것을 막는다).
        if len(set(TRACK_RE.findall(name))) > 1:
            continue

        ratio = cells[-1]
        if not RATIO_RE.match(ratio):
            continue
        capacity, applicants = cells[-3], cells[-2]
        if not (capacity.isdigit() and applicants.isdigit()):
            continue

        if "발레" in name:
            track = "발레"
        elif "한국무용" in name:
            track = "한국무용"
        else:
            track = "현대무용"

        out.append(
            {
                "track": track,
                "label": name,
                "capacity": int(capacity),
                "applicants": int(applicants),
                "ratio": float(ratio.split(":")[0].strip()),
            }
        )

    # 같은 행이 요약표와 상세표에 중복으로 실리는 경우가 있어 중복 제거
    seen, unique = set(), []
    for row in out:
        sig = (row["label"], row["capacity"], row["applicants"], row["ratio"])
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(row)
    return unique


def parse_stamp(html):
    """대학별 기준시각 표기를 '09.07 14:00' 형태로 정규화."""
    text = strip_tags(html)

    m = STAMP_RE.search(text)          # 유웨이: 2026년 09월 07일 14시 00분 기준
    if m:
        _, mo, d, h, mi = m.groups()
        return f"{mo}.{d} {h}:{mi}"

    m = STAMP_RE2.search(text)         # 진학어플라이: 2026-09-07 오후 2:50
    if m:
        _, mo, d, ampm, h, mi = m.groups()
        h = int(h) % 12
        if ampm == "오후":
            h += 12
        return f"{mo}.{d} {h:02d}:{mi}"

    return None


def discover_jinhak_urls():
    """진학어플라이 스마트경쟁률 목록에서 {학교명: 경쟁률페이지 주소} 를 만든다.

    화면의 링크는 자바스크립트가 그려내므로 HTML 에는 <a> 태그가 없다.
    대신 본문에 대학별 정보가 JSON 배열로 박혀 있어 그것을 읽는다.
    배열 모양: ["학교명", 4, "수시", "수시모집", 지역, 설립, 시작일시, 종료일시,
               안내주소, 상태, "경쟁률 페이지 주소", ...]
    """
    try:
        html = fetch(JINHAK_LIST_URL)
    except Exception as exc:
        print(f"[warn] 진학어플라이 목록을 읽지 못했습니다: {exc}", file=sys.stderr)
        return {}

    html = html.replace("&quot;", '"')
    found = {}
    for raw in JINHAK_ROW_RE.findall(html):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not row or not isinstance(row[0], str):
            continue

        name = row[0].strip()
        url = None
        if len(row) > 10 and isinstance(row[10], str) and row[10].startswith("http"):
            url = row[10]
        else:  # 배열 모양이 달라졌을 때를 위한 대비
            url = next(
                (
                    v
                    for v in row
                    if isinstance(v, str)
                    and v.startswith("http")
                    and re.search(r"ratio|rate", v, re.I)
                ),
                None,
            )
        if name and url:
            found.setdefault(name, url)
    return found


def match_jinhak(name, table):
    """학교명으로 경쟁률 주소를 찾는다.

    진학어플라이 표기가 '중앙대학교(서울)' 처럼 캠퍼스가 붙어 나올 수 있어
    정확히 같지 않아도 한쪽이 다른 쪽으로 시작하면 같은 학교로 본다.
    """
    if name in table:
        return table[name]

    base = name.replace(" ", "")
    for key, url in table.items():
        k = key.replace(" ", "")
        if k.startswith(base) or base.startswith(k):
            print(f"[정보] '{name}' → 진학어플라이 표기 '{key}' 로 매칭", file=sys.stderr)
            return url
    return None


# ---------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"schools": {}, "history": []}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- collect

def collect():
    state = load_state()
    now = datetime.now(KST)
    results = []

    # 접수가 시작된 진학어플라이 대학의 경쟁률 주소를 자동으로 찾는다.
    need_discovery = any(s["url"] is None for s in SCHOOLS)
    jinhak = discover_jinhak_urls() if need_discovery else {}
    if jinhak:
        print(f"진학어플라이 목록에서 {len(jinhak)}개 대학 경쟁률 주소 확인", file=sys.stderr)

    for school in SCHOOLS:
        prev = state["schools"].get(school["key"], {})
        entry = dict(school)
        entry["tracks"] = []
        entry["stamp"] = None
        entry["stale"] = False
        entry["status"] = "pending"

        url = school["url"] or match_jinhak(school["name"], jinhak)
        entry["url"] = url

        if not url:
            # 아직 경쟁률 페이지가 열리지 않은 대학
            results.append(entry)
            continue

        try:
            html = fetch(url)
            tracks = parse_rows(html)
            stamp = parse_stamp(html)
            if not tracks:
                raise ValueError("무용 트랙 행을 찾지 못했습니다")
            entry["tracks"] = tracks
            entry["stamp"] = stamp
            entry["status"] = "live"
        except Exception as exc:  # 네트워크 오류·구조 변경 등
            print(f"[warn] {school['name']}: {exc}", file=sys.stderr)
            if prev.get("tracks"):
                entry["tracks"] = prev["tracks"]
                entry["stamp"] = prev.get("stamp")
                entry["status"] = "live"
                entry["stale"] = True

        # 직전 확인 시점 대비 지원자 증감
        prev_by_label = {t["label"]: t for t in prev.get("tracks", [])}
        for t in entry["tracks"]:
            before = prev_by_label.get(t["label"])
            t["delta"] = (
                t["applicants"] - before["applicants"] if before else 0
            )

        results.append(entry)

    # 여기서는 저장하지 않는다. 값이 실제로 바뀌었을 때만 main() 이 저장한다.
    # (매번 저장하면 data.json 이 계속 바뀌어 불필요한 커밋과 화면 재로딩이 생긴다.)
    return results, now, state


# ---------------------------------------------------------------- render

def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_delta(delta):
    if delta > 0:
        return f'<span class="delta up">▲ {delta}</span>'
    if delta < 0:
        return f'<span class="delta down">▼ {abs(delta)}</span>'
    return '<span class="delta flat">–</span>'


def render_card(entry):
    if entry["status"] != "live":
        return f"""
    <article class="card pending">
      <div class="card-head">
        <div>
          <h3>{esc(entry['name'])}{f'<span class="campus"> · {esc(entry["campus"])}</span>' if entry['campus'] else ''}</h3>
          <p class="dept">{esc(entry['dept'])}</p>
        </div>
        <span class="pill pending">접수예정</span>
      </div>
      <p class="pending-body">접수기간 <b>{esc(entry['period'])}</b>. 접수가 시작되면 이 자리에 발레 경쟁률이 자동으로 채워집니다.</p>
    </article>"""

    ballets = [t for t in entry["tracks"] if t["track"] == "발레"]
    others = [t for t in entry["tracks"] if t["track"] != "발레"]

    if len(ballets) == 1:
        b = ballets[0]
        headline = f"""
      <div class="headline">
        <div class="track">{esc(b['label'])}<br><span class="nums">모집 {b['capacity']} · 지원 {b['applicants']} {render_delta(b['delta'])}</span></div>
        <div class="ratio">{b['ratio']:.2f}<span> : 1</span></div>
      </div>"""
    elif ballets:
        cap = sum(t["capacity"] for t in ballets)
        app = sum(t["applicants"] for t in ballets)
        dlt = sum(t["delta"] for t in ballets)
        agg = app / cap if cap else 0
        headline = f"""
      <div class="headline">
        <div class="track">발레 <span class="nums">({len(ballets)}개 전형 합계)</span><br><span class="nums">모집 {cap} · 지원 {app} {render_delta(dlt)}</span></div>
        <div class="ratio">{agg:.2f}<span> : 1</span></div>
      </div>"""
        others = ballets + others
    else:
        headline = '<div class="headline"><div class="track">발레 모집단위를 찾지 못했습니다</div></div>'

    counts = {}
    for t in others:
        counts[t["track"]] = counts.get(t["track"], 0) + 1

    rows = "".join(
        f"""
        <div class="track-row">
          <span class="t-name">{esc(t['label'] if counts[t['track']] > 1 else t['track'])}</span>
          <span class="t-nums"><span class="n">{t['capacity']}명 모집 · {t['applicants']}명 지원</span><span class="r">{t['ratio']:.2f} : 1</span></span>
        </div>"""
        for t in others
    )

    stale = '<span class="stale">갱신 지연</span>' if entry["stale"] else ""

    return f"""
    <article class="card live">
      <div class="card-head">
        <div>
          <h3>{esc(entry['name'])}{f'<span class="campus"> · {esc(entry["campus"])}</span>' if entry['campus'] else ''}</h3>
          <p class="dept">{esc(entry['dept'])}</p>
        </div>
        <span class="pill live">접수중</span>
      </div>{headline}
      <div class="tracks">{rows}
      </div>
      <div class="card-foot">
        <span>{esc(entry['stamp'] or '')} 기준 {stale}</span>
        <a href="{esc(entry['url'])}" target="_blank" rel="noopener">대학 원문 ↗</a>
      </div>
    </article>"""


def render(results, now):
    live = [e for e in results if e["status"] == "live"]
    pending = [e for e in results if e["status"] != "live"]

    stamps = [e["stamp"] for e in live if e["stamp"]]
    basis = max(stamps) if stamps else "–"

    ballet_apps = sum(
        t["applicants"] for e in live for t in e["tracks"] if t["track"] == "발레"
    )
    ballet_caps = sum(
        t["capacity"] for e in live for t in e["tracks"] if t["track"] == "발레"
    )
    overall = f"{ballet_apps / ballet_caps:.2f}" if ballet_caps else "–"

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>발레 경쟁률 보드</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🩰</text></svg>">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800;900&family=IBM+Plex+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600;700&display=swap">
<style>
  :root{{
    --bg:#14181d; --panel:#1b212a; --panel-2:#212a35;
    --line:#2b3542; --line-soft:#242c37;
    --ink:#f3f1ea; --muted:#8b93a3; --muted-2:#5f6774;
    --accent:#eb9e4b; --accent-dim:#4a3a24;
    --good:#49b881; --good-dim:#173226;
    --up:#ff7a6b; --down:#6ea8ff;
    --pending:#93a0b3; --pending-dim:#242c37;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font-family:'IBM Plex Sans KR',ui-sans-serif,system-ui,sans-serif;
    -webkit-font-smoothing:antialiased}}
  .wrap{{max-width:1080px;margin:0 auto;padding:32px 18px 64px}}

  header{{display:flex;flex-direction:column;gap:12px;
    padding-bottom:24px;border-bottom:1px solid var(--line);margin-bottom:24px}}
  .eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:11.5px;
    letter-spacing:.14em;text-transform:uppercase;color:var(--accent);
    display:flex;align-items:center;gap:8px}}
  .eyebrow::before{{content:"";width:7px;height:7px;border-radius:50%;
    background:var(--accent);box-shadow:0 0 0 3px var(--accent-dim);
    animation:blink 2.4s infinite}}
  @keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
  h1{{font-family:'Archivo','IBM Plex Sans KR',sans-serif;font-weight:900;
    font-size:clamp(26px,4.2vw,40px);letter-spacing:-.01em;margin:0}}
  .sub{{color:var(--muted);font-size:14.5px;line-height:1.65;max-width:62ch}}
  .sub b{{color:var(--ink);font-weight:600}}

  .strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
    background:var(--line);border:1px solid var(--line);border-radius:10px;
    overflow:hidden;margin-bottom:30px}}
  .stat{{background:var(--panel);padding:14px 16px;display:flex;
    flex-direction:column;gap:5px}}
  .stat .label{{font-size:11px;letter-spacing:.06em;color:var(--muted-2)}}
  .stat .value{{font-family:'IBM Plex Mono',monospace;font-variant-numeric:tabular-nums;
    font-size:22px;font-weight:600}}
  .stat .value.good{{color:var(--good)}}
  .stat .value.accent{{color:var(--accent)}}

  .section-title{{display:flex;align-items:baseline;gap:9px;margin:0 0 12px}}
  .section-title h2{{font-family:'Archivo',sans-serif;font-weight:800;font-size:14px;
    letter-spacing:.03em;margin:0;text-transform:uppercase}}
  .section-title .count{{font-family:'IBM Plex Mono',monospace;color:var(--muted);font-size:12.5px}}

  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
    gap:13px;margin-bottom:34px}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:18px;display:flex;flex-direction:column;gap:13px}}
  .card.live{{border-color:#33413a}}
  .card-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}}
  .card-head h3{{font-family:'Archivo','IBM Plex Sans KR',sans-serif;font-weight:800;
    font-size:18px;line-height:1.25;margin:0}}
  .campus{{color:var(--muted);font-weight:500}}
  .dept{{color:var(--muted);font-size:12px;margin:3px 0 0}}

  .pill{{display:inline-flex;align-items:center;gap:6px;padding:4px 10px 4px 8px;
    border-radius:999px;font-family:'IBM Plex Mono',monospace;font-size:11px;
    font-weight:600;white-space:nowrap;flex:none}}
  .pill.live{{background:var(--good-dim);color:var(--good)}}
  .pill.live::before{{content:"";width:6px;height:6px;border-radius:50%;
    background:var(--good);animation:blink 1.8s infinite}}
  .pill.pending{{background:var(--pending-dim);color:var(--pending)}}
  .pill.pending::before{{content:"";width:6px;height:6px;border-radius:50%;background:var(--pending)}}

  .headline{{background:var(--panel-2);border:1px solid var(--line-soft);border-radius:9px;
    padding:13px 15px;display:flex;align-items:center;justify-content:space-between;gap:10px}}
  .headline .track{{font-size:13px;color:var(--ink);font-weight:600;line-height:1.5}}
  .headline .nums{{color:var(--muted);font-weight:400;font-size:12px}}
  .headline .ratio{{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:25px;
    color:var(--accent);font-variant-numeric:tabular-nums;white-space:nowrap}}
  .headline .ratio span{{font-size:13px;color:var(--muted-2);font-weight:500}}

  .delta{{font-family:'IBM Plex Mono',monospace;font-size:11.5px;font-weight:600;margin-left:4px}}
  .delta.up{{color:var(--up)}}
  .delta.down{{color:var(--down)}}
  .delta.flat{{color:var(--muted-2)}}

  .tracks{{display:flex;flex-direction:column;border-top:1px solid var(--line-soft)}}
  .track-row{{display:flex;justify-content:space-between;align-items:center;
    padding:7px 2px;border-bottom:1px solid var(--line-soft);font-size:12.5px}}
  .track-row:last-child{{border-bottom:none}}
  .t-name{{color:var(--muted)}}
  .t-nums{{font-family:'IBM Plex Mono',monospace;font-variant-numeric:tabular-nums;
    display:flex;gap:9px;align-items:baseline}}
  .t-nums .n{{color:var(--muted-2);font-size:11.5px}}
  .t-nums .r{{color:var(--ink);font-weight:600}}

  .pending-body{{color:var(--muted);font-size:13px;line-height:1.6;margin:0}}
  .pending-body b{{color:var(--ink)}}

  .card-foot{{display:flex;justify-content:space-between;align-items:center;
    font-size:11px;color:var(--muted-2);gap:8px}}
  .card-foot a{{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--muted-2)}}
  .stale{{color:var(--accent);margin-left:4px}}

  .note{{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);
    font-size:12.5px;line-height:1.75}}
  .note h3{{font-family:'Archivo',sans-serif;font-size:12px;letter-spacing:.06em;
    text-transform:uppercase;color:var(--ink);margin:0 0 8px}}
  .note ul{{margin:0;padding-left:17px}}
  .note li{{margin-bottom:5px}}
  .note a{{color:var(--muted)}}

  #toast{{position:fixed;left:50%;bottom:24px;transform:translate(-50%,14px);
    background:var(--good-dim);color:var(--good);border:1px solid var(--good);
    padding:9px 16px;border-radius:999px;font-size:13px;font-weight:600;
    opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:50}}
  #toast.show{{opacity:1;transform:translate(-50%,0)}}
  @media (prefers-reduced-motion:reduce){{#toast{{transition:none}}}}

  @media (max-width:640px){{
    .strip{{grid-template-columns:repeat(2,1fr)}}
    .headline .ratio{{font-size:22px}}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="eyebrow">2027학년도 수시 · 자동 갱신</div>
    <h1>무용학부(발레) 경쟁률 보드</h1>
    <p class="sub">관심대학 7개교의 무용 <b>발레</b> 모집단위 지원현황입니다.
      대학 원본이 <b>매시 정각</b>에 갱신되면 이 보드가 <b>1~2분 안에</b> 반영하고,
      보고 계신 화면도 새로고침 없이 저절로 바뀝니다.</p>
  </header>

  <div class="strip">
    <div class="stat"><div class="label">관심대학</div><div class="value">{len(results)}개교</div></div>
    <div class="stat"><div class="label">접수중</div><div class="value good">{len(live)}개교</div></div>
    <div class="stat"><div class="label">발레 전체 경쟁률</div><div class="value accent">{overall} : 1</div></div>
    <div class="stat"><div class="label">대학 발표 기준</div><div class="value" style="font-size:15px">{esc(basis)}</div></div>
  </div>

  <div class="section-title"><h2>접수중 · 발레 경쟁률 공개</h2><span class="count">{len(live)}</span></div>
  <div class="grid">{''.join(render_card(e) for e in live)}
  </div>

  <div class="section-title"><h2>접수 예정</h2><span class="count">{len(pending)}</span></div>
  <div class="grid">{''.join(render_card(e) for e in pending)}
  </div>

  <div class="note">
    <h3>참고</h3>
    <ul>
      <li>수치는 각 대학이 공개 운영하는 지원현황 페이지를 그대로 옮긴 것입니다. 대학 원본은 매시 정각에 갱신되며, 이 보드는 정각 직후 20초 간격으로 확인합니다.</li>
      <li>▲▼ 표시는 직전 확인 시점 대비 지원자 증감입니다.</li>
      <li>최종 경쟁률이 아니며 접수 마감(2026.09.11 금 18:00) 전까지 계속 바뀝니다. 정확한 정보는 각 대학 홈페이지에서 확인하세요.</li>
      <li>이 화면은 새 숫자가 올라오면 <b>자동으로 다시 불러옵니다</b>. 직접 새로고침하지 않으셔도 됩니다.</li>
      <li>마지막 반영: {now.strftime('%Y.%m.%d %H:%M')} (KST)</li>
    </ul>
  </div>

</div>

<div id="toast">방금 갱신되었습니다</div>

<script>
  // GitHub Pages 는 파일을 10분간 CDN 에 캐시해서, 이 주소로는 새 값을 제때 못 받는다
  // (쿼리스트링·no-store 모두 무시된다). 그래서 캐시가 없는 raw 주소에서 직접 읽고,
  // 바뀐 내용만 화면에 갈아끼운다. 페이지를 다시 불러오지 않으므로 스크롤도 유지된다.
  var RAW = "https://raw.githubusercontent.com/woopapa0303/ballet-ratio/main/";
  var CURRENT = "{now.isoformat()}";
  var checking = false;

  function showToast() {{
    var el = document.getElementById("toast");
    if (!el) return;
    el.classList.add("show");
    setTimeout(function () {{ el.classList.remove("show"); }}, 4000);
  }}

  async function checkForUpdate() {{
    if (checking || document.hidden) return;
    checking = true;
    try {{
      var res = await fetch(RAW + "data.json?t=" + Date.now(), {{ cache: "no-store" }});
      if (!res.ok) return;
      var data = await res.json();
      if (!data.updated_at || data.updated_at === CURRENT) return;

      var htmlRes = await fetch(RAW + "index.html?t=" + Date.now(), {{ cache: "no-store" }});
      if (!htmlRes.ok) return;
      var doc = new DOMParser().parseFromString(await htmlRes.text(), "text/html");
      if (!doc.body) return;

      var toast = document.getElementById("toast");
      document.body.replaceWith(document.importNode(doc.body, true));
      if (toast) document.body.appendChild(toast);   // 알림 요소는 유지
      CURRENT = data.updated_at;
      showToast();
    }} catch (e) {{
      /* 일시적인 네트워크 오류는 조용히 넘기고 다음 회차에 다시 확인한다 */
    }} finally {{
      checking = false;
    }}
  }}

  setInterval(checkForUpdate, 30000);
  document.addEventListener("visibilitychange", function () {{
    if (!document.hidden) checkForUpdate();   // 휴대폰 화면을 다시 켰을 때 즉시 확인
  }});
</script>
</body>
</html>
"""


def fingerprint(results):
    """의미 있는 데이터(대학별 모집/지원/기준시각)만 뽑은 지문.

    확인 시각처럼 매번 달라지는 값은 제외한다. 지문이 같으면 파일을 새로 쓰지
    않아 불필요한 커밋과 페이지 재배포가 생기지 않는다.
    """
    return [
        [
            e["key"],
            e["stamp"],
            [[t["label"], t["capacity"], t["applicants"]] for t in e["tracks"]],
        ]
        for e in results
    ]


def main():
    results, now, state = collect()
    fp = fingerprint(results)

    if fp == state.get("fingerprint") and os.path.exists(HTML_PATH):
        print(f"변경 없음 ({now:%H:%M} KST) — 파일을 그대로 둡니다.")
        return

    state["schools"] = {e["key"]: e for e in results}
    state["updated_at"] = now.isoformat()
    state["fingerprint"] = fp

    ballet_total = sum(
        t["applicants"]
        for e in results
        for t in e["tracks"]
        if t["track"] == "발레"
    )
    history = state.get("history", [])
    if not history or history[-1].get("ballet_total") != ballet_total:
        history.append({"at": now.isoformat(), "ballet_total": ballet_total})
        state["history"] = history[-200:]

    save_state(state)

    html = render(results, now)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    live = [e for e in results if e["status"] == "live"]
    for e in live:
        b = next((t for t in e["tracks"] if t["track"] == "발레"), None)
        if b:
            print(f"{e['name']}: 발레 {b['capacity']}명 모집 / {b['applicants']}명 지원 = {b['ratio']:.2f}:1")
    print(f"생성 완료: {HTML_PATH} ({now:%Y-%m-%d %H:%M} KST)")


if __name__ == "__main__":
    main()
