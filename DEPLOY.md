# 🌐 친구들과 함께 쓰기 — 웹 배포 가이드 (Streamlit 무료 클라우드)

친구들이 **링크만 열면** 쓸 수 있게 만드는 방법이에요. 설치 없이 폰·PC 어디서나 됩니다.
한 번만 설정해두면 끝이고, 전부 무료예요.

준비물: GitHub 계정, Streamlit 클라우드 계정(둘 다 무료), 그리고 티스캐너 토큰(사쿠님 것 1개).

---

## 1단계 — GitHub에 코드 올리기

1. https://github.com 가입 → 로그인.
2. 오른쪽 위 **+** → **New repository**.
   - Repository name: `golf-tee` (아무 이름)
   - **Private** 선택(친구만 쓸 거면 비공개 권장) → **Create repository**.
3. 만든 저장소 화면에서 **Add file → Upload files**.
4. 이 폴더(`golf_tee`) 안의 **파일과 폴더를 전부 끌어다 올려요.**
   - 꼭 포함: `app.py`, `teescanner.py`, `catalog.py`, `scan.py`, `weather.py`,
     `data.py`, `golf_courses.csv`, `golf_clubs_ts.json`(전국 목록), `requirements.txt`,
     `components/`(폴더째), `.streamlit/`(폴더째).
   - **절대 올리면 안 되는 것**: `teescanner_tokens.json`(토큰!), `scan_*.json`.
     (`.gitignore`가 자동으로 걸러주지만, 수동 업로드 땐 직접 빼주세요.)
5. 아래 **Commit changes** 눌러 업로드 완료.

> 💡 `golf_clubs_ts.json`(전국 골프장 목록)을 꼭 같이 올리세요. 그래야 친구들이 바로
> 목록을 보고 스캔할 수 있어요. 없으면 앱에서 "다시 수집"으로 새로 만들어야 합니다.

## 2단계 — Streamlit 클라우드에 연결

1. https://share.streamlit.io 접속 → **GitHub 계정으로 로그인**.
2. **Create app → Deploy a public app from GitHub** (Private repo도 가능).
3. 항목 선택:
   - Repository: 방금 만든 `golf-tee`
   - Branch: `main`
   - Main file path: `app.py`
4. **Deploy** 클릭 → 1~2분 뒤 앱이 뜨고 **주소(URL)** 가 생겨요.
5. 그 주소를 친구들에게 보내면 끝!

## 친구들은 어떻게 쓰나요 — 각자 로그인

친구들은 앱을 열고 왼쪽 **👤 티스캐너 로그인**에서 **본인 티스캐너 아이디(전화번호)+비밀번호**로
로그인하면 돼요. 각자 자기 계정으로 접속하는 거라, 사쿠님 토큰을 공유할 필요가 없어요.
(비밀번호는 티스캐너로 로그인할 때만 쓰이고 앱에 저장하지 않아요.)

## (선택) 로그인 없이 바로 쓰게 하고 싶다면 — 공유 토큰

친구들이 로그인 절차 없이 바로 쓰게 하려면, 2단계에서 **Advanced settings → Secrets** 에
사쿠님 토큰을 넣어두면 돼요(이러면 로그인 안 해도 사쿠님 토큰으로 데이터가 나와요):
```toml
TEESCANNER_X_TOKEN = "여기에 x-token 값"
TEESCANNER_X_REFRESH_TOKEN = "여기에 x-refresh-token 값"
```
이 경우 링크를 아는 사람이 사쿠님 세션으로 조회하게 되니 **가까운 친구끼리만** 공유하세요.
(안 넣으면 각자 로그인해서 쓰는 방식이 됩니다.)

## 참고 / 주의

- 친구들이 자기 티스캐너 아이디·비번을 이 앱에 입력하게 돼요. 앱은 그걸 티스캐너에 넘겨
  로그인만 하고 비번은 저장하지 않지만, "이 앱을 믿고 로그인한다"는 점은 알려주세요.
  Private repo + 링크 비공개를 권장해요.
- 무료 플랜은 사용이 없으면 앱이 잠들었다가(sleep) 다음 접속 때 다시 깨어나요(수십 초).
- "전국 최저가 스캔"은 서버에서 도는데, 한 명이 스캔해두면 같은 날짜는 다른 친구도 바로 봐요.
- 이건 티스캐너 내부 데이터를 쓰는 개인용 도구예요. 공개 서비스로 크게 열지는 마세요.
