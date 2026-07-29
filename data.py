
import datetime as dt
import hashlib
from pathlib import Path

import pandas as pd

STANDARD_COLUMNS = [
    "course", "region", "date", "tee_time",
    "green_fee", "caddie", "caddie_fee", "cart_fee",
    "players", "lat", "lon", "source", "booking_url",
    "holes", "gubun", "address", "city",
]

def city_from_address(addr: str) -> str:
    parts = str(addr).split()
    for p in parts:
        if p.endswith(("시", "군", "구")):
            return p
    return parts[0] if parts else ""

SOURCE_URLS = {
    "티스캐너": "https://www.teescanner.com",
    "XGOLF": "https://www.xgolf.com",
    "카카오골프예약": "https://golf.kakao.com",
    "스마트스코어": "https://www.smartscore.co.kr",
}
_SOURCES = list(SOURCE_URLS.keys())

def booking_link(course: str, source: str) -> str:
    return SOURCE_URLS[source]

REGION_CENTERS = {
    "서울": (37.56, 126.99), "부산": (35.18, 129.07), "대구": (35.87, 128.60),
    "인천": (37.46, 126.71), "광주": (35.16, 126.85), "대전": (36.35, 127.38),
    "울산": (35.54, 129.31), "세종": (36.48, 127.29), "경기": (37.41, 127.20),
    "강원": (37.72, 128.20), "충북": (36.80, 127.70), "충남": (36.60, 126.80),
    "전북": (35.72, 127.00), "전남": (34.90, 126.80), "경북": (36.30, 128.80),
    "경남": (35.30, 128.30), "제주": (33.40, 126.55),
}

CSV_PATH = Path(__file__).parent / "golf_courses.csv"

def _approx_coord(region: str, name: str) -> tuple[float, float]:
    clat, clon = REGION_CENTERS.get(region, (36.5, 127.8))
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    dlat = ((h % 1000) / 1000 - 0.5) * 0.45
    dlon = (((h // 1000) % 1000) / 1000 - 0.5) * 0.45
    return round(clat + dlat, 4), round(clon + dlon, 4)

def _load_courses() -> list[dict]:
    try:
        cdf = pd.read_csv(CSV_PATH, encoding="utf-8")
    except (OSError, ValueError):
        return [{"name": "스카이72 CC", "region": "인천", "holes": 18, "gubun": "대중제",
                 "address": "인천", "lat": 37.482, "lon": 126.551}]
    courses = []
    for _, r in cdf.iterrows():
        region = str(r["지역"]).strip()
        name = str(r["이름"]).strip()
        lat, lon = _approx_coord(region, name)
        addr = str(r["소재지"]).strip()
        courses.append({
            "name": name, "region": region,
            "holes": int(r["홀"]) if pd.notna(r["홀"]) else 18,
            "gubun": str(r["구분"]).strip(), "address": addr, "city": city_from_address(addr),
            "lat": lat, "lon": lon,
        })
    return courses

_COURSES = _load_courses()
_TIMES = ["06:12", "06:40", "07:04", "07:28", "10:16", "11:00", "12:20", "13:40", "15:10", "16:00"]

def _rows_for_date(date: dt.date) -> list[dict]:
    import random
    rng = random.Random(date.toordinal())
    is_weekend = date.weekday() >= 5
    rows = []
    for c in _COURSES:
        for tee in rng.sample(_TIMES, k=rng.randint(1, 3)):
            base = rng.choice([90000, 120000, 150000, 180000, 220000, 250000])
            price = base + (40000 if is_weekend else 0)
            if int(tee[:2]) <= 7:
                price += 15000
            
            # 특가 로직 제거 (원래 약 10% 확률로 7만원 이하)
            # if rng.random() < 0.10:  
            #     price = rng.choice([49000, 55000, 59000, 65000, 69000])
                
            caddie = rng.choice(["캐디", "노캐디", "캐디선택가능"])
            caddie_fee = 0 if caddie == "노캐디" else rng.choice([120000, 140000, 150000])
            source = rng.choice(_SOURCES)
            rows.append({
                "course": c["name"], "region": c["region"], "date": date.isoformat(), "tee_time": tee,
                "green_fee": price, "caddie": caddie, "caddie_fee": caddie_fee,
                "cart_fee": rng.choice([80000, 90000, 100000]), "players": 4,
                "lat": c["lat"], "lon": c["lon"], "source": source,
                "booking_url": booking_link(c["name"], source),
                "holes": c["holes"], "gubun": c["gubun"], "address": c["address"], "city": c["city"],
            })
    return rows

def make_sample_for_dates(dates) -> pd.DataFrame:
    rows = []
    for d in dates:
        rows.extend(_rows_for_date(d))
    return pd.DataFrame(rows, columns=STANDARD_COLUMNS)

def make_sample_dataframe(days: int = 14) -> pd.DataFrame:
    today = dt.date.today()
    return make_sample_for_dates([today + dt.timedelta(days=i) for i in range(days)])

def add_total_cost(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if len(df) == 0:
        df["est_total_per_person"] = []
        return df
    per_caddie = (df["caddie_fee"] / df["players"]).round(0)
    per_cart = (df["cart_fee"] / df["players"]).round(0)
    df["est_total_per_person"] = (df["green_fee"] + per_caddie + per_cart).astype(int)
    return df

if __name__ == "__main__":
    print("총 골프장 수:", len(_COURSES))
    df = make_sample_for_dates([dt.date.today()])
    print("지역 수:", df["region"].nunique(), "| 오늘 티타임 행수:", len(df))
    print("홀수 분포:", df.drop_duplicates("course")["holes"].value_counts().to_dict())
    print("구분 분포:", df.drop_duplicates("course")["gubun"].value_counts().to_dict())
