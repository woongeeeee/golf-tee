"""
teescanner.py — 티스캐너 실시간 특가 데이터.

✅ 좋은 소식: 티스캐너는 짧은 x-token 은 사실상 검사하지 않고, 긴 x-refresh-token(약 6개월)만
   유효하면 요청을 통과시켜 줍니다. 그래서 아래 두 토큰을 한 번만 넣어두면 약 6개월 동안
   아무것도 안 해도 계속 실제 데이터가 나옵니다.

최초 1회만:
  아래 X_TOKEN, X_REFRESH_TOKEN 에 본인 토큰을 붙여넣으세요.
  (크롬 F12 → Network의 x-token / x-refresh-token 값)
  ⚠️ 토큰은 비밀번호 같은 값이라 공개된 곳에 올리지 마세요.
  ⚠️ 약 6개월 뒤(리프레시 토큰 만료) 데이터가 안 나오면 그때 한 번만 새로 복사해 넣으면 됩니다.
"""

import html
import json
from pathlib import Path

import requests
import pandas as pd

BASE = "https://foapi.teescanner.com/v1"
TOKEN_FILE = Path(__file__).parent / "teescanner_tokens.json"

# 연결 재사용(TCP/TLS 핸드셰이크 반복 제거) — 대량 스캔 속도 향상
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=40, pool_maxsize=40, max_retries=0))

# ↓↓↓ 최초 1회 여기에 붙여넣기 (이후엔 자동 저장 파일이 우선) ↓↓↓
X_TOKEN = ""
X_REFRESH_TOKEN = ""

DEFAULT_REGION = "gyeonggi"

# 한글 지역명 → 티스캐너 지역 코드 (find_regions.py로 검증한 실제 6개 권역)
REGION_MAP = {
    "경기·수도권": "gyeonggi",
    "강원": "gangwon",
    "충청": "chungcheong",
    "전라": "jeolla",
    "경상": "gyeongsang",
    "제주": "jeju",
}

_tokens = {"x_token": "", "x_refresh_token": ""}


def _save():
    try:
        TOKEN_FILE.write_text(json.dumps(_tokens, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load():
    """파일에 저장된 최신 토큰을 우선 사용. 단, 코드에 새 토큰을 붙여넣으면 그게 우선."""
    global _tokens
    file_tokens = None
    if TOKEN_FILE.exists():
        try:
            file_tokens = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            file_tokens = None
    # 사용자가 방금 코드에 붙여넣은 토큰이 파일과 다르면 → 새로 붙여넣은 것으로 간주(우선)
    if X_TOKEN and (not file_tokens or X_TOKEN != file_tokens.get("x_token")):
        _tokens = {"x_token": X_TOKEN.strip(), "x_refresh_token": X_REFRESH_TOKEN.strip()}
        _save()
    elif file_tokens:
        _tokens = file_tokens
    else:
        _tokens = {"x_token": X_TOKEN.strip(), "x_refresh_token": X_REFRESH_TOKEN.strip()}


_load()


def set_tokens(x_token: str, x_refresh: str) -> None:
    """외부(예: Streamlit secrets)에서 토큰을 주입. 클라우드 배포용."""
    global _tokens
    _tokens = {"x_token": (x_token or "").strip(), "x_refresh_token": (x_refresh or "").strip()}


def has_token() -> bool:
    return bool(_tokens.get("x_token") and _tokens.get("x_refresh_token"))


def token_sig() -> str:
    """캐시 무효화용 시그니처(토큰 바뀌면 값이 바뀜)."""
    return (_tokens.get("x_token") or "")[-12:]


_BASE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko-KR,ko;q=0.9",
    "origin": "https://www.teescanner.com",
    "referer": "https://www.teescanner.com/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"),
    "x-client-build": "1",
    "x-client-version": "2.0.0",
}


def _headers(tokens=None) -> dict:
    """tokens=(x_token, x_refresh)면 그 값 사용(사람별 세션). 없으면 전역(공유/파일) 토큰."""
    xt, xr = tokens if tokens else (_tokens["x_token"], _tokens["x_refresh_token"])
    return {**_BASE_HEADERS, "x-token": xt, "x-refresh-token": xr}


def _capture_refresh(resp: requests.Response):
    """응답 헤더에 새 토큰이 오면 자동으로 저장(자동갱신 핵심)."""
    changed = False
    for k, v in resp.headers.items():
        lk = k.lower()
        if not v or len(v) < 20:
            continue
        val = v.replace("Bearer ", "").strip()
        if lk in ("x-token", "x-access-token", "access-token") and val != _tokens["x_token"]:
            _tokens["x_token"] = val
            changed = True
        elif lk in ("x-refresh-token", "refresh-token") and val != _tokens["x_refresh_token"]:
            _tokens["x_refresh_token"] = val
            changed = True
    if changed:
        _save()


def _get(path: str, params: dict, tokens=None) -> requests.Response:
    r = _session.get(f"{BASE}{path}", headers=_headers(tokens), params=params, timeout=10)
    if tokens is None:          # 전역(공유/파일) 토큰일 때만 자동갱신 캡처
        _capture_refresh(r)
    r.raise_for_status()
    return r


def login(user_id: str, password: str) -> dict:
    """티스캐너 아이디(전화번호)+비밀번호로 로그인 → 그 사람의 토큰/이름 반환."""
    r = _session.post(
        f"{BASE}/login/authMemberLoginV2",
        headers=_BASE_HEADERS,
        files={
            "user_ip": (None, "127.0.0.1"),
            "platform": (None, "WEB"),
            "id": (None, str(user_id)),
            "pw": (None, str(password)),
            "service_code": (None, "TEESCANNER"),
        },
        timeout=12,
    )
    r.raise_for_status()
    j = r.json()
    d = j.get("data") or {}
    tok, ref = d.get("token"), d.get("refreshToken")
    if not tok or not ref:
        raise RuntimeError(d.get("message") or j.get("message") or "아이디 또는 비밀번호를 확인하세요.")
    name = (d.get("info") or {}).get("usrName") or d.get("UsrId") or ""
    return {"x_token": tok, "x_refresh_token": ref, "name": name}


def fetch_recommend(date: str, region: str = DEFAULT_REGION, tokens=None) -> list[dict]:
    r = _get("/homemenu/getHomeRecommendConerList",
             {"category_type": 0, "selected_date": date, "gps_state": "Y", "region": region},
             tokens=tokens)
    j = r.json()
    if j.get("result") != 0:
        raise RuntimeError(f"티스캐너 오류: {j.get('message')}")
    return j.get("data", {}).get("recommend_coner_list", [])


def deals_dataframe(date: str, region: str = DEFAULT_REGION, tokens=None) -> pd.DataFrame:
    rows = []
    for it in fetch_recommend(date, region, tokens=tokens):
        caddie = (it.get("caddie_name") or it.get("caddie_type")
                  or it.get("caddie") or it.get("caddie_division") or "")
        rows.append({
            "course": html.unescape(it.get("golfclub_name", "")),
            "area": html.unescape(it.get("area_name", "")).replace(">", " › "),
            "min_cost": it.get("min_cost"),
            "gubun": "대중제" if it.get("membership_type") == "public" else "회원제",
            "review": it.get("review_avg"),
            "benefit": html.unescape(it.get("benefit_sentence", "")).strip(),
            "caddie": html.unescape(str(caddie)).strip(),
            "date": it.get("selected_date", date),
            "seq": it.get("golfclub_seq"),
        })
    df = pd.DataFrame(rows)
    return df.sort_values("min_cost").reset_index(drop=True) if len(df) else df


def search_dataframe(keyword: str, tokens=None) -> pd.DataFrame:
    """골프장 이름으로 검색 → 매칭 골프장 목록(seq 포함). 전국 검색용."""
    r = _get("/search/getNewSearch", {"keywords": keyword}, tokens=tokens)
    j = r.json()
    if j.get("result") != 0:
        raise RuntimeError(f"티스캐너 오류: {j.get('message')}")
    rows = []
    for it in j.get("data", {}).get("golfclub_result", []):
        rows.append({
            "course": html.unescape(it.get("golfclub_name", "")),
            "seq": it.get("golfclub_seq"),
            "area": html.unescape(it.get("area_name", "")).replace(">", " › "),
            "address": html.unescape(it.get("address", "")),
            "score": it.get("total_score"),
        })
    return pd.DataFrame(rows)


def tee_times_dataframe(golfclub_seq: int, date: str, tokens=None) -> pd.DataFrame:
    """특정 골프장(golfclub_seq)의 날짜별 실제 티타임 목록."""
    r = _get("/booking/getTeeTimeListbyGolfclub",
             {"golfclub_seq": int(golfclub_seq), "roundDay": date, "orderType": ""},
             tokens=tokens)
    j = r.json()
    if j.get("result") != 0:
        raise RuntimeError(f"티스캐너 오류: {j.get('message')}")
    rows = []
    for t in j.get("data", {}).get("teeTimeList", []):
        rows.append({
            "time": t.get("teetime_time"),
            "green_fee": t.get("min_cost"),
            "origin": t.get("min_orgin_cost"),
            "caddie": t.get("caddie_name") or "-",
            "course": html.unescape(str(t.get("course_name") or "-")),
            "people": t.get("round_people"),
            "discount": t.get("discount_yn") == "Y",
        })
    df = pd.DataFrame(rows)
    if len(df):
        # 0원/미정 가격은 실제 금액이 아니므로 제외
        gf = pd.to_numeric(df["green_fee"], errors="coerce")
        df = df[gf.notna() & (gf > 0)]
    return df.sort_values("time").reset_index(drop=True) if len(df) else df


if __name__ == "__main__":
    if not has_token():
        print("먼저 X_TOKEN / X_REFRESH_TOKEN 을 넣어주세요.")
    else:
        print(deals_dataframe("2026-07-25").to_string(index=False))
        print("\n현재 토큰 끝 12자:", token_sig())
