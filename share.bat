@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    GOLF TEE - 친구들과 링크로 공유하기
echo ============================================
echo.
if not exist cloudflared.exe (
  echo [!] cloudflared.exe 가 이 폴더에 없습니다.
  echo.
  echo     아래 주소에서 받아 이 폴더에 넣고, 파일 이름을 cloudflared.exe 로 바꾸세요:
  echo     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  echo.
  pause
  exit /b
)
echo [1/2] 골프티 앱을 시작합니다... (새 창이 하나 열려요)
start "GOLF TEE APP" cmd /k "streamlit run app.py"
echo      앱이 켜질 때까지 8초 기다립니다...
timeout /t 8 /nobreak >nul
echo.
echo [2/2] 공유 링크를 만듭니다.
echo      잠시 뒤 아래에 나오는 https://....trycloudflare.com 주소를 친구에게 보내세요.
echo      (이 창과 앱 창을 둘 다 켜둔 동안에만 친구가 접속할 수 있어요.)
echo.
cloudflared.exe tunnel --url http://localhost:8501
pause
