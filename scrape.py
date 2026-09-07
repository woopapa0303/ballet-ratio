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
    # 접수 시작일이 09.08 인 대학들 — 경쟁률 페이지가 열리면 url 을 채운다.
    {
        "key": "khu",
        "name": "경희대학교",
        "campus": "서울·경기",
        "dept": "무용학부",
        "url": None,
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "cau",
        "name": "중앙대학교",
        "campus": "서울",
        "dept": "무용예술전공",
        "url": None,
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "dankook",
        "name": "단국대학교",
        "campus": "경기·충남",
        "dept": "무용과",
        "url": None,
        "period": "09.08 ~ 09.11 18:00",
    },
    {
        "key": "sungshin",
        "name": "성신여자대학교",
        "campus": "서울",
        "dept": "무용예술학과",
        "url": None,
        "period": "09.08 ~ 09.11 18:00",
    },
]

TRACK_RE = re.compile(r"발레|한국무용|현대무용")
RATIO_RE = re.compile(r"^\d+(?:\.\d+)?\s*:\s*1$")
STAMP_RE = re.compile(r"(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d{2})시\s*(\d{2})분\s*기준")

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
    return out


def parse_stamp(html):
    """'2026년 09월 07일 14시 00분 기준' → '09.07 14:00'."""
    m = STAMP_RE.search(strip_tags(html))
    if not m:
        return None
    _, mo, d, h, mi = m.groups()
    return f"{mo}.{d} {h}:{mi}"


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

    for school in SCHOOLS:
        prev = state["schools"].get(school["key"], {})
        entry = dict(school)
        entry["tracks"] = []
        entry["stamp"] = None
        entry["stale"] = False
        entry["status"] = "pending"

        if not school["url"]:
            # 아직 경쟁률 페이지가 열리지 않은 대학
            results.append(entry)
            continue

        try:
            html = fetch(school["url"])
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

        # 직전 값 대비 증감 (발레 기준)
        prev_by_track = {t["track"]: t for t in prev.get("tracks", [])}
        for t in entry["tracks"]:
            before = prev_by_track.get(t["track"])
            t["delta"] = (
                t["applicants"] - before["applicants"] if before else 0
            )

        results.append(entry)

    state["schools"] = {e["key"]: e for e in results}
    state["updated_at"] = now.isoformat()

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
    return results, now


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

    ballet = next((t for t in entry["tracks"] if t["track"] == "발레"), None)
    others = [t for t in entry["tracks"] if t["track"] != "발레"]

    if ballet:
        headline = f"""
      <div class="headline">
        <div class="track">{esc(ballet['label'])}<br><span class="nums">모집 {ballet['capacity']} · 지원 {ballet['applicants']} {render_delta(ballet['delta'])}</span></div>
        <div class="ratio">{ballet['ratio']:.2f}<span> : 1</span></div>
      </div>"""
    else:
        headline = '<div class="headline"><div class="track">발레 모집단위를 찾지 못했습니다</div></div>'

    rows = "".join(
        f"""
        <div class="track-row">
          <span class="t-name">{esc(t['track'])}</span>
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
<meta http-equiv="refresh" content="300">
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
      각 대학이 공개하는 실시간 경쟁률 페이지를 <b>10분마다</b> 자동으로 읽어옵니다.
      이 페이지는 5분마다 스스로 새로고침됩니다.</p>
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
      <li>수치는 각 대학이 공개 운영하는 지원현황 페이지를 그대로 옮긴 것입니다. 대학 원본은 보통 1시간 단위로 갱신되며, 이 보드는 10분마다 원본을 다시 확인합니다.</li>
      <li>▲▼ 표시는 직전 확인 시점 대비 지원자 증감입니다.</li>
      <li>최종 경쟁률이 아니며 접수 마감(2026.09.11 금 18:00) 전까지 계속 바뀝니다. 정확한 정보는 각 대학 홈페이지에서 확인하세요.</li>
      <li>마지막 확인: {now.strftime('%Y.%m.%d %H:%M')} (KST)</li>
    </ul>
  </div>

</div>
</body>
</html>
"""


def main():
    results, now = collect()
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
