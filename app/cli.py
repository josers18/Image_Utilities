"""Headless batch command-line interface for Image Utilities.

Usage:
    python -m app.cli photos/*.jpg --task cutout --format webp
    python -m app.cli image.png --task upscale --scale 4 --sharpen 25
    python -m app.cli product.jpg --task both --aspect-ratio 1:1 -o out/
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from app.config import IMAGE_SUFFIXES, PREVIEWS
from app.engine import Cancelled, Engine, JobSpec, Reporter
from app.finish import Options, file_suffix, planned_filename
from app.naming import format_bytes, list_images


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Process images with Image Utilities directly from the terminal.",
    )
    parser.add_argument("paths", nargs="+", help="Input image files or directories.")
    parser.add_argument(
        "--task",
        choices=["cutout", "upscale", "both", "resize", "convert", "rename"],
        default="cutout",
        help="Processing task (default: cutout).",
    )
    parser.add_argument("--scale", type=int, choices=[2, 4], default=4, help="AI upscale scale factor (2 or 4).")
    parser.add_argument("--look", choices=["photo", "illustration"], default="photo", help="AI upscaler model look.")
    parser.add_argument(
        "--fit",
        choices=["none", "long", "width", "height", "box", "percent"],
        default="none",
        help="Canvas fit mode (default: none).",
    )
    parser.add_argument("--fit-a", type=int, default=2048, help="Size dimension or percentage for fit mode.")
    parser.add_argument("--fit-b", type=int, default=2048, help="Secondary height dimension for box fit.")
    parser.add_argument("--aspect-ratio", choices=["auto", "1:1", "4:5", "9:16", "16:9", "4:3", "3:2"], default="auto")
    parser.add_argument("--sharpen", type=int, default=0, help="Sharpening strength (0 to 100).")
    parser.add_argument("--brightness", type=int, default=100, help="Brightness percentage (50 to 150).")
    parser.add_argument("--contrast", type=int, default=100, help="Contrast percentage (50 to 150).")
    parser.add_argument("--saturation", type=int, default=100, help="Color saturation percentage (0 to 200).")
    parser.add_argument("--auto-contrast", action="store_true", help="Automatically equalize tone contrast.")
    parser.add_argument("--watermark", type=str, default="", help="Watermark text overlay.")
    parser.add_argument(
        "--watermark-pos",
        choices=["bottom-right", "bottom-left", "top-right", "top-left", "center"],
        default="bottom-right",
    )
    parser.add_argument(
        "--format",
        choices=["png", "jpeg", "webp", "svg", "same"],
        default="png",
        help="Output format (default: png).",
    )
    parser.add_argument("--quality", type=int, default=90, help="JPEG / WebP compression quality (1 to 100).")
    parser.add_argument("-o", "--output-dir", type=str, default="", help="Destination directory (default: beside input).")
    parser.add_argument("-r", "--subfolders", action="store_true", help="Recursively include subdirectories.")

    args = parser.parse_args(argv)

    # Collect files
    sources: list[Path] = []
    for raw in args.paths:
        path = Path(raw).expanduser().resolve()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            sources.append(path)
        elif path.is_dir():
            files, _ = list_images(path, subfolders=args.subfolders, limit=5000)
            sources.extend(files)

    if not sources:
        print("No supported images found at the given paths.", file=sys.stderr)
        return 1

    options = Options(
        task=args.task,
        scale=args.scale,
        look=args.look,
        save="folder" if args.output_dir else "beside",
        fit=args.fit,
        fit_a=args.fit_a,
        fit_b=args.fit_b,
        aspect_ratio=args.aspect_ratio,
        sharpen=args.sharpen,
        brightness=args.brightness,
        contrast=args.contrast,
        saturation=args.saturation,
        auto_contrast=args.auto_contrast,
        watermark_text=args.watermark,
        watermark_pos=args.watermark_pos,
        format=args.format,
        quality=args.quality,
    )

    print(f"Image Utilities CLI — processing {len(sources)} image{'s' if len(sources) != 1 else ''} ({args.task})...")
    engine = Engine()
    cancel = threading.Event()
    success_count = 0
    t0 = time.perf_counter()

    for idx, source in enumerate(sources, 1):
        dest_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else source.parent
        dest_name = planned_filename(source.stem, options, idx - 1, source)
        
        preview_dir = PREVIEWS / "cli"
        preview_dir.mkdir(parents=True, exist_ok=True)
        spec = JobSpec(
            source=source,
            dest_dir=dest_dir,
            dest_name=dest_name,
            task=options.task,
            scale=options.scale,
            look=options.look,
            preview_before=preview_dir / f"{idx}-before.jpg",
            preview_after=preview_dir / f"{idx}-after.png",
            thumb=preview_dir / f"{idx}-thumb.jpg",
            options=options,
        )

        def report(phase: str, frac: float) -> None:
            pct = int(frac * 100)
            sys.stdout.write(f"\r[{idx}/{len(sources)}] {source.name} • {phase} ({pct}%)...")
            sys.stdout.flush()

        item_start = time.perf_counter()
        try:
            res = engine.process_file(spec, Reporter(report), cancel)
            elapsed = time.perf_counter() - item_start
            nbytes = res.output.stat().st_size if res.output.exists() else 0
            size_str = format_bytes(nbytes)
            sys.stdout.write(
                f"\r[{idx}/{len(sources)}] ✓ {source.name} → {res.output.name} ({res.width}×{res.height}, {size_str}, {elapsed:.1f}s)\n"
            )
            sys.stdout.flush()
            success_count += 1
        except Exception as exc:
            sys.stdout.write(f"\r[{idx}/{len(sources)}] ✗ {source.name} failed: {exc}\n")
            sys.stdout.flush()

    total_time = time.perf_counter() - t0
    print(f"\nDone! Processed {success_count}/{len(sources)} images in {total_time:.1f}s.")
    return 0 if success_count == len(sources) else 1


if __name__ == "__main__":
    sys.exit(main())
