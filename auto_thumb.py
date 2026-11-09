#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build deployable Turbo Gallery assets from the original image archive.

Layout:
  originals/iN/1.jpg        source archive; do not deploy
  public/assets/iN/thumb.webp      collection cover
  public/assets/iN/thumbs/N.webp   grid image
  public/assets/iN/medium/N.webp   lightbox image
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
ORIGINALS_DIR = ROOT / "originals"
PUBLIC_DIR = ROOT / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FOLDER_PATTERN = re.compile(r"i\d+$")
NUMBERED_IMAGE_PATTERN = re.compile(r"^\d+\.jpg$", re.IGNORECASE)

COVER_SIZE = (600, 600)
THUMB_SIZE = (800, 800)
MEDIUM_SIZE = (2560, 2560)


def natural_sort_key(name: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def collection_folders() -> list[Path]:
    if not ORIGINALS_DIR.exists():
        return []
    return sorted(
        (path for path in ORIGINALS_DIR.iterdir() if path.is_dir() and FOLDER_PATTERN.fullmatch(path.name)),
        key=lambda path: int(path.name[1:]),
    )


def migrate_legacy_layout() -> int:
    """Move root-level iN folders into originals/ and preserve generated assets."""
    legacy_folders = sorted(
        (path for path in ROOT.iterdir() if path.is_dir() and FOLDER_PATTERN.fullmatch(path.name)),
        key=lambda path: int(path.name[1:]),
    )
    if not legacy_folders:
        return 0

    ORIGINALS_DIR.mkdir(exist_ok=True)
    for source in legacy_folders:
        destination = ORIGINALS_DIR / source.name
        if destination.exists():
            raise RuntimeError(
                f"Không thể di chuyển {source.name}: {destination} đã tồn tại. "
                "Hãy kiểm tra hai thư mục trước khi chạy lại."
            )
        shutil.move(str(source), str(destination))

        asset_folder = ASSETS_DIR / source.name
        asset_folder.mkdir(parents=True, exist_ok=True)
        legacy_thumbs = destination / "thumbs"
        legacy_cover = destination / "thumb.webp"
        if legacy_thumbs.exists():
            shutil.move(str(legacy_thumbs), str(asset_folder / "legacy-thumbs"))
        if legacy_cover.exists():
            shutil.move(str(legacy_cover), str(asset_folder / "legacy-cover.webp"))

    print(f"[+] Đã chuyển {len(legacy_folders)} bộ ảnh vào {ORIGINALS_DIR.name}/.")
    return len(legacy_folders)


def normalize_source_images(folder: Path) -> list[Path]:
    """Rename direct image files to 1.jpg, 2.jpg … using a collision-safe two-step move."""
    images = sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: natural_sort_key(path.name),
    )
    if not images:
        return []

    if all(NUMBERED_IMAGE_PATTERN.fullmatch(path.name) for path in images):
        return sorted(images, key=lambda path: int(path.stem))

    temporary: list[Path] = []
    stamp = time.time_ns()
    for index, source in enumerate(images, start=1):
        target = folder / f".turbo-gallery-{stamp}-{index}.tmp"
        source.rename(target)
        temporary.append(target)

    normalized: list[Path] = []
    for index, source in enumerate(temporary, start=1):
        target = folder / f"{index}.jpg"
        source.rename(target)
        normalized.append(target)
    return normalized


def image_is_current(source: Path, destination: Path) -> bool:
    try:
        return destination.exists() and destination.stat().st_size > 0 and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def build_image(source: Path, destination: Path, size: tuple[int, int], quality: int) -> bool:
    if image_is_current(source, destination):
        return False
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail(size, Image.Resampling.LANCZOS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, "WEBP", quality=quality, method=6)
        return True
    except Exception as error:
        print(f"[-] Không thể xử lý {source}: {error}", file=sys.stderr)
        return False


def remove_stale_assets(folder: str, count: int) -> None:
    """Remove only generated formats that no longer correspond to an original."""
    asset_folder = ASSETS_DIR / folder
    expected = {
        asset_folder / "thumb.webp",
        *(asset_folder / "thumbs" / f"{index}.webp" for index in range(1, count + 1)),
        *(asset_folder / "medium" / f"{index}.webp" for index in range(1, count + 1)),
    }
    for directory in (asset_folder / "thumbs", asset_folder / "medium"):
        if not directory.exists():
            continue
        for candidate in directory.iterdir():
            if candidate.is_file() and candidate not in expected:
                candidate.unlink()

    # Files from the old project format are generated derivatives, not originals.
    for legacy in (asset_folder / "legacy-thumbs", asset_folder / "legacy-cover.webp"):
        if legacy.is_dir():
            shutil.rmtree(legacy)
        elif legacy.exists():
            legacy.unlink()


def write_gallery_config(galleries: list[dict[str, object]]) -> None:
    """Write the only browser-side collection manifest; works under file:// too."""
    payload = "window.TURBO_GALLERIES = Object.freeze(" + json.dumps(
        galleries, ensure_ascii=False, separators=(",", ":")
    ) + ");\n"
    PUBLIC_DIR.mkdir(exist_ok=True)
    target = PUBLIC_DIR / "galleries.js"
    temporary = target.with_suffix(".js.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)


def sync_all(*, migrate_legacy: bool = False) -> int:
    started = time.perf_counter()
    if migrate_legacy:
        migrate_legacy_layout()
    folders = collection_folders()
    if not folders:
        print("[!] Không có ảnh nguồn. Chạy: python auto_thumb.py --migrate", file=sys.stderr)
        return 1

    tasks: list[tuple[Path, Path, tuple[int, int], int]] = []
    galleries: list[dict[str, object]] = []
    cleanup: list[tuple[str, int]] = []

    for folder in folders:
        images = normalize_source_images(folder)
        if not images:
            continue
        latest_source_mtime = max(image.stat().st_mtime_ns for image in images)
        galleries.append(
            {
                "folder": folder.name,
                "count": len(images),
                "thumb": f"assets/{folder.name}/thumb.webp",
                "version": str(latest_source_mtime),
            }
        )
        asset_folder = ASSETS_DIR / folder.name
        tasks.append((images[0], asset_folder / "thumb.webp", COVER_SIZE, 78))
        for index, source in enumerate(images, start=1):
            tasks.append((source, asset_folder / "thumbs" / f"{index}.webp", THUMB_SIZE, 78))
            tasks.append((source, asset_folder / "medium" / f"{index}.webp", MEDIUM_SIZE, 84))
        cleanup.append((folder.name, len(images)))

    created = 0
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as pool:
        for result in pool.map(lambda job: build_image(*job), tasks):
            created += bool(result)

    for folder, count in cleanup:
        remove_stale_assets(folder, count)
    write_gallery_config(galleries)

    elapsed = time.perf_counter() - started
    print(f"[+] Hoàn tất: {created} ảnh dẫn xuất được tạo/cập nhật trong {elapsed:.1f}s.")
    print(f"[+] Manifest: galleries.js ({len(galleries)} bộ sưu tập).")
    return 0


def watch_mode(*, migrate_legacy: bool = False) -> int:
    """Watch originals/ with filesystem events, debounced to avoid partial uploads."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print("[!] Watch mode cần watchdog. Chạy: python -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    if sync_all(migrate_legacy=migrate_legacy):
        return 1

    class GalleryEventHandler(FileSystemEventHandler):
        def __init__(self) -> None:
            self.timer: threading.Timer | None = None
            self.lock = threading.Lock()

        def on_any_event(self, event) -> None:
            if getattr(event, "is_directory", False) or Path(event.src_path).suffix.lower() not in IMAGE_EXTENSIONS:
                return
            with self.lock:
                if self.timer:
                    self.timer.cancel()
                self.timer = threading.Timer(1.0, self.rebuild)
                self.timer.daemon = True
                self.timer.start()

        def rebuild(self) -> None:
            print("[*] Phát hiện thay đổi ảnh; đang tạo lại assets…")
            sync_all()

    observer = Observer()
    observer.schedule(GalleryEventHandler(), str(ORIGINALS_DIR), recursive=True)
    observer.start()
    print("[*] Đang theo dõi originals/. Nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Turbo Gallery web assets.")
    parser.add_argument("--migrate", action="store_true", help="Di chuyển các thư mục iN cũ vào originals/.")
    parser.add_argument("--watch", action="store_true", help="Theo dõi originals/ bằng watchdog.")
    args = parser.parse_args()
    return watch_mode(migrate_legacy=args.migrate) if args.watch else sync_all(migrate_legacy=args.migrate)


if __name__ == "__main__":
    raise SystemExit(main())
