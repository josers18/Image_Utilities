# Image Utilities

An Apple-grade, high-performance desktop image utility for macOS. Powered by on-device AI models accelerated by Apple Silicon GPU (Metal Performance Shaders), **Image Utilities** cuts out backgrounds, super-resolves and upscales photos or artwork, resizes, converts, and renames batches of images with complete local privacy.

---

## ✨ Features

### 🧠 On-Device AI Engines
- **State-of-the-Art Background Removal**: Uses BiRefNet via `rembg` for fine-grained subject segmentation, preserving hair and translucent edges.
- **2× & 4× Super-Resolution**: Powered by Real-ESRGAN (`RealESRGAN_x2plus`, `RealESRGAN_x4plus`, and `RealESRGAN_x4plus_anime_6B`) running directly on Apple Silicon MPS (Metal Performance Shaders).
- **Tiled Neural Inference**: Automatic overlap-and-blend tiling (`iter_tiles`) prevents GPU Out-Of-Memory (OOM) errors even on 100+ megapixel photos.
- **Combined Pipeline ("Both")**: Intelligently upscales first to sharpen fine details, then generates a pixel-perfect matte.

### 🎨 Pro Studio & Inspection Tools
- **Split Curtain Slider**: Smooth interactive curtain with a draggable handle and left/right tags.
- **Side-by-Side Comparison**: Inspect original and processed images side-by-side on widescreen monitors.
- **Peek Original**: Press-and-hold the peek button or hold <kbd>Spacebar</kbd> to momentarily reveal the before picture.
- **Transparency Backdrops**: Switch between Dark Checkerboard, Light Checkerboard, Solid White, and Solid Black to verify alpha cutouts.
- **1:1 Actual Size Zoom**: Toggle between "Fit to Screen" and 100% actual pixel resolution.

### ⚡ 1-Click Workflow Presets
- ⚡ **Product**: Cutout + White Canvas + 32px padding + Box 2048×2048 + WebP.
- 🔍 **4× Photo**: 4× Upscale Photo model + PNG.
- 🎨 **4× Art**: 4× Upscale Illustration/Anime model + PNG.
- 🌐 **WebP**: Resize 1920px long edge + 82% WebP.
- ✂️ **Cutout**: Cutout + Transparent + Soft Shadow + PNG.

### 🗂️ Batch Processing & Queue Management
- **Dual Workspace**: Switch between **Studio View** (focused canvas with bottom filmstrip) and **Gallery Grid View** (spacious responsive cards).
- **Multi-Item Selection**: <kbd>Cmd</kbd>/<kbd>Ctrl</kbd>+Click to select multiple items, <kbd>Shift</kbd>+Click for range selection, and bulk-delete selected items.
- **Smart Drag & Drop Zones**: Dropping files onto an active queue offers dual targets: **"Add to Current Queue"** or **"Replace Queue"**.
- **Real-Time Streaming**: Server-Sent Events (SSE) deliver instantaneous, 60fps progress updates without polling lag.

### 🛠️ Matte, Canvas, and Output Customization
- **Edge Refinement**: Adjust between Tighter, Normal, or Feathered matte, with automatic interior hole filling.
- **Canvas & Framing**: Trim bounding box to subject with customizable padding, drop-shadow generation, and custom background colors.
- **Export Formats**: PNG, JPEG, WebP, SVG (vector contour tracing), and Original.
- **Batch Renaming**: Prefix, Suffix, Find & Replace, and sequential zero-padded number counters.

---

## 🖥️ System Requirements

- **Operating System**: macOS 13 (Ventura) or later (macOS Sonoma / Sequoia recommended).
- **Hardware**: Apple Silicon (M1/M2/M3/M4) recommended for Metal GPU acceleration; Intel Macs supported with CPU fallback.
- **Python**: Python 3.12+ (managed automatically via `uv` on first launch).

---

## 🚀 Quick Start

### 1. Launch via Mac App
Double-click `Image Utilities.app` in the repository root. On first run, it will automatically set up the virtual environment (`.venv`), install dependencies, and launch your browser.

### 2. Launch via Terminal
```bash
./run.sh
```

Or run directly with Python:
```bash
.venv/bin/python -m app
```

Command-line flags:
```bash
.venv/bin/python -m app --port 8765 --no-browser
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| <kbd>Cmd</kbd> + <kbd>Enter</kbd> | Run Batch / Cancel active batch |
| <kbd>Space</kbd> (hold) | Peek Original image (in Peek mode) |
| <kbd>Cmd</kbd> / <kbd>Ctrl</kbd> + Click | Select / Deselect multiple queue items |
| <kbd>Shift</kbd> + Click | Select range of queue items |
| <kbd>Esc</kbd> | Deselect all multi-selected items |
| Double-click on preview | Toggle 1:1 Actual Size Zoom |

---

## 🏗️ Architecture Overview

```
Image Utilities Architecture
┌────────────────────────────────────────────────────────┐
│               Image Utilities.app (Swift)              │
│       Native macOS dock wrapper & process manager      │
└───────────────────────────┬────────────────────────────┘
                            │ Spawns & monitors
┌───────────────────────────▼────────────────────────────┐
│                  FastAPI Web Server                    │
│    • REST Endpoints (/api/run, /api/pick, etc.)        │
│    • Server-Sent Events (/api/events) Stream           │
│    • Static Asset Delivery (HTML5 / Vanilla JS / CSS)  │
└─────────────┬────────────────────────────┬─────────────┘
              │ Job Dispatch               │ Real-Time Push
┌─────────────▼─────────────┐ ┌────────────▼─────────────┐
│    Store & Batch Worker   │ │   Vanilla JS / CSS Client │
│ • Thread-safe State Queue │ │ • Studio & Gallery Views  │
│ • Preview Cache Manager   │ │ • Curtain / Side-by-Side  │
│ • Progress Broadcaster    │ │ • Direct Zero-Scroll Panel│
└─────────────┬─────────────┘ └───────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────────┐
│                    Execution Engine                    │
│ • PyTorch Metal (MPS) Real-ESRGAN (x2 / x4 / Anime)   │
│ • BiRefNet Background Removal via rembg                │
│ • Tiled inference (iter_tiles) for high-res images     │
│ • PIL Image finishing (Matting, sRGB, WebP/SVG export) │
└────────────────────────────────────────────────────────┘
```

For full architectural details, concurrency models, and data pipeline specifications, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 📁 Repository Structure

```
.
├── Image Utilities.app/    # Native macOS application wrapper
├── app/
│   ├── __init__.py
│   ├── __main__.py         # CLI entry point and uvicorn launcher
│   ├── config.py           # Paths, supported formats, and system limits
│   ├── engine.py           # PyTorch MPS and BiRefNet AI engine
│   ├── finish.py           # Canvas matting, trimming, color conversion
│   ├── jobs.py             # Store, background worker thread, SSE push
│   ├── naming.py           # Filename generation and sanitization
│   ├── picker.py           # Native macOS AppleScript file/folder dialogs
│   ├── server.py           # FastAPI routes and SSE event streaming
│   ├── settings.py         # Persistent JSON settings manager
│   ├── tiles.py            # Tiled overlapping window algorithm
│   └── static/
│       ├── app.css         # Apple HIG design system (Dark & Light modes)
│       ├── app.js          # Reactive frontend, SSE listener, comparison
│       ├── favicon.svg     # App icon
│       └── index.html      # Responsive workspace and zero-scroll inspector
├── mac/
│   ├── build.sh            # Rebuilds Image Utilities.app with custom icon
│   └── main.swift          # Swift AppKit native launcher
├── tests/
│   ├── test_core.py        # Naming, sanitization, and tiling unit tests
│   └── test_finish.py      # Matting, fitting, and rename rules tests
├── requirements.txt        # Python package dependencies
├── run.sh                  # Bootstrap launcher script
├── ARCHITECTURE.md         # Detailed architectural documentation
└── README.md               # Project documentation
```

---

## 🧪 Running Tests

Execute the unit test suite:
```bash
.venv/bin/python -m unittest discover tests
```

---

## 🔒 Privacy & Security

Image Utilities is strictly **100% on-device**:
- All images are processed locally on your Mac.
- Model weights are cached in `./models/` on your disk.
- Zero analytics, zero telemetries, and zero external network calls during image processing.

---

## 📄 License

MIT License. Feel free to use, modify, and distribute.
