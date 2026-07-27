"""
app.py  —  전국 골프장 티타임 통합검색 (티스캐너 스타일)
실행:  streamlit run app.py
"""

import calendar
import concurrent.futures as cf
import datetime as dt
import html as _html
import json
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
from streamlit_folium import st_folium
from st_keyup import st_keyup

import data as D
from data import add_total_cost
import weather as wx
import teescanner as ts
import catalog as CAT
import scan as SCAN

_ICON_LOCAL = str(Path(__file__).parent / "static" / "app-icon-192.png")
st.set_page_config(page_title="웅SCANNER · 전국 골프장 티타임",
                   page_icon=(_ICON_LOCAL if Path(_ICON_LOCAL).exists() else "⛳"),
                   layout="wide", initial_sidebar_state="auto")

TODAY = dt.date.today()
MONTH_RANGE_LABEL = f"{TODAY.month}~{TODAY.month % 12 + 1}월"  # 당월~다음월 (월 바뀌면 자동 변경)
DEAL_LIMIT_PRICE = 70000  # 특가 기준 그린피(원)
POPUP_PRICE_CAP = 60000   # 18홀 기준 그린피 6만원 이하(9홀은 x2가 6만원 이하일 때만)
POPUP_DAYS = 30           # 오늘부터 며칠간의 특가를 모을지
MAX_DATES = 45            # 성능 보호: 한 번에 생성/표시할 최대 날짜 수

# 클릭 가능한 스타일 표(커스텀 컴포넌트) — 행 클릭 시 새로고침 없이 선택값을 반환
_scan_table = components.declare_component(
    "scan_table", path=str(Path(__file__).parent / "components" / "scan_table"))

# 로그인 유지용 저장소(브라우저 localStorage) — 새로고침해도 로그인이 풀리지 않게 함
_auth_store = components.declare_component(
    "auth_store", path=str(Path(__file__).parent / "components" / "auth_store"))

# 클릭 가능한 골프장 목록(지도·날씨 탭 공용) — 항목 클릭 시 골프장 이름을 반환
_course_list = components.declare_component(
    "course_list", path=str(Path(__file__).parent / "components" / "course_list"))


def _secret(k: str):
    """secrets.toml 이 없어도 안전하게 읽기(없으면 None)."""
    try:
        return st.secrets[k]
    except Exception:
        return None


# 클라우드 배포용: secrets에 토큰이 있으면 모두가 그걸로 실데이터를 사용(친구들은 입력 불필요)
_sx, _sr = _secret("TEESCANNER_X_TOKEN"), _secret("TEESCANNER_X_REFRESH_TOKEN")
if _sx and _sr:
    ts.set_tokens(str(_sx), str(_sr))

def naver_directions(course: str) -> str:
    """골프장 이름으로 네이버 지도(실제 위치)를 열어 길찾기하는 링크."""
    return f"https://map.naver.com/p/search/{quote(course)}"


def folium_map(mapdf: pd.DataFrame, focus: str | None = None) -> folium.Map:
    """OpenStreetMap(무료·키 불필요) + 골프장 마커 지도. 마커 클릭 시 길찾기 버튼.
    focus(골프장 이름)가 주어지면 그 골프장으로 지도를 확대·중심 이동하고 마커를 강조."""
    frow = None
    if focus is not None and (mapdf["course"] == focus).any():
        frow = mapdf[mapdf["course"] == focus].iloc[0]
        center = [float(frow["lat"]), float(frow["lon"])]
        zoom = 13
    else:
        center = [float(mapdf["lat"].mean()), float(mapdf["lon"].mean())]
        zoom = 13 if len(mapdf) == 1 else 7
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    for _, r in mapdf.iterrows():
        loc = r["city"] if "city" in r and pd.notna(r["city"]) else r.get("region", "")
        is_focus = frow is not None and r["course"] == focus
        popup_html = (
            f"<div style='font-family:sans-serif;text-align:center;min-width:150px'>"
            f"<div style='font-weight:800;font-size:14px;margin-bottom:2px'>{r['course']}</div>"
            f"<div style='color:#5c7565;font-size:12px'>{loc} · {r['holes']}홀 · {r['gubun']}</div>"
            f"<a href='{naver_directions(str(r['course']))}' target='_blank' "
            f"style='display:inline-block;margin-top:8px;background:#16A34A;color:#fff;"
            f"padding:6px 14px;border-radius:8px;font-weight:800;text-decoration:none;font-size:13px'>"
            f"🧭 네이버 길찾기</a></div>"
        )
        folium.CircleMarker(
            location=[float(r["lat"]), float(r["lon"])],
            radius=11 if is_focus else 6, weight=2 if is_focus else 1,
            color="#166534" if is_focus else "#991B1B",
            fill=True, fill_color="#16A34A" if is_focus else "#EF4444",
            fill_opacity=0.95 if is_focus else 0.9,
            tooltip=f"{r['course']}",
            popup=folium.Popup(popup_html, max_width=240,
                               show=bool(is_focus)),
        ).add_to(m)
    return m

# ============================ 디자인(CSS) — 밝은 잔디 테마 ============================
CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Gowun+Dodum&family=Bungee&family=Black+Han+Sans&display=swap');

html, body, [class*="css"], .stApp, button, input, select, textarea {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif !important;
    color: #17301F;
}
.stApp {
    background:
      repeating-linear-gradient(122deg, rgba(45,150,60,.045) 0 44px, rgba(90,190,105,.085) 44px 88px),
      radial-gradient(1000px 520px at 92% -12%, rgba(150,230,160,.35), transparent 60%),
      linear-gradient(180deg, #eff8ea 0%, #e3f1dc 100%) fixed;
}
.block-container { padding-top: 1.3rem; padding-bottom: 3rem; max-width: 1460px; }
#MainMenu, footer { visibility: hidden; height:0; }
header[data-testid="stHeader"] { background: transparent; }
/* 오른쪽 위 Deploy 버튼/툴바 숨김 (스트림릿 기본 요소) */
[data-testid="stToolbar"], [data-testid="stAppDeployButton"], .stDeployButton { display: none !important; }
/* 사이드바 미사용 — 모든 기능을 메인 화면으로 옮겨서 사이드바는 숨김 */
section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* ---------- 히어로 (햇살 잔디 페어웨이) ---------- */
.hero {
    position:relative; overflow:hidden; border-radius:26px; padding:34px 46px; margin-bottom:26px;
    background:
      radial-gradient(520px 260px at 88% -30%, rgba(255,255,255,.55), transparent 60%),
      linear-gradient(118deg, #167c3c 0%, #27a851 42%, #7fd24a 100%);
    box-shadow: 0 26px 55px -26px rgba(39,168,81,.65), inset 0 1px 0 rgba(255,255,255,.35);
}
.hero:before {  /* 잔디 깎은 줄무늬(모잉 스트라이프) */
    content:""; position:absolute; inset:0; opacity:.5;
    background: repeating-linear-gradient(100deg, rgba(255,255,255,.10) 0 34px, rgba(0,0,0,.05) 34px 68px);
    mask: linear-gradient(180deg, transparent 30%, #000 100%);
}
.hero .flag { position:absolute; right:46px; top:50%; transform:translateY(-50%); font-size:150px;
    filter: drop-shadow(0 16px 28px rgba(0,0,0,.32)); }
.hero-kick { position:relative; display:inline-block; color:#eafff0; font-weight:800; font-size:13px;
    letter-spacing:.4px; background:rgba(255,255,255,.16); border:1px solid rgba(255,255,255,.4);
    padding:5px 13px; border-radius:999px; margin-bottom:13px; }
.hero h1 { position:relative; color:#fff; font-size:48px; font-weight:800; margin:0; line-height:1.04;
    letter-spacing:-1.5px; text-shadow:0 3px 16px rgba(0,60,20,.35); }
.hero p  { position:relative; font-family:'Gowun Dodum','Pretendard',sans-serif !important;
    color:#f0fff3; font-size:16.5px; margin:14px 0 0; }
.hero .chip {
    position:relative; display:inline-flex; align-items:center; gap:8px; margin-top:20px;
    background: rgba(255,255,255,.22); color:#fff; padding:9px 18px; border-radius:999px;
    font-size:14px; font-weight:700; border:1px solid rgba(255,255,255,.4); backdrop-filter: blur(4px);
}

/* ---------- KPI 카드 ---------- */
.kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin:2px 0 24px; }
.kpi-card {
    background:#fff; border:1px solid #dcebd5; border-radius:18px; padding:20px 22px;
    box-shadow: 0 10px 24px -18px rgba(40,120,60,.4);
    transition:transform .16s ease, box-shadow .16s ease;
}
.kpi-card:hover { transform:translateY(-4px); box-shadow:0 18px 34px -18px rgba(22,163,74,.5); }
.kpi-card .ico { width:40px; height:40px; border-radius:12px; display:flex; align-items:center;
    justify-content:center; font-size:20px; background:#e9f8ee; margin-bottom:12px; }
.kpi-card .label { color:#5c7565; font-size:13px; font-weight:600; }
.kpi-card .value { font-family:'Montserrat','Pretendard',sans-serif !important;
    color:#12321f; font-size:29px; font-weight:800; margin-top:5px; }
.kpi-card.hl { background:linear-gradient(180deg,#eafaef,#ffffff); border-color:#8fe0a6; }
.kpi-card.hl .value { color:#12a350; }

/* ---------- 탭 ---------- */
.stTabs [data-baseweb="tab-list"] { gap:8px; border-bottom:1px solid #cfe3c7; }
.stTabs [data-baseweb="tab"] { background:transparent; border-radius:10px 10px 0 0; padding:9px 18px;
    font-weight:700; color:#5c7565; }
.stTabs [aria-selected="true"] { background:#ffffff; color:#12a350; box-shadow:0 -2px 0 #16A34A inset; }

/* ---------- 티타임 테이블 ---------- */
.table-wrap { border:1px solid #d8e8d1; border-radius:16px; overflow-x:auto; background:#fff;
    box-shadow:0 12px 30px -22px rgba(40,120,60,.5); }
.golf-table { width:100%; min-width:900px; border-collapse:collapse; font-size:13.5px; table-layout:auto; }
.golf-table thead th { background:#eef7e9; color:#3c6b47; font-weight:800; text-align:center;
    padding:13px 11px; border-bottom:1px solid #d8e8d1; white-space:nowrap; }
.golf-table tbody td { padding:12px 11px; border-bottom:1px solid #eef3ea; text-align:center;
    color:#26382b; white-space:nowrap; }
.golf-table th:first-child, .golf-table td:first-child { padding-left:16px; }
.golf-table th:last-child, .golf-table td:last-child { padding-right:16px; }
.golf-table tbody tr:last-child td { border-bottom:none; }
.golf-table tbody tr:hover td { background:#f3fbef; }
.golf-table tbody tr.best td { background:linear-gradient(90deg, rgba(22,163,74,.10), transparent 70%); }
.golf-table tbody tr.best td:first-child { box-shadow: inset 3px 0 0 #16A34A; }
.golf-table .course { text-align:left; font-weight:800; color:#123021; white-space:nowrap; }
.golf-table a.course-link { color:#123021; font-weight:800; text-decoration:none; cursor:pointer;
    border-bottom:1px dashed #9bc4a8; }
.golf-table a.course-link:hover { color:#12a350; border-bottom-color:#12a350; }
#tt-detail { position:relative; top:-70px; }
.golf-table .dt { white-space:nowrap; }
.golf-table .cad { white-space:nowrap; line-height:1.35; }
.golf-table .rank { color:#9bb0a0; font-weight:800; width:34px; font-family:'Montserrat',sans-serif; }
.golf-table .money { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.golf-table .total { text-align:right; white-space:nowrap; font-weight:800; color:#12a350; font-variant-numeric:tabular-nums; }
.badge { padding:3px 11px; border-radius:999px; font-size:12px; font-weight:700; color:#fff; }
.req { font-size:11px; margin-top:4px; font-weight:700; }
.best-badge { background:#F5A524; color:#3a2600; padding:2px 8px; border-radius:6px; font-size:11px;
    font-weight:800; margin-left:8px; display:inline-block; white-space:nowrap; }
.deal-price { color:#e0352b; font-weight:800; }
.loop { background:#fef3c7; color:#92580a; padding:1px 6px; border-radius:6px; font-size:11px; font-weight:800; }
.src-pill { background:#eef3ea; color:#4f6a57; padding:3px 10px; border-radius:7px; font-size:12.5px;
    font-weight:600; display:inline-block; white-space:nowrap; }
.book-btn { background:#16A34A; color:#fff !important; padding:6px 14px; border-radius:9px; font-weight:800;
    text-decoration:none; font-size:13px; display:inline-block; white-space:nowrap;
    box-shadow:0 4px 12px -4px rgba(22,163,74,.6); }
.book-btn:hover { background:#12b552; }

/* ---------- 특가 팝업 ---------- */
.deal-lead { color:#3c6b47; font-size:14.5px; margin:0 0 6px; }
.deal-row { display:flex; align-items:center; justify-content:space-between; gap:14px;
    background:#f7fcf4; border:1px solid #dcebd5; border-radius:14px; padding:14px 18px; margin-bottom:10px; }
.deal-row .name { font-weight:800; color:#123021; font-size:15px; }
.deal-row .meta { color:#5c7565; font-size:12.5px; margin-top:3px; }
.deal-row .pr { font-family:'Montserrat',sans-serif; font-size:20px; font-weight:800; color:#e0352b; }
.tag-req { padding:3px 9px; border-radius:999px; font-size:11.5px; font-weight:800; color:#fff; }

/* ---------- 특가 패널 강조(중앙 카드 느낌) ---------- */
.st-key-deal_modal {
    border:2px solid #16A34A !important; border-radius:20px !important;
    background:#ffffff !important; box-shadow:0 24px 60px -26px rgba(20,90,50,.55) !important; }

/* ---------- 로고 (웅SCANNER) - 그래피티 · 다채색 · 임팩트 ---------- */
.logo-wrap { position:relative; padding:0 2px 16px; margin-bottom:8px; border-bottom:1px solid #d8e8d1;
    text-align:center; }
@keyframes ungpop {
    0%,100% { transform: rotate(-5deg) scale(1);
        filter: drop-shadow(2px 3px 0 #111) drop-shadow(0 0 10px rgba(255,90,0,.45)); }
    50%     { transform: rotate(-5deg) scale(1.06);
        filter: drop-shadow(3px 4px 0 #111) drop-shadow(0 0 20px rgba(255,180,0,.7)); }
}
.logo-ung {
    display:inline-block; font-family:'Black Han Sans', sans-serif;
    font-size:104px; line-height:.84; letter-spacing:-1px;
    background: linear-gradient(135deg,#ff2d55 0%,#ff9500 26%,#ffd60a 48%,#34c759 70%,#0a84ff 100%);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
    animation: ungpop 1.7s ease-in-out infinite;
}
.logo-scan { display:block; margin-top:2px; line-height:1; white-space:nowrap; }
.logo-scan span {
    font-family:'Bungee', cursive; font-size:33px; letter-spacing:.5px;
    -webkit-text-stroke:1.4px #141414;
    text-shadow: 1.5px 1.5px 0 #141414, 3px 3px 0 rgba(0,0,0,.25);
    animation: scanbob 1.4s ease-in-out infinite;
}
@keyframes scanbob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-3px)} }
.logo-scan .c1{ -webkit-text-fill-color:#ff3b30; animation-delay:0s; }
.logo-scan .c2{ -webkit-text-fill-color:#ff9500; animation-delay:.08s; }
.logo-scan .c3{ -webkit-text-fill-color:#ffcc00; animation-delay:.16s; }
.logo-scan .c4{ -webkit-text-fill-color:#34c759; animation-delay:.24s; }
.logo-scan .c5{ -webkit-text-fill-color:#00c7be; animation-delay:.32s; }
.logo-scan .c6{ -webkit-text-fill-color:#0a84ff; animation-delay:.40s; }
.logo-scan .c7{ -webkit-text-fill-color:#bf5af2; animation-delay:.48s; }
.logo-tag { margin-top:11px; font-size:11px; color:#5c7565; font-weight:700; letter-spacing:.3px; }

/* ---------- 특가 다시 보기 버튼(primary) 강조 ---------- */
.stButton > button { border-radius:12px; font-weight:800; }
.stButton button[kind="primary"], [data-testid="stBaseButton-primary"] {
    background:linear-gradient(120deg,#16A34A,#22C55E) !important; color:#fff !important; border:none !important;
    box-shadow:0 10px 22px -8px rgba(22,163,74,.7); font-size:15px; padding:10px 20px; }
.stButton button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {
    background:linear-gradient(120deg,#12b552,#34e68c) !important; }

/* ---------- 실시간 검색창(st_keyup)에만 높이 40px 적용 (지도 등 다른 컴포넌트는 제외) ---------- */
iframe[title="st_keyup.st_keyup"] { height: 40px !important; display:block; margin:0 !important; }
[data-testid="stCustomComponentV1"]:has(iframe[title="st_keyup.st_keyup"]) {
    height: 40px !important; margin-bottom:0 !important; }

/* ---------- 로그인 유지 저장소(auth_store) — 눈에 안 보이게 완전 숨김 ---------- */
iframe[title="auth_store.auth_store"] { height:0 !important; display:block; margin:0 !important; }
[data-testid="stCustomComponentV1"]:has(iframe[title="auth_store.auth_store"]) {
    height:0 !important; margin:0 !important; padding:0 !important; }

/* ---------- 지도탭: CC 검색 결과 스크롤 목록 ---------- */
.cc-list { max-height: 400px; overflow-y:auto; border:1px solid #dcebd5; border-radius:12px;
    background:#fff; padding:4px; box-shadow:0 8px 20px -16px rgba(40,120,60,.5); }
.cc-item { padding:9px 12px; border-bottom:1px solid #eef3ea; font-weight:700; color:#123021; font-size:13.5px; }
.cc-item:last-child { border-bottom:none; }
.cc-sub { color:#7a8f80; font-weight:500; font-size:12px; }
.cc-empty { padding:18px; text-align:center; color:#7a8f80; }

/* ---------- 날씨: 시간대별 수치 스트립 ---------- */
.hour-strip { display:flex; gap:8px; overflow-x:auto; padding:6px 2px 12px; }
.hour-cell { min-width:74px; flex:0 0 auto; background:#fff; border:1px solid #dcebd5; border-radius:14px;
    padding:12px 8px; text-align:center; box-shadow:0 6px 16px -14px rgba(40,120,60,.5); }
.hour-cell .hh { font-size:12.5px; color:#5c7565; font-weight:700; }
.hour-cell .ic { font-size:24px; margin:6px 0 4px; }
.hour-cell .tt { font-family:'Montserrat',sans-serif; font-size:18px; font-weight:800; color:#12321f; }
.hour-cell .rr { font-size:12px; color:#2563eb; margin-top:5px; font-weight:600; }
.hour-cell .ww { font-size:12px; color:#5c7565; margin-top:2px; font-weight:600; }
.wcard-sub { font-size:12.5px; color:#5c7565; margin-top:4px; font-weight:600; }

/* ---------- 모바일(좁은 화면) 배율 맞춤 ---------- */
@media (max-width: 640px) {
    .block-container { padding-left:0.6rem !important; padding-right:0.6rem !important; padding-top:0.8rem; }
    .hero { padding:20px 18px; border-radius:18px; margin-bottom:16px; }
    .hero-kick { font-size:10.5px; margin-bottom:8px; padding:4px 10px; }
    .hero h1 { font-size:25px; letter-spacing:-.5px; line-height:1.08; }
    .hero p { font-size:12.5px; margin-top:8px; }
    .hero .flag { font-size:60px; right:12px; top:50%; }
    .hero .chip { font-size:12px; padding:7px 12px; margin-top:12px; }
    .kpi-grid { grid-template-columns:repeat(2,1fr) !important; gap:10px; margin-bottom:16px; }
    .kpi-card { padding:14px 14px; border-radius:14px; }
    .kpi-card .ico { width:32px; height:32px; font-size:16px; margin-bottom:8px; }
    .kpi-card .value { font-size:21px; }
    .kpi-card .label { font-size:12px; }
    .stTabs [data-baseweb="tab"] { padding:8px 10px; font-size:13px; }
    .logo-ung { font-size:82px; }
    .logo-scan span { font-size:26px; }
    h1, h2, h3 { word-break:keep-all; }
}

</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------- 홈 화면(앱) 아이콘: ⛳ 골프 아이콘을 iOS/안드로이드 '홈 화면에 추가' 아이콘으로 지정 ----------
# (Streamlit 기본 아이콘 대신 static/의 골프 아이콘을 <head>에 주입. GitHub raw로 안정적인 절대주소 사용)
_ICON_BASE = "https://raw.githubusercontent.com/woongeeeee/golf-tee/main/static/"
_ICON_VER = "5"   # 아이콘 바꿀 때마다 숫자 올리면 폰이 새로 받아감(캐시 무력화)
components.html(f"""
<script>
(function() {{
  var base = "{_ICON_BASE}", V = "?v={_ICON_VER}", TITLE = "웅SCANNER";
  function apply() {{
    try {{
      var doc = window.parent.document, head = doc.head;
      // 1) Streamlit 기본 아이콘/매니페스트 제거
      doc.querySelectorAll("link[rel='apple-touch-icon'],link[rel='apple-touch-icon-precomposed'],"
        + "link[rel='icon'],link[rel='shortcut icon'],link[rel='manifest']").forEach(function(l){{ l.remove(); }});
      // 2) 우리 골프 아이콘 주입
      function addLink(rel, href, sizes) {{
        var l = doc.createElement('link'); l.setAttribute('rel', rel); l.setAttribute('href', href);
        if (sizes) l.setAttribute('sizes', sizes); head.appendChild(l);
      }}
      addLink('apple-touch-icon', base + 'apple-touch-icon.png' + V);
      addLink('apple-touch-icon-precomposed', base + 'apple-touch-icon.png' + V);
      addLink('icon', base + 'app-icon-192.png' + V, '192x192');
      addLink('shortcut icon', base + 'app-icon-192.png' + V);
      // 3) 홈 화면 이름/웹앱 메타
      function setMeta(name, content) {{
        var m = doc.querySelector("meta[name='" + name + "']");
        if (!m) {{ m = doc.createElement('meta'); m.setAttribute('name', name); head.appendChild(m); }}
        m.setAttribute('content', content);
      }}
      setMeta('apple-mobile-web-app-title', TITLE);
      setMeta('application-name', TITLE);
      setMeta('apple-mobile-web-app-capable', 'yes');
    }} catch (e) {{}}
  }}
  apply();
  // Streamlit이 나중에 자기 태그를 다시 넣을 수 있어 몇 번 더 덮어씀
  var n = 0, t = setInterval(function() {{ apply(); if (++n > 12) clearInterval(t); }}, 500);
}})();
</script>
""", height=0)

CADDIE_COLORS = {"캐디": "#16A34A", "노캐디": "#64748B", "캐디선택가능": "#D97706"}
CADDIE_OPTIONS = ["캐디", "노캐디", "캐디선택가능"]
WEATHER_EMOJI = {"맑음": "☀️", "구름많음": "☁️", "구름조금": "🌤️", "구름 조금": "🌤️",
                 "대체로 흐림": "⛅", "흐림": "☁️", "안개": "🌫️", "이슬비": "🌦️",
                 "약한 비": "🌦️", "소나기": "🌧️", "뇌우": "⛈️",
                 "비": "🌧️", "눈": "🌨️", "구름": "⛅"}


def wemoji(text: str) -> str:
    for k, v in WEATHER_EMOJI.items():
        if k in (text or ""):
            return v
    return "🌡️"


def caddie_badge(raw: str) -> str:
    """티스캐너 캐디 문자열(하우스캐디/노캐디/선택 등) → 색상 배지 HTML."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "노" in raw or raw.lower().startswith("no"):
        color = "#16A34A"      # 노캐디
    elif "선택" in raw:
        color = "#D97706"      # 선택 가능
    else:
        color = "#DC2626"      # 하우스/동반 = 캐디 필수
    return f"<span class='tag-req' style='background:{color}'>{raw}</span>"


CADDIE_FILTER_OPTS = ["캐디필수", "노캐디", "캐디선택가능"]
CADDIE_KEYS = (("캐디필수", "cad_req"), ("노캐디", "cad_no"), ("캐디선택가능", "cad_sel"))


def booking_url(seq, date: str) -> str:
    """티스캐너 골프장 예약 상세 페이지 URL(선택한 날짜로 바로 이동)."""
    try:
        s = int(seq)
    except (TypeError, ValueError):
        return "https://www.teescanner.com"
    return ("https://www.teescanner.com/booking/detail?tab=teetime"
            f"&golfclub_seq={s}&roundDay={date}&isJoin=N&entry_path=MP&step=1")


def caddie_picks() -> list:
    """캐디 체크박스 상태 → 선택된 캐디 종류 목록(하나도 없으면 전체)."""
    picks = [label for label, k in CADDIE_KEYS if st.session_state.get(k, True)]
    return picks or CADDIE_FILTER_OPTS


def caddie_class(raw: str) -> str:
    """티스캐너 캐디 원문 → 캐디필수 / 노캐디 / 캐디선택가능 중 하나(빈값은 '')."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "노" in raw or raw.lower().startswith("no"):
        return "노캐디"
    if "선택" in raw:
        return "캐디선택가능"
    return "캐디필수"


def caddie_req(caddie: str) -> tuple[str, str]:
    """캐디 옵션 → (라벨, 색)."""
    if caddie == "노캐디":
        return "노캐디", "#16A34A"
    if caddie == "캐디선택가능":
        return "선택 가능", "#D97706"
    return "캐디 필수", "#DC2626"


def caddie_pill(raw: str) -> str:
    """캐디 원문 → 캐디필수/노캐디/캐디선택가능 색상 배지(정보 없으면 회색)."""
    cls = caddie_class(raw)
    if not cls:
        return "<span class='tag-req' style='background:#94a3b8'>캐디 확인</span>"
    color = {"노캐디": "#16A34A", "캐디선택가능": "#D97706", "캐디필수": "#DC2626"}[cls]
    return f"<span class='tag-req' style='background:{color}'>{cls}</span>"


def holes_from_name(name: str) -> str:
    """티타임 코스명(예: '9홀', '9홀X2 (18홀)', '가든(9홀)') → '18홀'/'9홀' 라벨."""
    s = str(name or "")
    if "18" in s:
        return "18홀"
    if "9" in s:
        return "9홀"
    return ""


def holes_label(h: int) -> str:
    """홀수 표시 → 18홀 완주 기준 반복 표기. (9홀은 2회, 6홀은 3회 돌아 18홀)"""
    if h == 9:
        return "9홀 <span class='loop'>×2</span>"
    if h == 6:
        return "6홀 <span class='loop'>×3</span>"
    return f"{h}홀"


def dismissed_today() -> bool:
    # 세션 기준(사람별). 새로고침하면 다시 뜸. 여러 명이 써도 서로 영향 없음.
    return st.session_state.get("popup_dismissed") == TODAY.isoformat()


def dismiss_today() -> None:
    st.session_state.popup_dismissed = TODAY.isoformat()


@st.cache_data(ttl=600)
def load_data(use_sample: bool, date_keys: tuple) -> pd.DataFrame:
    """지도·날씨 탭용 골프장 카탈로그(좌표 포함 샘플). 실데이터는 티스캐너에서 별도로 가져옴."""
    dates = [dt.date.fromisoformat(x) for x in date_keys]
    df = D.make_sample_for_dates(dates)
    return add_total_cost(df)


@st.cache_data(ttl=600)
def load_month_deals(use_sample: bool) -> pd.DataFrame:
    """오늘부터 30일간의 특가(그린피 7만원 이하) 매물을 모아 가격 낮은 순으로 반환."""
    dates = [TODAY + dt.timedelta(days=i) for i in range(30)]
    dfm = load_data(use_sample, tuple(d.isoformat() for d in dates))
    return (dfm[dfm["green_fee"] <= DEAL_LIMIT_PRICE]
            .sort_values(["green_fee", "date", "tee_time"]).head(18).reset_index(drop=True))


@st.cache_data(ttl=1800)
def weather_raw(lat: float, lon: float) -> dict | None:
    """Open-Meteo 예보 원본(캐시 30분). 키 불필요. 오늘 이전 3일도 함께 받음."""
    return wx.fetch_openmeteo(lat, lon, days=16, past_days=3)


@st.cache_data(ttl=300)
def ts_deals(date: str, region: str, tokens) -> pd.DataFrame:
    """티스캐너 실시간 특가(캐시 5분). tokens는 사람별 세션 토큰(또는 None=공유)."""
    return ts.deals_dataframe(date, region, tokens=tokens)


@st.cache_data(ttl=180)
def ts_tee_times(date: str, seq: int, tokens) -> pd.DataFrame:
    """티스캐너 골프장별 실제 티타임(캐시 3분)."""
    return ts.tee_times_dataframe(seq, date, tokens=tokens)


@st.cache_data(ttl=600)
def ts_search(keyword: str, tokens) -> pd.DataFrame:
    """티스캐너 골프장 이름 검색(캐시 10분). 전국 골프장 아무거나 검색용."""
    return ts.search_dataframe(keyword, tokens=tokens)


@st.cache_data(ttl=86400)
def ts_catalog() -> pd.DataFrame:
    """전국 골프장 목록(golf_clubs_ts.json)을 로드. 없으면 빈 DF."""
    return pd.DataFrame(CAT.load())


@st.cache_data(ttl=3600)
def ts_scan(date: str, min_hour=None) -> pd.DataFrame:
    """해당 날짜의 '전국 최저가 스캔' 결과 로드. 없으면 빈 DF.
    min_hour(당일 야간=16)면 그 시각 이후만 스캔한 별도 결과를 로드."""
    return pd.DataFrame(SCAN.load(date, min_hour))


@st.cache_data(ttl=300)
def ts_all_deals(date: str, tokens) -> pd.DataFrame:
    """6개 권역 실시간 특가를 한 번에 모아 골프장별 최저 그린피 목록으로 반환(캐시 5분)."""
    frames = []
    errs = []
    for kr, code in ts.REGION_MAP.items():
        try:
            d = ts.deals_dataframe(date, code, tokens=tokens)
        except Exception as e:
            errs.append(f"{kr}({code}): {type(e).__name__} {e}")
            continue
        if len(d):
            d = d.copy()
            d["region_kr"] = kr
            frames.append(d)
    if not frames:
        # 모든 권역이 오류면 사유를 올려서 화면에 표시(캐시 안 됨). 정상인데 0곳이면 빈 DF.
        if errs:
            raise RuntimeError(" | ".join(errs[:6]))
        return pd.DataFrame()
    alld = pd.concat(frames, ignore_index=True)
    # 같은 골프장(seq)이 여러 권역에 잡히면 최저가 1건만 유지
    alld = alld.sort_values("min_cost").drop_duplicates("seq", keep="first")
    return alld.sort_values("min_cost").reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def ts_deals_range(start_iso: str, days: int, _tokens) -> pd.DataFrame:
    """오늘(start)부터 days일간, 전 권역 실시간 특가를 병렬로 모아 반환(캐시 15분).
    _tokens는 캐시 키에서 제외(누가 조회하든 같은 공개 특가 데이터라 공유 캐시)."""
    start = dt.date.fromisoformat(start_iso)
    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]
    tasks = [(d, kr, code) for d in dates for kr, code in ts.REGION_MAP.items()]

    def _one(t):
        d, kr, code = t
        try:
            df = ts.deals_dataframe(d, code, tokens=_tokens)
        except Exception:
            return None
        if not len(df):
            return None
        df = df.copy()
        df["date"] = d
        df["region_kr"] = kr
        return df

    frames = []
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(_one, tasks):
            if r is not None and len(r):
                frames.append(r)
    if not frames:
        return pd.DataFrame()
    alld = pd.concat(frames, ignore_index=True)
    # 같은 골프장이 같은 날짜에 여러 권역으로 잡히면 최저가 1건만
    alld = alld.sort_values("min_cost").drop_duplicates(["seq", "date"], keep="first")
    return alld.reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def ts_deal_details(pairs, _tokens) -> dict:
    """여러 (날짜, seq)의 '최저가 티타임'에서 캐디·홀 정보를 병렬로 수집.
    반환: {(date, seq): (캐디원문, 코스명)}. 특가 팝업 목록에 캐디/홀 표시용."""
    def _one(p):
        d, seq = p
        try:
            df = ts.tee_times_dataframe(int(seq), d, tokens=_tokens)
        except Exception:
            return (p, "", "")
        df = df[df["green_fee"].notna() & (df["green_fee"] > 0)]
        if not len(df):
            return (p, "", "")
        row = df.loc[df["green_fee"].idxmin()]
        return (p, str(row.get("caddie") or ""), str(row.get("course") or ""))

    out = {}
    if not pairs:
        return out
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for p, cad, cname in ex.map(_one, pairs):
            out[p] = (cad, cname)
    return out


@st.cache_data(ttl=180)
def ts_cheapest_caddie(date: str, seq: int, tokens) -> str:
    """특가(추천)에는 캐디 필드가 없어, 해당 골프장 최저가 티타임의 캐디를 읽어옴(캐시 3분)."""
    try:
        d = ts.tee_times_dataframe(int(seq), date, tokens=tokens)
    except Exception:
        return ""
    d = d[d["green_fee"].notna()]
    if not len(d):
        return ""
    row = d.loc[d["green_fee"].idxmin()]
    return str(row.get("caddie") or "")


def filter_tee_times(ttdf: pd.DataFrame, am: bool, night: bool, night_hour: int = 17) -> pd.DataFrame:
    """실제 티타임 표에 오전(12시 이전)·야간(기본 17시 이후) 필터 적용.
    night_hour로 야간 기준 시각을 바꿀 수 있음(당일 야간은 16시)."""
    if not len(ttdf) or not (am or night):
        return ttdf
    def _hr(t):
        s = str(t).strip()
        s = s.split(":")[0] if ":" in s else s[:2]
        return int(s) if s.isdigit() else -1
    h = ttdf["time"].map(_hr)
    out = ttdf
    if am:
        out = out[h < 12]
    if night:
        out = out[h >= night_hour]
    return out.reset_index(drop=True)


def tee_time_table_html(ttdf: pd.DataFrame, seq=None, date: str = "") -> str:
    """티스캐너 티타임 DataFrame → HTML 테이블(지역별 특가/골프장 검색 공용)."""
    url = booking_url(seq, date)
    trows = []
    for _, t in ttdf.iterrows():
        gf = f"{int(t['green_fee']):,}원" if pd.notna(t["green_fee"]) else "-"
        gf_html = (f"<span class='deal-price'>{gf}</span>"
                   if (pd.notna(t["green_fee"]) and t["green_fee"] <= DEAL_LIMIT_PRICE) else gf)
        org = (f"<span style='color:#9bb0a0;text-decoration:line-through;font-size:12px'>{int(t['origin']):,}</span>"
               if t["discount"] and pd.notna(t["origin"]) and t["origin"] != t["green_fee"] else "")
        trows.append(
            f"<tr><td class='dt' style='font-weight:800'>{t['time']}</td>"
            f"<td class='money'>{gf_html} {org}</td>"
            f"<td>{t['caddie']}</td><td>{t['course']}</td><td>{t['people']}인</td>"
            f"<td><a class='book-btn' href='{url}' target='_blank' rel='noopener'>예약</a></td></tr>"
        )
    return (
        "<div class='table-wrap'><table class='golf-table'><thead><tr>"
        "<th>티타임</th><th>그린피</th><th>캐디</th><th>코스</th><th>인원</th><th>예약</th>"
        "</tr></thead><tbody>" + "".join(trows) + "</tbody></table></div>"
    )


def month_dates(year: int, month: int) -> list[dt.date]:
    last = calendar.monthrange(year, month)[1]
    return [d for d in (dt.date(year, month, i) for i in range(1, last + 1)) if d >= TODAY]


def kpi(ico: str, label: str, value: str, hl: bool = False) -> str:
    cls = "kpi-card hl" if hl else "kpi-card"
    return (f"<div class='{cls}'><div class='ico'>{ico}</div>"
            f"<div class='label'>{label}</div><div class='value'>{value}</div></div>")


# ============================ 특가 팝업(모달) ============================
@st.dialog("🔥 이 달의 특가", width="large")
def deal_popup(deals: pd.DataFrame):
    st.markdown(f"<p class='deal-lead'>앞으로 <b>{MONTH_RANGE_LABEL}</b> 안에 예약 가능한 특가 매물이에요. "
                "<b>날짜</b>와 <b>캐디 필수 여부</b>를 확인하고 바로 예약하세요.</p>", unsafe_allow_html=True)
    rows = []
    for _, r in deals.iterrows():
        req_label, req_color = caddie_req(r["caddie"])
        rows.append(
            f"<div class='deal-row'>"
            f"<div><div class='name'>{r['course']} <span style='color:#7a8f80;font-weight:600'>· {r['region']}</span></div>"
            f"<div class='meta'>📅 {r['date']} {r['tee_time']} · 출처 {r['source']}</div></div>"
            f"<div style='text-align:right;display:flex;align-items:center;gap:14px'>"
            f"<span class='tag-req' style='background:{req_color}'>{req_label}</span>"
            f"<div class='pr'>{r['green_fee']:,}원</div>"
            f"<a class='book-btn' href='{r['booking_url']}' target='_blank' rel='noopener'>예약</a>"
            f"</div></div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.divider()
    if st.checkbox("오늘 하루동안 이 창을 열지 않습니다"):
        dismiss_today()
        st.rerun()


@st.dialog("🔥 오늘의 전국 특가", width="large")
def deal_popup_real(deals: pd.DataFrame, date: str, tokens=None):
    """티스캐너 실시간 특가(선택 날짜, 전국 최저가 순) 팝업."""
    st.markdown(f"<p class='deal-lead'><b>{date}</b> 기준 전국에서 가장 저렴한 <b>실시간</b> 특가예요. "
                "<b>캐디 여부</b>를 확인하고 티스캐너에서 바로 예약하세요.</p>", unsafe_allow_html=True)
    cols = deals.columns
    rows = []
    with st.spinner("특가 정보 확인 중..."):
        for _, r in deals.iterrows():
            price = f"{int(r['min_cost']):,}원" if pd.notna(r["min_cost"]) else "-"
            region = r["region_kr"] if "region_kr" in cols and pd.notna(r.get("region_kr")) else r.get("region", "")
            # 캐디: 스캔 결과엔 캐디 컬럼이 있음. 없으면(추천특가) 최저가 티타임에서 조회.
            if "caddie" in cols and str(r.get("caddie") or "").strip():
                cad_raw = r["caddie"]
            else:
                cad_raw = ts_cheapest_caddie(date, int(r["seq"]), tokens) if pd.notna(r.get("seq")) else ""
            cad = caddie_badge(cad_raw)
            # 부가정보(구분·지역·평점) 있는 것만 조합
            bits = []
            if "gubun" in cols and pd.notna(r.get("gubun")):
                bits.append(str(r["gubun"]))
            if r.get("area"):
                bits.append(str(r["area"]))
            if "review" in cols and pd.notna(r.get("review")):
                bits.append(f"⭐{r['review']}")
            elif "score" in cols and pd.notna(r.get("score")):
                bits.append(f"⭐{r['score']}")
            if "time" in cols and str(r.get("time") or "").strip():
                bits.append(f"⛳{r['time']}")
            meta = " · ".join(bits)
            rows.append(
                f"<div class='deal-row'>"
                f"<div><div class='name'>{r['course']} <span style='color:#7a8f80;font-weight:600'>· {region}</span></div>"
                f"<div class='meta'>{meta}</div></div>"
                f"<div style='text-align:right;display:flex;align-items:center;gap:14px'>"
                f"{cad}<div class='pr'>{price}</div>"
                f"<a class='book-btn' href='{booking_url(r.get('seq'), date)}' target='_blank' rel='noopener'>예약</a>"
                f"</div></div>"
            )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.divider()
    if st.checkbox("오늘 하루동안 이 창을 열지 않습니다"):
        dismiss_today()
        st.rerun()


# 데이터 소스: 지도·날씨 탭은 좌표가 필요해 골프장 카탈로그(샘플) 사용. 티타임/가격은 티스캐너 실데이터.
USE_SAMPLE = True

# ============================ 상단: 로고 · 로그인 · 날짜/필터 (사이드바 없이) ============================
st.markdown("""
<div class="logo-wrap">
  <div class="logo-ung">웅</div>
  <div class="logo-scan">
    <span class="c1">S</span><span class="c2">C</span><span class="c3">A</span><span class="c4">N</span><span class="c5">N</span><span class="c6">E</span><span class="c7">R</span>
  </div>
  <div class="logo-tag">⛳ 전국 골프장 티타임 통합검색</div>
</div>
""", unsafe_allow_html=True)

# ---------- 티스캐너 로그인 (각자 자기 계정) ----------
# 로그인 유지: 브라우저 localStorage에 토큰을 저장해 새로고침해도 로그인이 풀리지 않음.
if st.session_state.get("user_tokens"):
    _t = st.session_state["user_tokens"]
    _auth_payload = json.dumps({"t": _t[0], "r": _t[1],
                                "n": st.session_state.get("user_name", "회원")})
elif st.session_state.pop("just_logged_out", False):
    _auth_payload = "__CLEAR__"
else:
    _auth_payload = "__LOAD__"
_stored = _auth_store(payload=_auth_payload, key="auth_store", default=None)
# 저장된 로그인 복원(세션에 없고, 방금 로그아웃한 게 아닐 때)
if (not st.session_state.get("user_tokens") and _auth_payload == "__LOAD__"
        and _stored):
    try:
        _d = json.loads(_stored)
        if _d.get("t") and _d.get("r"):
            st.session_state.user_tokens = (_d["t"], _d["r"])
            st.session_state.user_name = _d.get("n", "회원")
            st.rerun()
    except Exception:
        pass

USER_TOKENS = st.session_state.get("user_tokens")
if USER_TOKENS:
    uc1, uc2 = st.columns([4, 1], vertical_alignment="center")
    uc1.success(f"✅ {st.session_state.get('user_name', '회원')}님 로그인됨")
    if uc2.button("로그아웃", key="logout_btn", width="stretch"):
        st.session_state.pop("user_tokens", None)
        st.session_state.pop("user_name", None)
        st.session_state.just_logged_out = True
        st.rerun()
else:
    with st.container(border=True):
        st.markdown("**👤 티스캐너 로그인** — 본인 아이디(전화번호)·비밀번호로 로그인하면 실시간 데이터가 나와요.")
        li1, li2, li3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        with li1:
            lid = st.text_input("아이디(전화번호)", key="login_id", placeholder="01012345678")
        with li2:
            lpw = st.text_input("비밀번호", type="password", key="login_pw")
        with li3:
            go = st.button("로그인", key="login_btn", type="primary", width="stretch")
        if go:
            if not lid.strip() or not lpw:
                st.warning("아이디와 비밀번호를 모두 입력하세요.")
            else:
                try:
                    res = ts.login(lid.strip(), lpw)
                    st.session_state.user_tokens = (res["x_token"], res["x_refresh_token"])
                    st.session_state.user_name = res["name"]
                    st.rerun()
                except Exception as e:
                    st.error(f"로그인 실패: {e}")

# ---------- 날짜·선택사항 값 읽기 ----------
# 실제 위젯은 아래 탭1 '전국 최저가' 안의 설정 배너에 있음.
# 스트림릿은 위→아래로 실행되어 히어로/KPI가 값을 먼저 알아야 해서 session_state에서 읽어옴.
_mode = st.session_state.get("date_mode", "특정 날짜")
if _mode == "특정 날짜":
    _picked = st.session_state.get("scan_date", TODAY + dt.timedelta(days=1))
    target_dates = [_picked]
    period_label = _picked.isoformat()
else:
    _year = st.session_state.get("scan_year", TODAY.year)
    _month_opt = st.session_state.get("scan_month", "전체")
    if _month_opt == "전체":
        target_dates = [d for m in range(1, 13) for d in month_dates(_year, m)]
        period_label = f"{_year}년 전체"
    else:
        target_dates = month_dates(_year, int(_month_opt.replace("월", "")))
        period_label = f"{_year}년 {_month_opt}"
# 🌙 당일 야간 모드: 날짜를 오늘로 고정하고 16시 이후만 대상으로 함
TODAY_NIGHT = bool(st.session_state.get("today_night", False))
NIGHT_MIN_HOUR = 16 if TODAY_NIGHT else None
if TODAY_NIGHT:
    target_dates = [TODAY]
    period_label = TODAY.isoformat()
date_capped = len(target_dates) > MAX_DATES
if date_capped:
    target_dates = target_dates[:MAX_DATES]
only_am = st.session_state.get("only_am", False)
only_night = st.session_state.get("only_night", False)
caddie_sel = caddie_picks()

# 지도·날씨 탭용 샘플(지역·캐디 필터는 전체 기본)
df = load_data(USE_SAMPLE, tuple(d.isoformat() for d in target_dates))
region = "전체"
caddie_opt = CADDIE_OPTIONS

# ============================ 필터 적용 ============================
f = df.copy()
if region != "전체":
    f = f[f["region"] == region]
f = f[f["caddie"].isin(caddie_opt)]
if only_am and len(f):
    f = f[f["tee_time"].str.slice(0, 2).astype(int) < 12]
if only_night and len(f):
    f = f[f["tee_time"].str.slice(0, 2).astype(int) >= 17]
f = f.reset_index(drop=True)

# ============================ 실시간(티스캐너) 데이터 ============================
# 사람별 세션 토큰(로그인). 없으면 None → 전역(공유 secrets/파일) 토큰 사용.
USER_TOKENS = st.session_state.get("user_tokens")
REAL = bool(USER_TOKENS) or ts.has_token()
real_date = target_dates[0].isoformat() if target_dates else TODAY.isoformat()
real_all = pd.DataFrame()
real_err = ""
if REAL:
    try:
        real_all = ts_all_deals(real_date, USER_TOKENS)
        if not len(real_all):
            real_err = f"{real_date} 특가가 0곳으로 조회됨(날짜를 바꿔보세요)"
    except Exception as e:
        real_err = str(e)
USE_REAL = REAL and len(real_all) > 0

# 전국 최저가 스캔(전체 골프장 훑어 계산한 실제 최저가). 있으면 특가/KPI/팝업의 기준이 됨.
scan_df = ts_scan(real_date, NIGHT_MIN_HOUR) if REAL else pd.DataFrame()
USE_SCAN = REAL and len(scan_df) > 0

# ============================ 히어로 ============================
if USE_SCAN:
    _scan_tag = "🌙 당일 야간 최저가(16시↑)" if TODAY_NIGHT else "🔴 전국 최저가 스캔"
    chip = (f"📅 {real_date} · 전국 · 골프장 {len(scan_df):,}곳 · <b>{_scan_tag}</b>")
elif USE_REAL:
    chip = (f"📅 {real_date} · 전국 · 골프장 {real_all['seq'].nunique():,}곳 · "
            f"<b>🔴 티스캐너 추천 특가</b>")
elif REAL:
    chip = f"📅 {real_date} · 이 날짜는 예약 데이터가 없어요 · <b>내일 이후 날짜를 선택하세요</b>"
else:
    chip = "🔒 위쪽 <b>👤 티스캐너 로그인</b>에서 로그인하면 실시간 데이터가 나와요"
st.markdown(f"""
<div class="hero">
  <div class="flag">⛳</div>
  <div class="hero-kick">🔴 실시간 티타임 · 캐디 · 최저가</div>
  <h1>전국 골프장<br>티타임 통합검색</h1>
  <p>싱그러운 페어웨이 위, 실시간 그린피 · 캐디 포함여부를 한눈에</p>
  <span class="chip">{chip}</span>
</div>
""", unsafe_allow_html=True)

@st.fragment
def deal_panel(tokens, fallback):
    """오늘부터 30일 · 6만원 이하 특가 패널(지역 다중선택 + 닫기).
    패널 틀을 먼저 그리고, 데이터는 안에서 불러와서 '아예 안 뜨는' 문제를 방지."""
    allr = list(ts.REGION_MAP.keys())
    with st.container(border=True, key="deal_modal"):
        hc = st.columns([6, 2.2, 1.6], vertical_alignment="center")
        hc[0].markdown(f"#### 🔥 오늘부터 {POPUP_DAYS}일 특가 · 18홀 기준 6만원 이하")
        with hc[1]:
            pk_prev = [r for r in allr if st.session_state.get(f"dealreg_{r}", True)]
            lbl = ("🗺️ 지역 전체" if len(pk_prev) == len(allr)
                   else (f"🗺️ 지역 {len(pk_prev)}곳" if pk_prev else "🗺️ 지역 선택"))
            with st.popover(lbl, use_container_width=True):
                b = st.columns(2)
                if b[0].button("전체선택", key="dealreg_all", use_container_width=True):
                    for r in allr:
                        st.session_state[f"dealreg_{r}"] = True
                if b[1].button("전체해제", key="dealreg_none", use_container_width=True):
                    for r in allr:
                        st.session_state[f"dealreg_{r}"] = False
                with st.container(height=200):
                    for r in allr:
                        st.session_state.setdefault(f"dealreg_{r}", True)
                        st.checkbox(r, key=f"dealreg_{r}")
        with hc[2]:
            if st.button("✕ 닫기", key="deal_close", use_container_width=True):
                st.session_state.deal_open = False
                st.rerun()

        # 데이터: 오늘부터 30일. 비면 오늘 특가(fallback).
        with st.spinner("특가 불러오는 중..."):
            try:
                rng = ts_deals_range(TODAY.isoformat(), POPUP_DAYS, tokens)
            except Exception:
                rng = pd.DataFrame()
        # 후보: 0원 제외 + 원가 6만원 이하(9홀 x2도 6만원 넘으려면 원가 3만↑라 후보는 6만 이하로 충분)
        cand = (rng[rng["min_cost"].notna() & (rng["min_cost"] > 0)
                    & (rng["min_cost"] <= POPUP_PRICE_CAP)]
                if len(rng) else pd.DataFrame())
        used_fallback = False
        if not len(cand) and fallback is not None and len(fallback):
            cand = fallback[fallback["min_cost"].notna() & (fallback["min_cost"] > 0)
                            & (fallback["min_cost"] <= POPUP_PRICE_CAP)]
            used_fallback = True

        if not len(cand):
            st.info("지금은 조건에 맞는 특가 매물이 없어요. (티스캐너 추천특가 기준 · 날짜/지역에 따라 없을 수 있어요) "
                    "잠시 뒤 **🔥 다시 보기**를 눌러보세요.")
        else:
            if used_fallback:
                st.caption("⚠️ 30일 특가 조회가 비어 있어 **오늘 기준 특가**로 보여드려요.")
            # 후보(원가 낮은순 상위 180)의 캐디·홀 정보를 한 번만 병렬 수집
            base = cand.sort_values("min_cost").head(180)
            pairs = tuple((r["date"], int(r["seq"])) for _, r in base.iterrows()
                          if pd.notna(r.get("seq")))
            with st.spinner("캐디·홀 정보 확인 중..."):
                details = ts_deal_details(pairs, tokens)

            # 18홀 기준 가격 계산: 9홀은 x2, 18홀/미상은 그대로. 18홀 기준 6만원 이하만.
            recs = []
            for _, r in base.iterrows():
                if pd.isna(r.get("seq")):
                    continue
                key = (r["date"], int(r["seq"]))
                cad_raw, cname = details.get(key, ("", ""))
                holes = holes_from_name(cname)
                raw = int(r["min_cost"])
                if holes == "9홀":
                    price18, basis = raw * 2, "9홀×2"
                else:
                    price18, basis = raw, "18홀"    # 18홀 또는 미상은 그대로(18홀 기준)
                if price18 <= POPUP_PRICE_CAP:
                    recs.append({"course": r["course"], "region_kr": r.get("region_kr", ""),
                                 "date": r["date"], "seq": int(r["seq"]),
                                 "price18": price18, "raw": raw, "basis": basis, "caddie": cad_raw})
            final = pd.DataFrame(recs)

            pick = [r for r in allr if st.session_state.get(f"dealreg_{r}", True)]
            dv = final
            if len(final):
                if not pick:
                    dv = dv.iloc[0:0]
                elif len(pick) < len(allr):
                    dv = dv[dv["region_kr"].isin(pick)]
                dv = dv.sort_values(["price18", "date"]).reset_index(drop=True)
            if not len(dv):
                st.info("선택한 지역에는 18홀 기준 6만원 이하 특가가 없어요. 지역을 바꿔보세요.")
            else:
                st.caption(f"총 {len(dv):,}건 · 18홀 기준 가격 낮은순 (9홀은 그린피×2로 계산)")
                rows = []
                for _, r in dv.head(80).iterrows():
                    cad = caddie_pill(str(r["caddie"]))
                    price = f"{int(r['price18']):,}원"
                    if r["basis"] == "9홀×2":
                        basis_html = (f"<span style='color:#c026d3;font-weight:800'>· 9홀×2</span>")
                        price_sub = f"<div style='font-size:11px;color:#8a9a8f'>(9홀 {int(r['raw']):,}원)</div>"
                    else:
                        basis_html = "<span style='color:#2b6b3f;font-weight:800'>· 18홀</span>"
                        price_sub = ""
                    url = booking_url(r["seq"], r["date"])
                    rows.append(
                        "<div class='deal-row'>"
                        f"<div><div class='name'>{r['course']} "
                        f"<span style='color:#7a8f80;font-weight:600'>· {r['region_kr']}</span></div>"
                        f"<div class='meta'>📅 {r['date']}  {basis_html}</div></div>"
                        "<div style='text-align:right;display:flex;align-items:center;gap:10px'>"
                        f"{cad}<div><div class='pr'>{price}</div>{price_sub}</div>"
                        f"<a class='book-btn' href='{url}' target='_blank' rel='noopener'>예약</a></div></div>")
                with st.container(height=430):
                    st.markdown("".join(rows), unsafe_allow_html=True)
                if len(dv) > 80:
                    st.caption(f"※ 많아서 상위 80건만 표시 (총 {len(dv):,}건)")
        if st.checkbox("오늘 하루 이 창 안 열기", key="deal_hide_today"):
            dismiss_today()
            st.session_state.deal_open = False
            st.rerun()


# ============================ 30일 특가 패널 (접속 시 표시 · 지역선택 · 닫기) ============================
# 모달(팝업)이 초기 자동-리런과 부딪혀 깜빡이던 문제를 없애려고, 상단 특가 패널로 구현.
if REAL:
    if "deal_open" not in st.session_state:
        st.session_state.deal_open = not dismissed_today()   # 최초 접속 시 자동으로 열림
    _rb = st.columns([2.2, 5])
    if _rb[0].button("🔥 30일 특가 다시 보기", type="primary", key="reopen_deals"):
        st.session_state.deal_open = True
    if st.session_state.deal_open:
        deal_panel(USER_TOKENS, real_all)

if date_capped:
    st.caption(f"⚡ 성능 보호를 위해 선택 기간 중 앞 {MAX_DATES}일만 불러왔습니다.")

# ============================ KPI ============================
if USE_SCAN:
    sc = scan_df[scan_df["min_cost"].notna()]
    n_deal = int((sc["min_cost"] <= DEAL_LIMIT_PRICE).sum()) if len(sc) else 0
    cards = (
        kpi("🏷️", "전국 최저가", f"{int(sc['min_cost'].min()):,}원" if len(sc) else "-", hl=True)
        + kpi("📊", "평균 최저가", f"{int(sc['min_cost'].mean()):,}원" if len(sc) else "-")
        + kpi("📍", "예약가능 골프장", f"{len(scan_df)}곳")
        + kpi("🔥", "특가(7만↓)", f"{n_deal}곳")
    )
    st.markdown(f"<div class='kpi-grid'>{cards}</div>", unsafe_allow_html=True)
elif USE_REAL:
    ra = real_all[real_all["min_cost"].notna()]
    cards = (
        kpi("🏷️", "실시간 최저가", f"{int(ra['min_cost'].min()):,}원" if len(ra) else "-", hl=True)
        + kpi("📊", "평균 최저가", f"{int(ra['min_cost'].mean()):,}원" if len(ra) else "-")
        + kpi("📍", "골프장 수", f"{real_all['seq'].nunique()}곳")
        + kpi("🔥", "추천 특가", f"{len(real_all)}곳")
    )
    st.markdown(f"<div class='kpi-grid'>{cards}</div>", unsafe_allow_html=True)
elif REAL and TODAY_NIGHT:
    st.info("🌙 **당일 야간** 모드예요. 아래 **📋 티타임 목록** 탭에서 "
            "**🌙 오늘 야간(16시↑) 최저가 스캔** 버튼을 눌러 오늘 남은 야간 티타임을 모아보세요.")
elif REAL:
    st.info(f"📅 **{real_date}** 은 예약 가능한 데이터가 없어요. "
            "아래 **📋 티타임 목록** 탭의 **📅 날짜·선택사항 설정**에서 "
            "**내일 이후 날짜**를 골라주세요. (당일 예약은 거의 없어요)")
else:
    st.info("🔒 위쪽 **👤 티스캐너 로그인**에서 본인 계정으로 로그인하면 "
            "전국 실시간 티타임·최저가가 나와요.")

# 검색 응답속도 개선: 지도·날씨 탭과 전국최저가 표는 st.fragment로 감싸 '그 부분만' 다시 그리게 함
# (검색어를 한 글자 칠 때마다 앱 전체가 아니라 이 함수만 재실행됨)
@st.fragment
def _scan_results_body(scan_df, real_date, tokens, only_am, only_night, today_night=False):
    sdf = scan_df.copy()
    allregs = sorted([x for x in sdf["region"].unique() if x])
    hc1, hc2, hc3 = st.columns([3, 1.4, 1.3], vertical_alignment="bottom")
    with hc1:
        squery = st_keyup("검색", placeholder="🔍 골프장 검색 (예: 이글밸리, CC)",
                          debounce=120, label_visibility="collapsed", key="scan_search")
    with hc2:
        # 지역 다중선택(체크박스) — 체크된 지역만 아래 표에 나옴
        picked_prev = [rg for rg in allregs if st.session_state.get(f"scanreg_{rg}", True)]
        plabel = ("🗺️ 지역 전체" if len(picked_prev) == len(allregs)
                  else (f"🗺️ 지역 {len(picked_prev)}곳" if picked_prev else "🗺️ 지역 선택"))
        with st.popover(plabel, use_container_width=True):
            bc1, bc2 = st.columns(2)
            if bc1.button("전체선택", key="scanreg_all", use_container_width=True):
                for rg in allregs:
                    st.session_state[f"scanreg_{rg}"] = True
            if bc2.button("전체해제", key="scanreg_none", use_container_width=True):
                for rg in allregs:
                    st.session_state[f"scanreg_{rg}"] = False
            with st.container(height=210):
                for rg in allregs:
                    st.session_state.setdefault(f"scanreg_{rg}", True)
                    st.checkbox(rg, key=f"scanreg_{rg}")
    with hc3:
        ssort = st.selectbox("정렬", ["가격 낮은순", "가격 높은순"],
                             label_visibility="collapsed", key="scan_sort")
    picked_regs = [rg for rg in allregs if st.session_state.get(f"scanreg_{rg}", True)]
    sv = sdf
    if not picked_regs:
        sv = sv.iloc[0:0]
    elif len(picked_regs) < len(allregs):
        sv = sv[sv["region"].isin(picked_regs)]
    if squery:
        sv = sv[sv["course"].str.contains(squery.strip(), case=False, na=False)]
    caddie_pick = caddie_picks()
    if len(caddie_pick) < len(CADDIE_FILTER_OPTS):
        sv = sv[sv["caddie"].map(caddie_class).isin(caddie_pick)]
    sv = sv.sort_values("min_cost", ascending=(ssort == "가격 낮은순")).reset_index(drop=True)

    if not len(sv):
        st.info("조건에 맞는 골프장이 없어요. 지역이나 검색어를 바꿔보세요.")
        return
    st.caption(f"전국 {len(sv):,}곳 · 표에서 **골프장 행을 클릭**하면 하단에 티타임 상세가 나와요.")
    has_cname = "course_name" in sv.columns
    best_price = sdf["min_cost"].min()
    rows = []
    for _, r in sv.iterrows():
        cname = (_html.unescape(str(r["course_name"]))
                 if has_cname and pd.notna(r.get("course_name")) and str(r["course_name"]).strip()
                 else "-")
        rows.append({
            "seq": (None if pd.isna(r.get("seq")) else int(r["seq"])),
            "course": str(r["course"]),
            "area": str(r["area"]),
            "min_cost": int(r["min_cost"]),
            "course_name": cname,
            "caddie": str(r["caddie"] or ""),
            "score": (None if pd.isna(r["score"]) else float(r["score"])),
            "is_deal": bool(r["min_cost"] <= DEAL_LIMIT_PRICE),
            "is_best": bool(r["min_cost"] == best_price),
        })
    selected = st.session_state.get("scan_sel_course")
    clicked = _scan_table(rows=rows, selected=selected, date=real_date,
                          key="scan_tbl", default=None)
    if clicked:
        st.session_state.scan_sel_course = clicked
        selected = clicked

    if selected and (sv["course"] == selected).any():
        detail_course = selected
    else:
        detail_course = sv.iloc[0]["course"]

    # ---- 골프장별 티타임 상세 (행 클릭 → 여기로 스크롤) ----
    st.divider()
    st.markdown("<div id='tt-detail'></div>", unsafe_allow_html=True)
    st.markdown(f"###### ⛳ {detail_course} · 티타임 상세")
    if not selected:
        st.caption("👆 위 표에서 골프장 행을 클릭하면 그 골프장으로 바뀌어요. (지금은 최저가 골프장)")
    sel = sv[sv["course"] == detail_course].iloc[0]
    try:
        ttdf = ts_tee_times(real_date, int(sel["seq"]), tokens)
        if today_night:
            ttdf = filter_tee_times(ttdf, False, True, night_hour=16)
        else:
            ttdf = filter_tee_times(ttdf, only_am, only_night)
        if len(ttdf):
            st.caption(f"✅ {detail_course} · {real_date} · 티타임 {len(ttdf)}개 (시간순)")
            st.markdown(tee_time_table_html(ttdf, sel["seq"], real_date), unsafe_allow_html=True)
        else:
            st.info(f"{detail_course}는 {real_date}에 (오전/야간 필터 포함) 예약 가능한 티타임이 없어요.")
    except Exception as e:
        st.warning(f"티타임 상세 불러오기 실패: {e}")


@st.fragment
def _map_tab_body():
    if not len(f):
        return
    courses_df = (f.dropna(subset=["lat", "lon"]).drop_duplicates("course")
                  .sort_values("course")[["course", "region", "city", "holes", "gubun", "lat", "lon"]])
    left, right = st.columns([1.35, 1])
    with right:
        st.markdown("##### 🔎 골프장 검색")
        map_query = st_keyup("CC검색", placeholder="🔍 골프장 이름 검색 (한 글자씩 실시간)",
                             debounce=120, label_visibility="collapsed", key="map_search")
        listed = courses_df
        if map_query:
            listed = listed[listed["course"].str.contains(map_query.strip(), case=False, na=False)]
        shown = listed.head(50)
        m_items = [{"course": r["course"], "sub": f"{r['city']} · {r['holes']}홀 · {r['gubun']}"}
                   for _, r in shown.iterrows()]
        map_sel = st.session_state.get("map_course")
        if map_sel and not (shown["course"] == map_sel).any():
            map_sel = None
        clicked_map = _course_list(items=m_items, selected=map_sel, key="map_list", default=None)
        if clicked_map:
            st.session_state.map_course = clicked_map
            map_sel = clicked_map
        extra = " (상위 50곳 표시)" if len(listed) > 50 else ""
        st.caption(f"총 {len(listed):,}곳{extra} · 목록에서 골프장을 누르면 왼쪽 지도가 그 위치로 이동해요")
    with left:
        st.markdown("##### 📍 골프장 위치 (OpenStreetMap)")
        if len(shown):
            if map_sel:
                frow = shown[shown["course"] == map_sel].iloc[0]
                st.markdown(f"**📌 {map_sel}** · {frow['city']} · {frow['holes']}홀 · {frow['gubun']}")
            st_folium(folium_map(shown, focus=map_sel), height=460,
                      use_container_width=True, returned_objects=[])
        else:
            st.info("검색 결과가 없어 지도에 표시할 골프장이 없어요.")
        st.caption("※ 초록 점이 선택한 골프장이에요. 점을 클릭하면 길찾기 버튼이 나와요. "
                   "좌표는 지역 기준 근사값(공공데이터에 좌표 미포함).")


@st.fragment
def _weather_tab_body():
    if not len(f):
        return
    wcourses = (f.dropna(subset=["lat", "lon"]).drop_duplicates("course")
                .sort_values("course")[["course", "region", "city", "holes", "gubun", "lat", "lon"]])
    st.markdown("##### 🔎 골프장 검색")
    wq = st_keyup("wx검색", placeholder="🔍 골프장 이름 검색 (한 글자씩 실시간)",
                  debounce=120, label_visibility="collapsed", key="wx_search")
    wlisted = wcourses
    if wq:
        wlisted = wlisted[wlisted["course"].str.contains(wq.strip(), case=False, na=False)]
    shown = wlisted.head(50)
    w_items = [{"course": r["course"], "sub": f"{r['city']} · {r['holes']}홀 · {r['gubun']}"}
               for _, r in shown.iterrows()]
    wx_sel = st.session_state.get("wx_course")
    if wx_sel and not (shown["course"] == wx_sel).any():
        wx_sel = None
    clicked_wx = _course_list(items=w_items, selected=wx_sel, key="wx_list", default=None)
    if clicked_wx:
        st.session_state.wx_course = clicked_wx
        wx_sel = clicked_wx
    if not wx_sel:
        wx_sel = shown.iloc[0]["course"] if len(shown) else None
    extra = " (상위 50곳)" if len(wlisted) > 50 else ""
    st.caption(f"검색 {len(wlisted):,}곳{extra} · 골프장을 누르면 그 골프장 날씨가 나와요")

    if not wx_sel:
        st.info("검색 결과가 없어요. 다른 이름으로 검색해보세요.")
        return
    row = wcourses[wcourses["course"] == wx_sel].iloc[0]
    st.markdown(f"##### ☀️ {wx_sel} ({row['city']}) 날씨 예보")
    raw = weather_raw(float(row["lat"]), float(row["lon"]))
    real = raw is not None
    # 날짜 선택: 이 날짜 앞뒤 3일씩(총 7일) 주간예보 + 그날 시간대별
    wx_pick = st.date_input("날짜 선택 (이 날짜 앞뒤 3일씩 주간예보 + 시간대별)",
                            value=TODAY, min_value=TODAY,
                            max_value=TODAY + dt.timedelta(days=12),
                            format="YYYY-MM-DD", key="wx_date")
    pick_iso = wx_pick.isoformat()
    if real:
        all_daily = wx.om_daily(raw, days=30)
        st.caption("✅ 실시간 날씨 예보 (Open-Meteo · 무료)")
    else:
        all_daily = wx.sample_forecast(16)
        st.caption("※ 인터넷 연결이 없어 샘플 예보입니다.")
    lo = (wx_pick - dt.timedelta(days=3)).isoformat()
    hi = (wx_pick + dt.timedelta(days=3)).isoformat()
    week = [d for d in all_daily if lo <= d["date"] <= hi] or all_daily[:7]
    wdf = pd.DataFrame(week)
    if len(wdf):
        st.markdown(f"###### 📅 주간 예보 ({pick_iso} 앞뒤 3일)")
        cols = st.columns(len(wdf))
        for i, (_, w) in enumerate(wdf.iterrows()):
            is_pick = (w["date"] == pick_iso)
            with cols[i]:
                wind_txt = f"{w['wind']} m/s" if w.get("wind") is not None else "-"
                hl = "border:2px solid #16A34A;box-shadow:0 8px 20px -12px rgba(22,163,74,.6);" if is_pick else ""
                star = " ⭐" if is_pick else ""
                st.markdown(
                    f"<div class='kpi-card' style='text-align:center;padding:16px 10px;{hl}'>"
                    f"<div class='label'>{w['date'][5:]}{star}</div>"
                    f"<div style='font-size:32px;margin:6px 0'>{wemoji(w['day_text'])}</div>"
                    f"<div class='value' style='font-size:19px'>{w['max']}° <span style='color:#8fa295'>/ {w['min']}°</span></div>"
                    f"<div class='wcard-sub'>💧 {w['rain_prob']}%</div>"
                    f"<div class='wcard-sub'>🌬 {wind_txt}</div></div>",
                    unsafe_allow_html=True)

        st.markdown("###### ⏰ 시간대별 날씨 (0~23시)")
        hourly = wx.om_hourly(raw, pick_iso) if real else []
        if hourly:
            st.caption(f"{pick_iso} · ✅ 실시간 시간대별 예보 (Open-Meteo)")
        else:
            if real:
                st.caption(f"{pick_iso}은 예보 범위(약 16일) 밖이라 샘플로 표시합니다.")
            day = wx.sample_day(pick_iso)
            hourly = wx.sample_hourly(pick_iso, day["min"], day["max"])
        cells = [
            f"<div class='hour-cell'><div class='hh'>{h['hour']}시</div>"
            f"<div class='ic'>{wemoji(h['sky'])}</div>"
            f"<div class='tt'>{h['temp']:.0f}°</div>"
            f"<div class='rr'>💧 {h['rain_prob']}%</div>"
            f"<div class='ww'>🌬 {h['wind']}</div></div>"
            for h in hourly
        ]
        st.markdown("<div class='hour-strip'>" + "".join(cells) + "</div>", unsafe_allow_html=True)
        st.caption("가로로 스크롤하면 0시~23시 전체가 보여요 · 숫자: 기온 · 💧강수확률 · 🌬바람(m/s)")
    else:
        st.info("예보를 불러오지 못했습니다. 잠시 후 다시 시도하세요.")


tab1, tab2, tab3, tab4 = st.tabs(["📋 티타임 목록", "📍 골프장 위치검색", "☀️ 날씨 예보", "🔍 골프장 검색"])

# ---------------- 탭 1: 목록 ----------------
with tab1:
    t1mode = st.radio("보기 방식", ["🔥 전국 최저가", "🌏 전국 전체 골프장"],
                      horizontal=True, key="t1mode", label_visibility="collapsed") if REAL else None
    if REAL and t1mode == "🔥 전국 최저가":
        st.markdown("<div id='scan-top'></div>", unsafe_allow_html=True)
        st.markdown("##### 🔥 전국 최저가 (전체 골프장 스캔 기준)")
        cat_df0 = ts_catalog()
        n_catalog = len(cat_df0)

        # ---- 날짜 · 선택사항 · 스캔 버튼 (여기서 고르고 맨 아래 버튼으로 검색) ----
        with st.expander("📅 날짜 · 선택사항 설정 (여기를 눌러 열기)", expanded=not USE_SCAN):
            st.checkbox("🌙 당일 야간만 보기 (오늘 16시 이후)", value=False, key="today_night",
                        help="오늘 16시 이후 남은 야간 티타임만 모아 최저가를 보여줘요. "
                             "당일 야간은 아주 싸게 나오는 경우가 많아요. (날짜는 오늘로 고정)")
            if TODAY_NIGHT:
                st.caption(f"🌙 **당일 야간** 모드 · 날짜는 **오늘({TODAY.isoformat()})**, "
                           "**16시 이후** 티타임만 스캔해요.")
            else:
                smode = st.radio("조회 방식", ["특정 날짜", "월간 검색"],
                                 horizontal=True, key="date_mode")
                if smode == "특정 날짜":
                    st.date_input("날짜", value=TODAY + dt.timedelta(days=1), min_value=TODAY,
                                  max_value=TODAY.replace(year=TODAY.year + 5),
                                  format="YYYY-MM-DD", key="scan_date")
                else:
                    years = list(range(TODAY.year, TODAY.year + 5))
                    ycol, mcol = st.columns(2)
                    ycol.selectbox("연도", years, format_func=lambda y: f"{y}년", key="scan_year")
                    mcol.selectbox("월", ["전체"] + [f"{m}월" for m in range(1, 13)], key="scan_month")
            st.markdown("**옵션 선택** — 원하는 항목만 체크하세요")
            o1, o2, o3, o4, o5 = st.columns(5)
            o1.checkbox("오전만", value=False, key="only_am", help="12시 이전 티타임만",
                        disabled=TODAY_NIGHT)
            o2.checkbox("야간만", value=False, key="only_night", help="17시 이후 티타임만",
                        disabled=TODAY_NIGHT)
            o3.checkbox("캐디필수", value=True, key="cad_req")
            o4.checkbox("노캐디", value=True, key="cad_no")
            o5.checkbox("캐디선택가능", value=True, key="cad_sel")
            st.caption("👇 아래 버튼을 누르면 위 설정으로 전국 최저가를 검색해요")
            scan_label = (f"🌙 오늘 야간(16시↑) 최저가 스캔" if TODAY_NIGHT
                          else f"⚡ {real_date} 전국 최저가 스캔")
            scan_clicked = st.button(scan_label, type="primary", key="scan_btn",
                                     disabled=(n_catalog == 0), width="stretch")
        if USE_SCAN:
            tail = " · 오늘 16시 이후" if TODAY_NIGHT else ""
            st.caption(f"✅ 스캔 완료 · {len(scan_df):,}곳 예약가능{tail} · 버튼을 누르면 최신가로 갱신돼요")
        elif n_catalog:
            base = ("전국 골프장의 오늘 16시 이후 야간 티타임만 훑어요"
                    if TODAY_NIGHT else f"전국 {n_catalog:,}곳을 훑어 실제 최저가를 계산해요")
            st.caption(f"{base} (약 1~2분 · 저장됨)")
        else:
            st.caption("먼저 '🌏 전국 전체 골프장'에서 목록을 만들어 주세요")

        if scan_clicked and n_catalog:
            scan_txt = "당일 야간 스캔 중..." if TODAY_NIGHT else "전국 최저가 스캔 중..."
            bar = st.progress(0.0, text=scan_txt)
            rows = SCAN.scan_prices(
                cat_df0.to_dict("records"), real_date, tokens=USER_TOKENS, min_hour=NIGHT_MIN_HOUR,
                progress=lambda i, n, found: bar.progress(i / n, text=f"스캔 중... {i}/{n} · {found}곳 가격확인"))
            SCAN.save(real_date, rows, NIGHT_MIN_HOUR)
            ts_scan.clear()
            bar.empty()
            st.session_state.scan_just_done = True
            st.rerun()

        if USE_SCAN:
            _scan_results_body(scan_df, real_date, USER_TOKENS, only_am, only_night, TODAY_NIGHT)

        elif USE_REAL:
            st.info("아직 이 날짜의 전국 최저가 스캔이 없어요. 위 **⚡ 전국 최저가 스캔**을 누르면 "
                    "전체 골프장에서 실제 최저가를 뽑아드려요. 아래는 티스캐너 '추천 특가'(빠른 미리보기)예요.")
            rv = real_all.sort_values("min_cost").reset_index(drop=True)
            rows_html = []
            for i, r in rv.iterrows():
                price = f"{int(r['min_cost']):,}원" if pd.notna(r["min_cost"]) else "-"
                is_deal = pd.notna(r["min_cost"]) and r["min_cost"] <= DEAL_LIMIT_PRICE
                price_html = f"<span class='deal-price'>{price}</span>" if is_deal else price
                review = f"⭐{r['review']}" if pd.notna(r["review"]) else "-"
                rows_html.append(
                    f"<tr><td class='rank'>{i + 1}</td>"
                    f"<td class='course'>{r['course']}</td><td>{r['area']}</td>"
                    f"<td class='money'>{price_html}</td><td>{r['gubun']}</td><td>{review}</td>"
                    f"<td style='text-align:left'>{r['benefit']}</td>"
                    f"<td><a class='book-btn' href='{booking_url(r.get('seq'), real_date)}' "
                    f"target='_blank' rel='noopener'>예약</a></td></tr>"
                )
            table = (
                "<div class='table-wrap'><table class='golf-table'><thead><tr>"
                "<th>#</th><th>골프장</th><th>지역</th><th>최저 그린피</th><th>구분</th><th>평점</th><th>혜택</th><th>예약</th>"
                "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div>"
            )
            st.markdown(table, unsafe_allow_html=True)
        elif TODAY_NIGHT:
            st.info("🌙 **당일 야간(오늘 16시 이후)** 최저가를 보려면 위 **🌙 오늘 야간(16시↑) 최저가 스캔** "
                    "버튼을 눌러주세요. 오늘 남은 야간 티타임만 모아 최저가를 계산해요.")
        else:
            st.info(f"📅 **{real_date}** 은 예약 가능한 특가가 없어요(당일은 거의 없어요). "
                    "위 **📅 날짜·선택사항 설정**에서 **내일 이후 날짜**를 골라보세요. 특정 골프장을 찾으려면 "
                    "'🌏 전국 전체 골프장' 또는 '🔍 골프장 검색' 탭을 이용하세요.")

        # 스캔 직후에는 상세로 튀지 않게 최저가 표 상단으로 화면 고정
        if st.session_state.pop("scan_just_done", False):
            components.html(
                "<script>const t=window.parent.document.getElementById('scan-top');"
                "if(t) t.scrollIntoView({behavior:'auto', block:'start'});</script>",
                height=0,
            )

    elif REAL and t1mode == "🌏 전국 전체 골프장":
        st.markdown("##### 🌏 전국 전체 골프장 (티스캐너)")
        cat_df = ts_catalog()
        if not len(cat_df):
            st.info("아직 전국 골프장 목록이 없어요. 아래 버튼으로 한 번만 만들면 이후엔 바로 떠요. (약 1분)")
            if st.button("🌏 전국 골프장 목록 만들기", type="primary", key="cat_build"):
                bar = st.progress(0.0, text="티스캐너에서 골프장 수집 중...")
                clubs = CAT.build(tokens=USER_TOKENS, progress=lambda i, n, found:
                                  bar.progress(i / n, text=f"수집 중... {i}/{n} · {found}곳 발견"))
                CAT.save(clubs)
                ts_catalog.clear()
                bar.empty()
                st.success(f"{len(clubs)}곳 수집 완료!")
                st.rerun()
        else:
            cat_df = cat_df.copy()
            cat_df["region"] = cat_df["area"].map(CAT.top_region)
            regions_c = ["전체"] + sorted([x for x in cat_df["region"].unique() if x])
            cc1, cc2 = st.columns([3, 1.3], vertical_alignment="bottom")
            with cc1:
                catq = st_keyup("검색", placeholder="🔍 골프장 이름 검색 (실시간)",
                                debounce=200, label_visibility="collapsed", key="cat_search")
            with cc2:
                catreg = st.selectbox("지역", regions_c, label_visibility="collapsed", key="cat_region")
            cv = cat_df
            if catreg != "전체":
                cv = cv[cv["region"] == catreg]
            if catq:
                cv = cv[cv["course"].str.contains(catq.strip(), case=False, na=False)]
            cv = cv.reset_index(drop=True)
            st.caption(f"전국 {len(cat_df):,}곳 중 {len(cv):,}곳 · 골프장을 고르면 {real_date} 실제 티타임이 나와요")
            if not len(cv):
                st.info("검색 결과가 없어요. 이름이나 지역을 바꿔보세요.")
            else:
                labels = [
                    f"{r['course']}  ·  {r['area']}" + (f"  ⭐{r['score']}" if pd.notna(r["score"]) else "")
                    for _, r in cv.iterrows()
                ]
                ci = st.selectbox("골프장 선택", range(len(labels)),
                                  format_func=lambda i: labels[i], key="cat_pick")
                sel = cv.iloc[ci]
                if sel.get("address"):
                    st.caption(f"📍 {sel['address']}")
                try:
                    cttdf = ts_tee_times(real_date, int(sel["seq"]), USER_TOKENS)
                    cttdf = filter_tee_times(cttdf, only_am, only_night)
                    if len(cttdf):
                        st.caption(f"✅ {sel['course']} · {real_date} · 티타임 {len(cttdf)}개 (시간순)")
                        st.markdown(tee_time_table_html(cttdf, sel["seq"], real_date), unsafe_allow_html=True)
                    else:
                        st.info(f"{sel['course']}는 {real_date}에 (오전/야간 필터 포함) 예약 가능한 티타임이 없어요. "
                                "위쪽 날짜나 필터를 바꿔보세요.")
                except Exception as e:
                    st.warning(f"티타임 불러오기 실패: {e}")
            st.divider()
            st.caption(f"※ 전국 목록은 티스캐너 이름검색을 모아 만든 거예요(현재 {len(cat_df):,}곳). "
                       "더 많이 모으려면 아래 버튼을 누르세요.")
            if st.button("🔄 전국 목록 다시 수집 (더 많이, 약 1분)", key="cat_rebuild"):
                bar = st.progress(0.0, text="다시 수집 중...")
                clubs = CAT.build(tokens=USER_TOKENS, progress=lambda i, n, found:
                                  bar.progress(i / n, text=f"수집 중... {i}/{n} · {found}곳 발견"))
                CAT.save(clubs)
                ts_catalog.clear()
                bar.empty()
                st.success(f"{len(clubs)}곳으로 갱신 완료!")
                st.rerun()

    else:
        st.info("🔒 위쪽 **👤 티스캐너 로그인**에서 본인 계정으로 로그인하면 "
                "여기에 전국 실시간 티타임·최저가가 나와요.")

# ---------------- 탭 2: 골프장 위치검색 ----------------
with tab2:
    _map_tab_body()

# ---------------- 탭 3: 날씨 ----------------
with tab3:
    _weather_tab_body()

# ---------------- 탭 4: 전국 골프장 검색 ----------------
with tab4:
    st.markdown("##### 🔍 전국 골프장 검색")
    if not REAL:
        st.info("실시간 검색을 하려면 위쪽 **👤 티스캐너 로그인**에서 본인 계정으로 로그인하세요.")
    else:
        st.caption("전국 골프장을 이름으로 검색해서 실제 티타임을 볼 수 있어요. (예: 이글밸리, 남서울, 스카이72)")
        sc1, sc2 = st.columns([2, 1], vertical_alignment="bottom")
        with sc1:
            kw = st.text_input("골프장 이름", placeholder="🔍 골프장 이름을 입력하세요 (2글자 이상)",
                               key="ts_search_kw")
        with sc2:
            search_date = st.date_input("날짜", value=TODAY + dt.timedelta(days=1),
                                        min_value=TODAY, format="YYYY-MM-DD", key="ts_search_date")

        kw = (kw or "").strip()
        if len(kw) < 2:
            st.info("골프장 이름을 2글자 이상 입력하면 전국에서 검색해드려요.")
        else:
            try:
                sdf = ts_search(kw, USER_TOKENS)
                if not len(sdf):
                    st.warning(f"'{kw}' 검색 결과가 없어요. 다른 이름으로 검색해보세요.")
                else:
                    st.caption(f"✅ '{kw}' 검색 결과 {len(sdf)}곳 — 골프장을 고르면 {search_date.isoformat()} 티타임이 나와요.")
                    labels = [
                        f"{r['course']}"
                        + (f"  ·  {r['area']}" if r["area"] else "")
                        + (f"  ⭐{r['score']}" if pd.notna(r["score"]) else "")
                        for _, r in sdf.iterrows()
                    ]
                    idx = st.selectbox("검색된 골프장", range(len(labels)),
                                       format_func=lambda i: labels[i], key="ts_search_pick")
                    sel = sdf.iloc[idx]
                    if sel.get("address"):
                        st.caption(f"📍 {sel['address']}")
                    try:
                        sttdf = ts_tee_times(search_date.isoformat(), int(sel["seq"]), USER_TOKENS)
                        sttdf = filter_tee_times(sttdf, only_am, only_night)
                        if len(sttdf):
                            st.caption(f"✅ {sel['course']} · {search_date.isoformat()} · 티타임 {len(sttdf)}개 (시간순)")
                            st.markdown(tee_time_table_html(sttdf, sel["seq"], search_date.isoformat()),
                                        unsafe_allow_html=True)
                        else:
                            st.info(f"{sel['course']}는 {search_date.isoformat()}에 (오전/야간 필터 포함) "
                                    "예약 가능한 티타임이 없어요. 다른 날짜나 필터를 골라보세요.")
                    except Exception as e:
                        st.warning(f"티타임 불러오기 실패: {e}")
            except Exception as e:
                st.error(f"검색 실패: {e}\n\n토큰(x-refresh-token)이 만료됐을 수 있어요(약 6개월). "
                         "크롬 F12 → Network에서 토큰을 새로 복사해 teescanner.py에 다시 넣어주세요.")

st.divider()
st.caption("⚠️ 실제 예약사이트 데이터를 쓰려면 각 사이트 약관·robots.txt를 확인하세요. 예약 버튼은 각 출처 플랫폼 사이트로 연결됩니다.")
