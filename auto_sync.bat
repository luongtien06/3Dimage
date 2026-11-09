@echo off
chcp 65001 >nul
echo ========================================================
echo   TURBO GALLERY - TỰ ĐỘNG ĐỒNG BỘ VÀ TẠO THUMBNAIL
echo ========================================================
echo.
python auto_thumb.py --migrate
echo.
echo ========================================================
echo   Hoàn tất! Nhấn phím bất kỳ để thoát...
echo ========================================================
pause >nul
