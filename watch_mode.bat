@echo off
chcp 65001 >nul
echo ========================================================
echo   TURBO GALLERY - CHẾ ĐỘ TỰ ĐỘNG THEO DÕI (WATCH MODE)
echo   (Tự động tạo thumbnail ngay khi bạn thêm ảnh/thư mục)
echo ========================================================
echo.
python auto_thumb.py --migrate --watch
