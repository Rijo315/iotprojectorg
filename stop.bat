
@echo off
setlocal
title Stop SENTROVA Services

echo ==========================================
echo       STOP SENTROVA SERVICES
echo ==========================================
echo.
echo This will stop services listening on:
echo Ports 5000, 5001, 5002 and 5173.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ports = @(5000,5001,5002,5173); " ^
 "foreach ($port in $ports) { " ^
 "  $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; " ^
 "  foreach ($connection in $connections) { " ^
 "    $procId = $connection.OwningProcess; " ^
 "    if ($procId -gt 0) { " ^
 "      Write-Host ('Stopping listener on port ' + $port + ', PID ' + $procId); " ^
 "      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue; " ^
 "    } " ^
 "  } " ^
 "}"

echo.
echo Stop command completed.
echo Check the service windows for any errors.
pause
endlocal
