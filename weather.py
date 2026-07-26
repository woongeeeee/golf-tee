"""
weather.py
Open-Meteo 무료 날씨 API (키·회원가입 불필요, 비상업용 무료).
최대 16일 일별 예보 + 시간대별 예보를 위/경도로 가져옵니다.
샘플 함수는 인터넷이 없을 때의 폴백입니다.
"""

import datetime as dt

import requests

OM_URL = "https://api.open-meteo.com/v1/forecast"

# WMO 날씨 코드 → 한글 텍스트
WMO_TEXT = {
    0: "맑음", 1: "대체로 맑음", 2: "구름조금", 3: "흐림",
    45: "안개", 48: "안개", 51: "이슬비", 53: "이슬비", 55: "이슬비",
    56: "이슬비", 57: "이슬비", 61: "비", 63: "비", 65: "비",
    66: "비", 67: "비", 71: "눈", 73: "눈", 75: "눈", 77: "눈",
    80: "소나기", 81: "소나기", 82: "소나기", 85: "눈", 86: "눈",
    95: "뇌우", 96: "뇌우", 99: "뇌우",
}


def _wtext(code) -> str:
    try:
        return WMO_TEXT.get(int(code), "흐림")
    except (TypeError, ValueError):
        return "흐림"


def fetch_openmeteo(lat: float, lon: float, days: int = 16, past_days: int = 3) -> dict | None:
    """Open-Meteo 예보 원본(JSON) 반환. 실패 시 None.
    past_days: 오늘 이전 며칠치도 함께 받아 '선택일 전 3일' 주간예보에 사용."""
    params = {
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,wind_speed_10m_max",
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
        "timezone": "Asia/Seoul", "forecast_days": days, "past_days": past_days,
        "wind_speed_unit": "ms",
    }
    try:
        r = requests.get(OM_URL, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print("[Open-Meteo] 조회 실패:", e)
        return None


def om_daily(raw: dict, days: int = 7) -> list[dict]:
    """원본 → 일별 예보 [{date,min,max,day_text,rain_prob,wind}]."""
    if not raw or "daily" not in raw:
        return []
    d = raw["daily"]
    out = []
    for i, date in enumerate(d["time"][:days]):
        pop = d["precipitation_probability_max"][i]
        out.append({
            "date": date,
            "min": round(d["temperature_2m_min"][i]) if d["temperature_2m_min"][i] is not None else None,
            "max": round(d["temperature_2m_max"][i]) if d["temperature_2m_max"][i] is not None else None,
            "day_text": _wtext(d["weather_code"][i]),
            "rain_prob": int(pop) if pop is not None else 0,
            "wind": round(d["wind_speed_10m_max"][i], 1) if d["wind_speed_10m_max"][i] is not None else None,
        })
    return out


def om_hourly(raw: dict, date_iso: str) -> list[dict]:
    """원본 → 특정 날짜의 시간대별 [{hour,temp,rain_prob,wind,sky}]."""
    if not raw or "hourly" not in raw:
        return []
    h = raw["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        if not t.startswith(date_iso):
            continue
        pop = h["precipitation_probability"][i]
        out.append({
            "hour": int(t[11:13]),
            "temp": round(h["temperature_2m"][i], 1) if h["temperature_2m"][i] is not None else 0,
            "rain_prob": int(pop) if pop is not None else 0,
            "wind": round(h["wind_speed_10m"][i], 1) if h["wind_speed_10m"][i] is not None else 0,
            "sky": _wtext(h["weather_code"][i]),
        })
    return out


# ============================ 샘플(인터넷 없을 때 폴백) ============================
def sample_forecast(days: int = 7) -> list[dict]:
    import random
    rng = random.Random(7)
    today = dt.date.today()
    texts = ["맑음", "구름조금", "흐림", "비", "소나기"]
    out = []
    for i in range(days):
        date = today + dt.timedelta(days=i)
        mx = rng.randint(18, 30)
        out.append({"date": date.isoformat(), "min": mx - rng.randint(6, 11), "max": mx,
                    "day_text": rng.choice(texts), "rain_prob": rng.randint(0, 80),
                    "wind": round(rng.uniform(1.0, 6.5), 1)})
    return out


def sample_day(date_iso: str) -> dict:
    import random
    rng = random.Random(int(date_iso.replace("-", "")) + 1)
    mx = rng.randint(18, 31)
    return {"date": date_iso, "min": mx - rng.randint(6, 11), "max": mx,
            "day_text": rng.choice(["맑음", "구름조금", "흐림", "비"]),
            "rain_prob": rng.randint(0, 80), "wind": round(rng.uniform(1.0, 6.5), 1)}


def sample_hourly(date_iso: str, tmin: int, tmax: int) -> list[dict]:
    import math
    import random
    rng = random.Random(int(date_iso.replace("-", "")))
    amp = max(1, tmax - tmin)
    texts = ["맑음", "구름조금", "흐림", "비"]
    out = []
    for h in range(24):
        frac = 0.5 - 0.5 * math.cos((h - 4) / 24 * 2 * math.pi)
        out.append({"hour": h, "temp": round(tmin + amp * frac + rng.uniform(-0.6, 0.6), 1),
                    "rain_prob": max(0, min(100, int(rng.gauss(28, 24)))),
                    "wind": round(max(0.3, rng.gauss(2.8, 1.4)), 1),
                    "sky": rng.choice(texts)})
    return out


if __name__ == "__main__":
    print("샘플:", sample_forecast(2))
