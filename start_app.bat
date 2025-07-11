@echo off
echo Menyalakan semua layanan (Redis, API, Worker)...
docker-compose up -d
echo.
echo Semua layanan sudah aktif di latar belakang.
pause