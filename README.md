# Turbo Gallery

## Cấu trúc

- `public/`: thư mục duy nhất cần triển khai lên hosting.
- `originals/`: ảnh gốc để lưu trữ và tạo lại asset; không cần đưa lên hosting.
- `auto_thumb.py`: tạo cover, thumbnail và ảnh lightbox WebP.

## Dùng

```powershell
python -m pip install -r requirements.txt
python auto_thumb.py --migrate
```

Chạy `auto_sync.bat` để đồng bộ một lần. Chạy `watch_mode.bat` để theo dõi thay đổi trong `originals/` bằng filesystem events.

Triển khai nội dung của thư mục `public/`, bắt đầu tại `public/index.html`.
