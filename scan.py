"""
scan.py — 전국 골프장 목록(catalog)을 날짜 기준으로 훑어
각 골프장의 '실제 최저가 티타임'(가격·캐디·시간)을 모은다.

티스캐너엔 '전체 최저가 한 번에' 주는 엔드포인트가 없어서,
골프장별 티타임을 병렬로 불러 최저가를 직접 계산한다.
결과는 scan_<날짜>.json 으로 캐시한다.
"""

import concurrent.futures as cf
import json
from pathlib import Path

import pandas as pd

import teescanner as ts
import catalog as CAT

HERE = Path(__file__).parent


def scan_file(date: str, min_hour=None) -> Path:
    suffix = f"_n{min_hour}" if min_hour is not None else ""
    return HERE / f"scan_{date}{suffix}.json"


def _hour(t) -> int:
    """티타임 문자열(예: '06:18', '16:30') → 시(hour) 정수. 파싱 실패 시 -1."""
    s = str(t).strip()
    s = s.split(":")[0] if ":" in s else s[:2]
    return int(s) if s.isdigit() else -1


def _one(club: dict, date: str, tokens=None, min_hour=None) -> dict | None:
    seq = club.get("seq")
    if seq is None:
        return None
    try:
        df = ts.tee_times_dataframe(int(seq), date, tokens=tokens)
    except Exception:
        return None
    df = df[df["green_fee"].notna()]
    # 당일 야간 등: 특정 시각 이후 티타임만 대상으로 최저가 계산
    if min_hour is not None and len(df):
        df = df[df["time"].map(_hour) >= int(min_hour)]
    if not len(df):
        return None
    row = df.loc[df["green_fee"].idxmin()]
    score = club.get("score")
    try:
        score = None if score is None or pd.isna(score) else float(score)
    except (TypeError, ValueError):
        score = None
    try:
        people = None if pd.isna(row.get("people")) else int(row.get("people"))
    except (TypeError, ValueError):
        people = None
    return {
        "seq": int(seq),
        "course": str(club.get("course", "")),
        "area": str(club.get("area", "")),
        "region": CAT.top_region(club.get("area", "")),
        "address": str(club.get("address", "")),
        "score": score,
        "min_cost": int(row["green_fee"]),
        "caddie": str(row.get("caddie") or ""),
        "course_name": str(row.get("course") or ""),
        "time": str(row.get("time") or ""),
        "people": people,
    }


def scan_prices(clubs: list[dict], date: str, progress=None, max_workers: int = 32,
                tokens=None, min_hour=None) -> list[dict]:
    """모든 골프장의 해당 날짜 최저가를 병렬로 수집. 티타임 없는 곳은 제외.
    min_hour가 주어지면 그 시각 이후 티타임만(예: 당일 야간 16시 이후) 대상으로 계산."""
    results = []
    total = len(clubs)
    done = 0
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_one, c, date, tokens, min_hour) for c in clubs]
        for fu in cf.as_completed(futs):
            try:
                r = fu.result()
            except Exception:
                r = None
            if r:
                results.append(r)
            done += 1
            if progress:
                progress(done, total, len(results))
    results.sort(key=lambda x: x["min_cost"])
    return results


def save(date: str, rows: list[dict], min_hour=None) -> None:
    try:
        scan_file(date, min_hour).write_text(
            json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def load(date: str, min_hour=None) -> list[dict]:
    f = scan_file(date, min_hour)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    return []
