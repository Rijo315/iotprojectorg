@echo off
setlocal
title SENTROVA Launcher

set "ROOT=D:\NEXORA\PROJECT\Industrial-Worker-Monitor"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"

echo.
echo ==========================================
echo       SENTROVA - START ALL SERVICES
echo ==========================================
echo.

if not exist "%BACKEND%\main.py" (
  echo ERROR: Cannot find "%BACKEND%\main.py"
  echo Check the ROOT path in this BAT file.
  pause
  exit /b 1
)
if not exist "%BACKEND%\camera_fall_server.py" (
  echo ERROR: Cannot find "%BACKEND%\camera_fall_server.py"
  pause
  exit /b 1
)
if not exist "%BACKEND%\demo_video_server.py" (
  echo ERROR: Cannot find "%BACKEND%\demo_video_server.py"
  echo Copy the demo-video add-on into the backend folder first.
  pause
  exit /b 1
)
if not exist "%FRONTEND%\package.json" (
  echo ERROR: Cannot find "%FRONTEND%\package.json"
  pause
  exit /b 1
)

echo Starting main Flask backend on port 5000...
start "SENTROVA - Main Backend (5000)" cmd /k "cd /d "%BACKEND%" && python main.py"

timeout /t 2 /nobreak >nul
echo Starting live camera server on port 5001...
start "SENTROVA - Live Camera (5001)" cmd /k "cd /d "%BACKEND%" && python camera_fall_server.py"

timeout /t 2 /nobreak >nul
echo Starting demo video server on port 5002...
start "SENTROVA - Demo Video (5002)" cmd /k "cd /d "%BACKEND%" && python demo_video_server.py"

timeout /t 2 /nobreak >nul
echo Starting React dashboard...
start "SENTROVA - React Dashboard" cmd /k "cd /d "%FRONTEND%" && npm.cmd run dev"

echo.
echo Launch commands have been sent.
echo Wait for each terminal to finish starting, then open:
echo   Dashboard: http://localhost:5173
echo   Backend:   http://127.0.0.1:5000/api/health
echo   Camera:    http://127.0.0.1:5001/health
echo   Demo API:  http://127.0.0.1:5002/health
echo.
echo If a service terminal shows an error, leave it open to read the message.
echo Close the individual service terminals to stop them.
echo.
pause
endlocal
