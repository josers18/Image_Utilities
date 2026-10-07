const ui = {
  task: "both",
  scale: 4,
  look: "photo",
  save: "beside",
  fit: "none",
  fitA: 2048,
  fitB: 2048,
  noUpscale: false,
  edge: "normal",
  fillHoles: true,
  trim: false,
  padding: 32,
  background: "transparent",
  backgroundHex: "#ffffff",
  shadow: false,
  format: "png",
  quality: 90,
  alsoWebp: false,
  srgb: false,
  prefix: "",
  suffix: "",
  find: "",
  replace: "",
  number: false,
  numberStart: 1,
  digits: 2,
  aspectRatio: "auto",
  sharpen: 0,
  keepExif: true,
  brightness: 100,
  contrast: 100,
  saturation: 100,
  autoContrast: false,
  watermarkText: "",
  watermarkPos: "bottom-right",
  watermarkOpacity: 50,
  subfolders: false,
  viewId: null,
  pinned: false,
  picking: false,
  peep: false,
  viewMode: "studio", // 'studio' | 'grid'
  compareMode: "split", // 'split' | 'side' | 'hold'
  backdrop: "dark-check", // 'dark-check' | 'light-check' | 'white' | 'black'
  theme: localStorage.getItem("img_theme") || "dark",
  selectedIds: new Set(),
};

const BUILTIN_PRESETS = {
  product: {
    label: "⚡ Product",
    title: "Product: Background Removal + White Canvas + 32px padding + Box 2048 + WebP",
    recipe: {
      task: "cutout",
      background: "white",
      trim: true,
      padding: 32,
      fit: "box",
      fitA: 2048,
      fitB: 2048,
      format: "webp",
      quality: 90,
      shadow: false,
    },
  },
  photo4x: {
    label: "🔍 4× Photo",
    title: "Print/HD: 4× Upscale Photo + PNG",
    recipe: {
      task: "upscale",
      scale: 4,
      look: "photo",
      format: "png",
      fit: "none",
    },
  },
  anime4x: {
    label: "🎨 4× Art",
    title: "Illustration: 4× Upscale Art + PNG",
    recipe: {
      task: "upscale",
      scale: 4,
      look: "illustration",
      format: "png",
      fit: "none",
    },
  },
  webopt: {
    label: "🌐 WebP",
    title: "Web Optimize: Resize 1920px + 82% WebP",
    recipe: {
      task: "resize",
      fit: "long",
      fitA: 1920,
      format: "webp",
      quality: 82,
    },
  },
  "clean-cut": {
    label: "✂️ Remove BG",
    title: "Sticker: Background Removal + Transparent + Soft Shadow",
    recipe: {
      task: "cutout",
      background: "transparent",
      shadow: true,
      format: "png",
      trim: false,
    },
  },
};

function getCustomPresets() {
  try {
    return JSON.parse(localStorage.getItem("img_custom_presets") || "{}");
  } catch {
    return {};
  }
}

function saveCustomPresets(presets) {
  localStorage.setItem("img_custom_presets", JSON.stringify(presets));
}

function renderPresets() {
  const container = $("presets");
  if (!container) return;
  container.innerHTML = "";

  // Built-in presets
  Object.entries(BUILTIN_PRESETS).forEach(([key, item]) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-chip";
    btn.dataset.preset = key;
    btn.title = item.title;
    btn.innerHTML = `<span>${item.label}</span>`;
    btn.addEventListener("click", () => applyPreset(item.recipe, item.label));
    container.appendChild(btn);
  });

  // Custom user presets
  const custom = getCustomPresets();
  Object.entries(custom).forEach(([id, item]) => {
    const chip = document.createElement("div");
    chip.className = "preset-chip custom";
    chip.title = `Custom Preset: ${item.label}`;

    const labelBtn = document.createElement("button");
    labelBtn.type = "button";
    labelBtn.className = "preset-label-btn";
    labelBtn.innerHTML = `<span>⭐ ${escapeHtml(item.label)}</span>`;
    labelBtn.addEventListener("click", () => applyPreset(item.settings, item.label));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "preset-del-btn";
    delBtn.title = "Delete this preset";
    delBtn.textContent = "×";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      delete custom[id];
      saveCustomPresets(custom);
      renderPresets();
      toast(`Deleted preset "${item.label}"`);
    });

    chip.appendChild(labelBtn);
    chip.appendChild(delBtn);
    container.appendChild(chip);
  });
}

function applyPreset(settings, label) {
  Object.assign(ui, settings);
  render(snapshot);
  toast(`Preset applied: ${label}`);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const SETTINGS_MAP = {
  task: "task",
  scale: "scale",
  look: "look",
  save: "save",
  fit: "fit",
  fit_a: "fitA",
  fit_b: "fitB",
  no_upscale: "noUpscale",
  edge: "edge",
  fill_holes: "fillHoles",
  trim: "trim",
  padding: "padding",
  background: "background",
  background_hex: "backgroundHex",
  shadow: "shadow",
  format: "format",
  quality: "quality",
  also_webp: "alsoWebp",
  srgb: "srgb",
  prefix: "prefix",
  suffix: "suffix",
  find: "find",
  replace: "replace",
  number: "number",
  number_start: "numberStart",
  digits: "digits",
  aspect_ratio: "aspectRatio",
  sharpen: "sharpen",
  keep_exif: "keepExif",
  brightness: "brightness",
  contrast: "contrast",
  saturation: "saturation",
  auto_contrast: "autoContrast",
  watermark_text: "watermarkText",
  watermark_pos: "watermarkPos",
  watermark_opacity: "watermarkOpacity",
};

let settingsReady = false;
let snapshot = null;
let timer = null;
let sseSource = null;
let listSig = "";
let shownRev = "";
const progressFloor = new Map();

const $ = (id) => document.getElementById(id);

// Initialize Theme
document.documentElement.setAttribute("data-theme", ui.theme);

$("theme-toggle").addEventListener("click", () => {
  ui.theme = ui.theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", ui.theme);
  localStorage.setItem("img_theme", ui.theme);
  toast(`Switched to ${ui.theme} mode`);
});

// View Mode Toggle (Studio vs Gallery Grid)
$("view-mode-studio").addEventListener("click", () => setViewMode("studio"));
$("view-mode-grid").addEventListener("click", () => setViewMode("grid"));

function setViewMode(mode) {
  ui.viewMode = mode;
  $("view-mode-studio").classList.toggle("active", mode === "studio");
  $("view-mode-grid").classList.toggle("active", mode === "grid");
  $("stage").classList.toggle("view-grid", mode === "grid");
  if (mode === "studio") {
    fitFrame();
    fitSource();
  }
}

// Comparison Mode Switching (Split / Side-by-Side / Peek)
document.querySelectorAll("#compare-mode-seg button").forEach((btn) => {
  btn.addEventListener("click", () => {
    const mode = btn.dataset.compare;
    setCompareMode(mode);
  });
});

function setCompareMode(mode) {
  ui.compareMode = mode;
  document.querySelectorAll("#compare-mode-seg button").forEach((b) => {
    b.classList.toggle("active", b.dataset.compare === mode);
  });
  const frame = $("frame");
  frame.classList.toggle("mode-side", mode === "side");
  frame.classList.toggle("mode-peek", mode === "hold");
  if (mode === "split") {
    setSplit($("split").value);
  }
}

// Peek Mode (Hold button or spacebar)
const peekBtn = $("btn-peek");
peekBtn.addEventListener("mousedown", () => $("frame").classList.add("peeking"));
peekBtn.addEventListener("mouseup", () => $("frame").classList.remove("peeking"));
peekBtn.addEventListener("mouseleave", () => $("frame").classList.remove("peeking"));

// Transparency Backdrop Switcher
document.querySelectorAll(".btn-backdrop").forEach((btn) => {
  btn.addEventListener("click", () => {
    const backdrop = btn.dataset.backdrop;
    ui.backdrop = backdrop;
    document.querySelectorAll(".btn-backdrop").forEach((b) => {
      b.classList.toggle("active", b.dataset.backdrop === backdrop);
    });
    const frame = $("frame");
    frame.className = frame.className.replace(/backdrop-\S+/g, "");
    frame.classList.add(`backdrop-${backdrop}`);
  });
});

// Initial render of presets toolbar
renderPresets();

// Save as Preset Handler
$("btn-save-preset").addEventListener("click", () => {
  const name = prompt("Name your preset (e.g., 'E-Commerce 4K', 'Square Social'):");
  if (!name || !name.trim()) return;
  const custom = getCustomPresets();
  const id = "custom_" + Date.now();
  custom[id] = {
    label: name.trim(),
    settings: {
      task: ui.task,
      scale: ui.scale,
      look: ui.look,
      fit: ui.fit,
      fitA: ui.fitA,
      fitB: ui.fitB,
      noUpscale: ui.noUpscale,
      edge: ui.edge,
      fillHoles: ui.fillHoles,
      trim: ui.trim,
      padding: ui.padding,
      background: ui.background,
      backgroundHex: ui.backgroundHex,
      shadow: ui.shadow,
      format: ui.format,
      quality: ui.quality,
      alsoWebp: ui.alsoWebp,
      srgb: ui.srgb,
      prefix: ui.prefix,
      suffix: ui.suffix,
      find: ui.find,
      replace: ui.replace,
      number: ui.number,
      numberStart: ui.numberStart,
      digits: ui.digits,
    },
  };
  saveCustomPresets(custom);
  renderPresets();
  toast(`Preset "${name.trim()}" saved to top bar!`);
});

// Export & Import Presets
$("btn-export-presets").addEventListener("click", () => {
  const custom = getCustomPresets();
  if (!Object.keys(custom).length) {
    toast("No custom presets to export yet. Save a preset first!");
    return;
  }
  const blob = new Blob([JSON.stringify(custom, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "image_utilities_presets.json";
  a.click();
  URL.revokeObjectURL(url);
  toast("Exported custom presets");
});

$("btn-import-presets").addEventListener("click", () => {
  $("import-presets-file").click();
});

$("import-presets-file").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    if (typeof data !== "object" || data === null) throw new Error("Invalid preset format");
    const existing = getCustomPresets();
    const merged = { ...existing, ...data };
    saveCustomPresets(merged);
    renderPresets();
    toast(`Imported ${Object.keys(data).length} presets successfully!`);
  } catch (err) {
    toast("Failed to import presets: " + err.message);
  } finally {
    $("import-presets-file").value = "";
  }
});

// Clear Queue
$("clear-all").addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/items/clear");
    ui.viewId = null;
    ui.pinned = false;
    ui.selectedIds.clear();
    updateSelectionBar();
    shownRev = "";
    apply(data);
    toast("Queue cleared");
  } catch (err) {
    toast(err.message);
  }
});

// Multi-Selection Action Bar
$("btn-delete-selected").addEventListener("click", async () => {
  if (!ui.selectedIds.size) return;
  const ids = Array.from(ui.selectedIds);
  try {
    const response = await fetch("/api/items/remove-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    const data = await readBody(response);
    if (!response.ok) throw new Error(errorText(data));
    ui.selectedIds.clear();
    updateSelectionBar();
    apply(data);
    toast(`Deleted ${ids.length} images`);
  } catch (err) {
    toast(err.message);
  }
});

$("btn-deselect").addEventListener("click", () => {
  ui.selectedIds.clear();
  updateSelectionBar();
  renderList(snapshot && snapshot.batch);
});

function updateSelectionBar() {
  const bar = $("selection-bar");
  const count = ui.selectedIds.size;
  bar.hidden = count < 2;
  $("selection-count").textContent = `${count} selected`;
}

// Segmented Buttons Handler
document.querySelectorAll(".seg").forEach((group) => {
  group.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    const value = group.id === "scale" ? Number(button.dataset.value) : button.dataset.value;
    if (group.id === "task") {
      if (value === "resize" && ui.fit === "none") ui.fit = "long";
      if (value !== "resize" && ui.format === "same") {
        ui.format = value === "convert" ? "webp" : "png";
      }
    }
    ui[group.id] = value;
    if (group.id === "format") ui.srgb = value === "jpeg" || value === "webp" || value === "svg";
    render(snapshot);
  });
});

bindCheck("fill-holes", "fillHoles");
bindCheck("trim", "trim");
bindCheck("shadow", "shadow");
bindCheck("also-webp", "alsoWebp");
bindCheck("srgb", "srgb");
bindCheck("no-upscale", "noUpscale");
bindCheck("number", "number");
bindCheck("keep-exif", "keepExif");
bindCheck("auto-contrast", "autoContrast");
bindNumber("fit-a", "fitA");
bindNumber("fit-b", "fitB");
bindNumber("padding", "padding");
bindNumber("quality", "quality");
bindNumber("number-start", "numberStart");
bindNumber("digits", "digits");
bindText("prefix", "prefix");
bindText("suffix", "suffix");
bindText("find", "find");
bindText("replace", "replace");
bindText("watermark-text", "watermarkText");
$("background-hex").addEventListener("input", () => {
  ui.backgroundHex = $("background-hex").value;
});
$("aspect-ratio").addEventListener("change", () => {
  ui.aspectRatio = $("aspect-ratio").value;
  render(snapshot);
});
$("sharpen").addEventListener("input", () => {
  ui.sharpen = Number($("sharpen").value) || 0;
  const val = $("sharpen-val");
  if (val) val.textContent = `${ui.sharpen}%`;
  render(snapshot);
});
$("brightness").addEventListener("input", () => {
  ui.brightness = Number($("brightness").value) || 100;
  const val = $("brightness-val");
  if (val) val.textContent = `${ui.brightness}%`;
  render(snapshot);
});
$("contrast").addEventListener("input", () => {
  ui.contrast = Number($("contrast").value) || 100;
  const val = $("contrast-val");
  if (val) val.textContent = `${ui.contrast}%`;
  render(snapshot);
});
$("saturation").addEventListener("input", () => {
  ui.saturation = Number($("saturation").value) || 100;
  const val = $("saturation-val");
  if (val) val.textContent = `${ui.saturation}%`;
  render(snapshot);
});
$("watermark-pos").addEventListener("change", () => {
  ui.watermarkPos = $("watermark-pos").value;
  render(snapshot);
});
$("watermark-opacity").addEventListener("input", () => {
  ui.watermarkOpacity = Number($("watermark-opacity").value) || 50;
  const val = $("watermark-opacity-val");
  if (val) val.textContent = `${ui.watermarkOpacity}%`;
  render(snapshot);
});
$("btn-undo").addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/items/undo");
    apply(data);
    toast("Restored queue items");
  } catch (err) {
    toast(err.message);
  }
});
$("btn-download-zip").addEventListener("click", () => {
  window.location.href = "/api/batch/zip";
});

$("choose-files").addEventListener("click", () => pick("/api/pick/files"));
$("choose-folder").addEventListener("click", () =>
  pick("/api/pick/folder", { subfolders: ui.subfolders })
);
$("change-dir").addEventListener("click", () => pick("/api/output-dir"));
$("subfolders").addEventListener("change", () => {
  ui.subfolders = $("subfolders").checked;
});
$("run").addEventListener("click", onRun);
$("reveal").addEventListener("click", reveal);
$("copy").addEventListener("click", copyResult);
$("peep").addEventListener("click", () => {
  ui.peep = !ui.peep;
  fitFrame();
});
$("frame").addEventListener("dblclick", () => {
  ui.peep = !ui.peep;
  fitFrame();
});
$("split").addEventListener("input", () => setSplit($("split").value));
$("list").addEventListener("click", onListClick);
$("fit").addEventListener("change", () => {
  const prevFit = ui.fit;
  ui.fit = $("fit").value;
  if (ui.fit === "percent" && prevFit !== "percent") {
    if (ui.fitA > 800 || ui.fitA === 2048) ui.fitA = 50;
  } else if (ui.fit !== "percent" && prevFit === "percent") {
    if (ui.fitA <= 100) ui.fitA = 2048;
  }
  render(snapshot);
});

if (window.ResizeObserver) {
  const watcher = new ResizeObserver(() => {
    fitFrame();
    fitSource();
  });
  watcher.observe($("frame-slot"));
  watcher.observe($("source-slot"));
}
$("source-preview").addEventListener("load", () => requestAnimationFrame(fitSource));

// Smart Drag & Drop with Dual Target Overlay
const stage = $("stage");
const dropOverlay = $("drop-overlay");
const dropTargetAdd = $("drop-target-add");
const dropTargetReplace = $("drop-target-replace");

["dragenter", "dragover"].forEach((name) => {
  stage.addEventListener(name, (event) => {
    event.preventDefault();
    stage.classList.add("hot");
    const count = snapshot && snapshot.batch ? snapshot.batch.items.length : 0;
    if (count > 0 && dropOverlay) {
      dropOverlay.hidden = false;
    }
  });
});

stage.addEventListener("dragleave", (event) => {
  if (!stage.contains(event.relatedTarget)) {
    stage.classList.remove("hot");
    if (dropOverlay) dropOverlay.hidden = true;
  }
});

stage.addEventListener("drop", (event) => {
  event.preventDefault();
  stage.classList.remove("hot");
  if (dropOverlay) dropOverlay.hidden = true;
  receiveDrop(event.dataTransfer);
});

if (dropOverlay && dropTargetAdd && dropTargetReplace) {
  [dropTargetAdd, dropTargetReplace].forEach((target) => {
    target.addEventListener("dragenter", () => target.classList.add("hovered"));
    target.addEventListener("dragleave", () => target.classList.remove("hovered"));
    target.addEventListener("drop", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropOverlay.hidden = true;
      stage.classList.remove("hot");
      target.classList.remove("hovered");
      if (target.id === "drop-target-replace") {
        await postJSON("/api/items/clear");
      }
      receiveDrop(event.dataTransfer);
    });
  });
}

document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());

// Keyboard Shortcuts
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    onRun();
  }
  if ((event.metaKey || event.ctrlKey) && (event.key === "z" || event.key === "Z") && !isInputActive()) {
    event.preventDefault();
    $("btn-undo").click();
  }
  if (event.code === "Space" && !isInputActive()) {
    event.preventDefault();
    $("frame").classList.add("peeking");
  }
  if (event.key === "Escape") {
    if (ui.selectedIds.size > 0) {
      ui.selectedIds.clear();
      updateSelectionBar();
      renderList(snapshot && snapshot.batch);
    }
  }
});

document.addEventListener("keyup", (event) => {
  if (event.code === "Space") {
    $("frame").classList.remove("peeking");
  }
});

function isInputActive() {
  const active = document.activeElement;
  return active && (active.tagName === "INPUT" || active.tagName === "SELECT" || active.tagName === "TEXTAREA");
}

load();
initSSE();

async function load() {
  apply(await getJSON("/api/state"));
}

function initSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource("/api/events");
  sseSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      apply(data);
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };
  sseSource.onerror = () => {
    if (snapshot && snapshot.batch && snapshot.batch.status === "running") {
      watch();
    }
  };
}

async function pick(url, body) {
  if (ui.picking) return;
  ui.picking = true;
  render(snapshot);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await readBody(response);
    if (!response.ok) throw new Error(errorText(data));
    if (!data.cancelled) {
      ui.pinned = false;
      ui.viewId = null;
      shownRev = "";
    }
    apply(data);
  } catch (error) {
    toast(error.message);
  } finally {
    ui.picking = false;
    render(snapshot);
  }
}

async function receiveDrop(transfer) {
  const files = (await filesFrom(transfer)).filter(isImage);
  if (!files.length) {
    toast("None of those files look like supported images.");
    return;
  }
  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));
  ui.picking = true;
  render(snapshot);
  try {
    const response = await fetch("/api/uploads", { method: "POST", body: form });
    const data = await readBody(response);
    if (!response.ok) throw new Error(errorText(data));
    ui.pinned = false;
    ui.viewId = null;
    shownRev = "";
    apply(data);
    toast(`Added ${files.length} images`);
  } catch (error) {
    toast(error.message);
  } finally {
    ui.picking = false;
    render(snapshot);
  }
}

async function onRun() {
  const batch = snapshot && snapshot.batch;
  if (!batch || ui.picking) return;
  if (batch.status === "running") {
    apply(await postJSON("/api/cancel"));
    toast("Cancelled batch");
    return;
  }
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(runBody()),
  });
  const data = await readBody(response);
  if (!response.ok) {
    toast(errorText(data));
    return;
  }
  apply(data);
  watch();
  toast("Started processing…");
}

async function reveal() {
  if (!ui.viewId) return;
  await fetch(`/api/items/${ui.viewId}/reveal`, { method: "POST" });
}

function watch() {
  if (timer) return;
  timer = setInterval(pull, 400);
}

async function pull() {
  try {
    const data = await getJSON("/api/state");
    apply(data);
    if (!data.batch || data.batch.status !== "running") {
      clearInterval(timer);
      timer = null;
      if (data.batch && data.batch.status === "done") {
        toast("Batch completed successfully! 🎉");
      }
    }
  } catch (error) {
    toast(error.message);
  }
}

function apply(data) {
  if (!data) return;
  takeSettings(data);
  const prevBatchStatus = snapshot && snapshot.batch && snapshot.batch.status;
  snapshot = data;
  if (data.batch && data.batch.status === "running") {
    watch();
  } else if (prevBatchStatus === "running" && data.batch && data.batch.status === "done") {
    toast("Batch completed successfully! 🎉");
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("Image Utilities", {
        body: `Batch complete: ${data.batch.items.length} pictures processed! 🎉`,
        icon: "/static/favicon.svg",
      });
    }
  }
  render(data);
}

function render(data) {
  const batch = data && data.batch;
  const running = Boolean(batch && batch.status === "running");
  const uploaded = Boolean(batch && batch.origin === "upload");

  $("device").textContent = data && data.device === "GPU" ? "Apple Silicon GPU" : data && data.device === "CPU" ? "CPU Fallback" : "On this Mac";
  $("output-dir").textContent = (data && data.output_dir) || "";
  $("output-dir").title = (data && data.output_dir) || "";

  setPressed("task", ui.task);
  setPressed("scale", String(ui.scale));
  setPressed("look", ui.look);
  setPressed("save", uploaded ? "folder" : ui.save);

  const enlarges = ui.task === "upscale" || ui.task === "both";
  const cuts = ui.task === "cutout" || ui.task === "both";
  show("panel-enlarge", enlarges);
  show("panel-fit", ui.task !== "convert" && ui.task !== "rename");
  show("panel-edge", cuts);
  show("panel-canvas", cuts);
  show("panel-tone", ui.task !== "rename" && ui.task !== "convert");
  show("panel-watermark", ui.task !== "rename" && ui.task !== "convert");
  show("panel-file", ui.task !== "rename");
  show("fit-fields", ui.fit !== "none");
  show("fit-b-wrap", ui.fit === "box");
  show("no-upscale-row", ui.fit !== "none");
  show("sharpen-row", ui.task !== "convert" && ui.task !== "rename");
  show("aspect-ratio-row", ui.task !== "convert" && ui.task !== "rename");
  show("padding-row", ui.trim);
  show("quality-row", ui.format === "jpeg" || ui.format === "webp");
  show("webp-row", ui.format !== "webp");
  show("color-row", ui.background === "custom");
  show("number-fields", ui.number);

  const same = document.querySelector('#format button[data-value="same"]');
  if (same) same.hidden = ui.task !== "resize";
  const none = $("fit").querySelector('option[value="none"]');
  if (none) {
    none.disabled = ui.task === "resize";
    if (enlarges) {
      none.textContent = `Full AI Upscale (${ui.scale}×)`;
      none.title = `Export at full ${ui.scale}× super-resolution`;
    } else {
      none.textContent = "Original size (1×)";
      none.title = "Keep original image dimensions";
    }
  }
  if (document.activeElement !== $("fit")) $("fit").value = ui.fit;

  const lock = running || ui.picking;
  document.querySelectorAll(".controls button, .controls input, .controls select").forEach((node) => {
    if (node.id === "run") return;
    node.disabled = lock;
  });
  document.querySelectorAll(".preset-chip, .preset-chip button").forEach((btn) => (btn.disabled = lock));
  document.querySelector('#save button[data-value="beside"]').disabled = lock || uploaded;
  $("padding").disabled = lock || !ui.trim;

  setPressed("edge", ui.edge);
  setPressed("background", ui.background);
  setPressed("format", ui.format);
  syncField("fit-a", ui.fitA);
  syncField("fit-b", ui.fitB);
  syncField("padding", ui.padding);
  syncField("quality", ui.quality);
  syncField("prefix", ui.prefix);
  syncField("suffix", ui.suffix);
  syncField("find", ui.find);
  syncField("replace", ui.replace);
  syncField("number-start", ui.numberStart);
  syncField("digits", ui.digits);
  syncField("background-hex", ui.backgroundHex);
  syncField("fill-holes", ui.fillHoles);
  syncField("trim", ui.trim);
  syncField("shadow", ui.shadow);
  syncField("also-webp", ui.alsoWebp);
  syncField("srgb", ui.srgb);
  syncField("no-upscale", ui.noUpscale);
  syncField("number", ui.number);
  syncField("keep-exif", ui.keepExif);
  syncField("sharpen", ui.sharpen);
  const sharpenVal = $("sharpen-val");
  if (sharpenVal) sharpenVal.textContent = `${ui.sharpen}%`;

  syncField("auto-contrast", ui.autoContrast);
  syncField("brightness", ui.brightness);
  const brightnessVal = $("brightness-val");
  if (brightnessVal) brightnessVal.textContent = `${ui.brightness}%`;

  syncField("contrast", ui.contrast);
  const contrastVal = $("contrast-val");
  if (contrastVal) contrastVal.textContent = `${ui.contrast}%`;

  syncField("saturation", ui.saturation);
  const saturationVal = $("saturation-val");
  if (saturationVal) saturationVal.textContent = `${ui.saturation}%`;

  syncField("watermark-text", ui.watermarkText);
  const wmPos = $("watermark-pos");
  if (wmPos && document.activeElement !== wmPos) wmPos.value = ui.watermarkPos;
  syncField("watermark-opacity", ui.watermarkOpacity);
  const wmOpacityVal = $("watermark-opacity-val");
  if (wmOpacityVal) wmOpacityVal.textContent = `${ui.watermarkOpacity}%`;

  const arNode = $("aspect-ratio");
  if (arNode && document.activeElement !== arNode) arNode.value = ui.aspectRatio;

  $("fit-legend").textContent = enlarges ? "Output size:" : ui.task === "resize" ? "Resize to:" : "Size:";
  $("fit-a-label").textContent = { long: "Long edge", width: "Width", height: "Height", box: "Width", percent: "Percent" }[ui.fit] || "Size";

  const isPercent = ui.fit === "percent";
  const fitUnit = $("fit-unit");
  if (fitUnit) fitUnit.textContent = isPercent ? "%" : "px";
  const fitAInput = $("fit-a");
  if (fitAInput) {
    fitAInput.placeholder = isPercent ? "50" : "2048";
    fitAInput.max = isPercent ? "800" : "20000";
    fitAInput.setAttribute("aria-label", isPercent ? "Scale percentage" : "Size in pixels");
  }

  const names = $("name-more");
  if (names) {
    names.classList.toggle("primary", ui.task === "rename");
    if ("open" in names && ui.task === "rename") names.open = true;
  }
  const renameLegend = $("rename-legend");
  if (renameLegend) renameLegend.textContent = ui.task === "rename" ? "Names" : "File name";
  $("task-hint").textContent = taskHint();
  $("scale-hint").textContent = scaleHint();
  $("look-hint").textContent = ui.look === "illustration" ? "Clean lines & flat anime colors." : "Natural textures & product photos.";
  $("fit-hint").textContent = fitHint();
  $("file-hint").textContent = fileHint();
  $("rename-hint").textContent = ui.number
    ? "The number counts from the top of the list."
    : "Preview reflects output name pattern.";
  $("save-hint").textContent = saveHint(uploaded);

  const count = batch ? batch.items.length : 0;
  $("stage").classList.toggle("idle", count === 0);
  $("stage-count").textContent = count === 1 ? "1 picture" : `${count} pictures`;
  $("queue-count-tag").textContent = count ? `${count} items` : "";
  $("clear-all").hidden = count === 0 || running;
  $("choose-files").disabled = ui.picking || running;
  $("choose-folder").disabled = ui.picking || running;
  $("change-dir").disabled = ui.picking || running;
  $("subfolders").disabled = running;

  const doneCount = batch ? batch.items.filter((i) => i.status === "done").length : 0;
  const zipBtn = $("btn-download-zip");
  if (zipBtn) zipBtn.hidden = doneCount === 0 || running;
  const undoBtn = $("btn-undo");
  if (undoBtn) undoBtn.hidden = running;

  const run = $("run");
  run.disabled = ui.picking || !count;
  run.textContent = running ? "Cancel Batch" : ui.task === "rename" ? "Rename Files" : "Run Batch";
  run.classList.toggle("cancel", running);

  const notice = (batch && batch.notice) || (data && data.notice) || "";
  $("notice").hidden = !notice;
  $("notice").textContent = notice;

  renderOverall(batch);
  renderList(batch);
  renderViewer(batch);
}

function renderOverall(batch) {
  const bar = $("overall");
  if (!batch || batch.status !== "running") {
    bar.hidden = true;
    return;
  }
  const values = batch.items.map(shownProgress);
  const mean = values.reduce((sum, value) => sum + value, 0) / (values.length || 1);
  bar.hidden = false;
  const pct = Math.round(mean * 100);
  $("overall-bar").style.width = `${pct}%`;
  const doneItems = batch.items.filter((i) => i.status === "done");
  const doneCount = doneItems.length;
  const total = batch.items.length;

  let speedText = "";
  if (doneCount > 0) {
    const totalDoneSeconds = doneItems.reduce((acc, cur) => acc + (cur.seconds || 0), 0);
    if (totalDoneSeconds > 0) {
      const avgSecPerItem = totalDoneSeconds / doneCount;
      const remainingItems = total - doneCount;
      const remainingSec = Math.round(remainingItems * avgSecPerItem);
      const speed = avgSecPerItem < 1 ? `${(1 / avgSecPerItem).toFixed(1)} img/s` : `${avgSecPerItem.toFixed(1)} s/img`;
      const eta = remainingSec > 60 ? `${Math.floor(remainingSec / 60)}m ${remainingSec % 60}s` : `${remainingSec}s`;
      speedText = ` · ~${eta} remaining (${speed})`;
    }
  }

  $("overall-text").textContent = `Processing ${doneCount} of ${total} (${pct}%)${speedText}`;
}

function renderList(batch) {
  const list = $("list");
  if (!batch || !batch.items.length) {
    list.replaceChildren();
    listSig = "";
    return;
  }
  const sig = batch.items.map((item) => item.id).join("|");
  if (sig !== listSig) {
    listSig = sig;
    list.replaceChildren(...batch.items.map(rowTemplate));
  }
  batch.items.forEach((item, index) => updateRow(item, batch, index));
}

function rowTemplate(item) {
  const row = document.createElement("li");
  row.className = "row";
  row.dataset.id = item.id;
  row.innerHTML = `
    <img alt="" data-loaded="">
    <div>
      <p class="name"></p>
      <p class="meta"></p>
    </div>
    <button type="button" class="icon" data-action="remove" title="Remove from queue" aria-label="Remove">×</button>`;
  return row;
}

function updateRow(item, batch, index) {
  const row = document.querySelector(`.row[data-id="${item.id}"]`);
  if (!row) return;
  row.classList.toggle("error", item.status === "error");
  row.classList.toggle("done", item.status === "done");
  row.classList.toggle("multi-selected", ui.selectedIds.has(item.id));
  row.style.setProperty("--p", item.status === "running" ? String(shownProgress(item)) : "0");
  row.querySelector(".name").textContent = item.name;
  row.querySelector(".meta").textContent = rowText(item, index);
  const remove = row.querySelector("button");
  remove.hidden = batch.status === "running";
  const img = row.querySelector("img");
  if (item.status === "done" && img.dataset.kind !== "result") {
    img.src = `/api/items/${item.id}/thumb?v=${Date.now()}`;
    img.dataset.kind = "result";
  } else if (!img.dataset.kind) {
    img.src = `/api/items/${item.id}/thumb`;
    img.dataset.kind = "source";
  }
}

function rowText(item, index) {
  if (item.status === "running") return item.phase || "Working…";
  if (item.status === "error") return item.message || "Failed";
  if (item.status === "cancelled") return "Cancelled";
  if (item.status === "done") {
    const size = item.source_width ? `${item.source_width}×${item.source_height} → ${item.width}×${item.height}` : "";
    const extra = [size, item.bytes_label, item.seconds ? `${item.seconds}s` : "", item.note]
      .filter(Boolean)
      .join(" · ");
    return extra || "Saved";
  }
  const where = ui.task === "rename" && ui.save === "beside" && item.origin !== "upload"
    ? "rename in place"
    : ui.save === "folder" || item.origin === "upload"
      ? "output folder"
      : "next to original";
  return `${outputName(item.name, index)} · ${where}`;
}

function renderViewer(batch) {
  const items = batch ? batch.items : [];
  if (!ui.pinned) {
    const runningItem = items.find((item) => item.status === "running");
    const done = items.filter((item) => item.status === "done");
    const pick = runningItem || done[done.length - 1] || items[items.length - 1];
    ui.viewId = pick ? pick.id : null;
  }
  if (ui.viewId && !items.some((item) => item.id === ui.viewId)) {
    ui.viewId = items.length ? items[items.length - 1].id : null;
    ui.pinned = false;
  }
  const item = items.find((entry) => entry.id === ui.viewId) || null;
  const hasResult = Boolean(item && item.status === "done" && item.output);

  $("drop").hidden = items.length > 0;
  $("source-view").hidden = !item || hasResult;
  $("frame-wrap").hidden = !hasResult;

  document.querySelectorAll(".row").forEach((row) => {
    row.classList.toggle("selected", Boolean(item) && row.dataset.id === item.id);
  });

  if (!item) {
    shownRev = "";
    return;
  }

  if (!hasResult) {
    const index = items.findIndex((entry) => entry.id === item.id);
    $("source-caption").textContent = `${item.name} · ${rowText(item, Math.max(index, 0))}`;
  }

  const rev = hasResult ? `result:${item.id}:${item.output}` : `source:${item.id}`;
  if (rev === shownRev) return;
  shownRev = rev;

  if (!hasResult) {
    const preview = $("source-preview");
    preview.alt = item.name;
    preview.onerror = () => {
      preview.onerror = null;
      preview.src = `/api/items/${item.id}/thumb`;
    };
    preview.src = `/api/items/${item.id}/preview/source`;
    return;
  }

  $("before").src = `/api/items/${item.id}/preview/before?v=${Date.now()}`;
  $("after").src = `/api/items/${item.id}/preview/after?v=${Date.now()}`;

  const index = items.findIndex((entry) => entry.id === item.id);
  const file = item.output ? item.output.split("/").pop() : outputName(item.name, Math.max(index, 0));
  $("viewer-dim").textContent = `${item.width}×${item.height} px`;
  $("viewer-size").textContent = item.bytes_label || "";
  $("viewer-caption").textContent = file;

  setSplit($("split").value);
  $("after").addEventListener("load", () => requestAnimationFrame(fitFrame), { once: true });
}

function fitFrame() {
  const image = $("after");
  const frame = $("frame");
  const zoom = $("zoom");
  const slot = $("frame-slot");
  if (!image.naturalWidth || !zoom || !slot) return;
  $("peep").textContent = ui.peep ? "Fit" : "1:1";
  $("peep").setAttribute("aria-pressed", String(ui.peep));
  if (ui.peep) {
    frame.classList.add("peep");
    frame.style.width = "";
    frame.style.height = "";
    zoom.style.width = `${image.naturalWidth}px`;
    zoom.style.height = `${image.naturalHeight}px`;
    return;
  }
  frame.classList.remove("peep");
  zoom.style.width = "";
  zoom.style.height = "";
  const size = fittedSize(image.naturalWidth, image.naturalHeight, slot);
  if (!size) return;
  frame.style.width = `${size.width}px`;
  frame.style.height = `${size.height}px`;
}

function fitSource() {
  const image = $("source-preview");
  const size = fittedSize(image.naturalWidth, image.naturalHeight, $("source-slot"));
  if (!size) return;
  image.style.width = `${size.width}px`;
  image.style.height = `${size.height}px`;
}

function fittedSize(naturalWidth, naturalHeight, slot) {
  if (!naturalWidth || !naturalHeight || !slot) return null;
  const bounds = slot.getBoundingClientRect();
  if (bounds.width < 8 || bounds.height < 8) return null;
  const ratio = naturalWidth / naturalHeight;
  let width = bounds.width;
  let height = width / ratio;
  if (height > bounds.height) {
    height = bounds.height;
    width = height * ratio;
  }
  return { width: Math.max(1, Math.floor(width)), height: Math.max(1, Math.floor(height)) };
}

function setSplit(value) {
  if (ui.compareMode !== "split") return;
  const percent = Number(value) / 10;
  $("after").style.clipPath = `inset(0 0 0 ${percent}%)`;
  $("handle").style.left = `${percent}%`;
}

async function onListClick(event) {
  const button = event.target.closest("button");
  const row = event.target.closest(".row");
  if (!row) return;

  if (button && button.dataset.action === "remove") {
    const response = await fetch(`/api/items/${row.dataset.id}`, { method: "DELETE" });
    const data = await readBody(response);
    if (!response.ok) {
      toast(errorText(data));
      return;
    }
    ui.selectedIds.delete(row.dataset.id);
    updateSelectionBar();
    if (ui.viewId === row.dataset.id) {
      ui.viewId = null;
      ui.pinned = false;
      shownRev = "";
    }
    apply(data);
    return;
  }

  const items = (snapshot && snapshot.batch && snapshot.batch.items) || [];
  const clickedId = row.dataset.id;
  const clickedIndex = items.findIndex((i) => i.id === clickedId);

  if (event.shiftKey && ui.viewId) {
    const lastIndex = items.findIndex((i) => i.id === ui.viewId);
    if (lastIndex !== -1 && clickedIndex !== -1) {
      const [start, end] = [Math.min(lastIndex, clickedIndex), Math.max(lastIndex, clickedIndex)];
      for (let i = start; i <= end; i++) {
        ui.selectedIds.add(items[i].id);
      }
    }
    updateSelectionBar();
    renderList(snapshot && snapshot.batch);
    return;
  }

  if (event.metaKey || event.ctrlKey) {
    if (ui.selectedIds.has(clickedId)) {
      ui.selectedIds.delete(clickedId);
    } else {
      ui.selectedIds.add(clickedId);
      if (ui.viewId) ui.selectedIds.add(ui.viewId);
    }
    updateSelectionBar();
    renderList(snapshot && snapshot.batch);
    return;
  }

  // Normal single click
  ui.selectedIds.clear();
  updateSelectionBar();
  ui.viewId = clickedId;
  ui.pinned = true;
  shownRev = "";
  render(snapshot);
}

function setPressed(id, value) {
  document.querySelectorAll(`#${id} button`).forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.value === String(value)));
  });
}

function scaleHint() {
  if (ui.look === "illustration" && ui.scale === 2) {
    return "Upscales 4×, then scales down to 2× so line art stays crisp.";
  }
  return "";
}

function taskHint() {
  const hints = {
    cutout: "Removes background with BiRefNet model.",
    upscale: "Sharpens and upscales using Real-ESRGAN.",
    both: "Upscales first, then removes background cleanly.",
    resize: "Fast high-quality Lanczos resizing without AI.",
    convert: "Re-encodes image formats or traces vector SVG.",
    rename: "Batch renames files using custom rules and counters.",
  };
  return hints[ui.task] || "";
}

function fitHint() {
  const enlarges = ui.task === "upscale" || ui.task === "both";
  const hints = {
    none: enlarges
      ? "Exports at full AI super-resolution (no post-downscaling)."
      : "Preserves original pixel dimensions.",
    long: "Constrains longest edge to this pixel length.",
    width: "Scales width and preserves aspect ratio.",
    height: "Scales height and preserves aspect ratio.",
    box: "Fits proportionally inside bounding box.",
    percent: "Scales canvas by percentage (100% is original).",
  };
  return hints[ui.fit] || "";
}

function fileHint() {
  if (ui.format === "svg") return "SVG vector traces paths (ideal for logos).";
  if (ui.format === "jpeg") return "JPEG quality 1–100 (opaque background).";
  if (ui.format === "webp") return "Modern high-efficiency WebP with transparency.";
  if (ui.format === "same") return "Preserves original format where available.";
  return "";
}

function saveHint(uploaded) {
  if (uploaded) return "Dropped files are saved in the configured output folder.";
  if (ui.task === "rename" && ui.save === "beside") {
    return "Files are renamed safely in their original folders.";
  }
  if (ui.save === "beside") return "Processed copies are saved next to originals.";
  return "All files are saved in the output folder.";
}

function outputName(filename, index) {
  const original = filename.replace(/\.[^.]+$/, "");
  const stem = renamedStem(original, index);
  const suffix = fileSuffix(filename);
  if (ui.task === "rename" || ui.task === "convert") return `${stem}${suffix}`;
  const parts = [stem];
  if (ui.task === "cutout" || ui.task === "both") parts.push("cutout");
  if (ui.task === "upscale" || ui.task === "both") parts.push(`x${ui.scale}`);
  if (ui.task === "resize") parts.push("resized");
  return `${parts.join(".")}${suffix}`;
}

function renamedStem(stem, index) {
  let text = stem;
  if (ui.find) text = text.split(ui.find).join(ui.replace);
  text = `${ui.prefix || ""}${text}${ui.suffix || ""}`.replace(/[\\/:\u0000]/g, "").trim();
  if (ui.number) {
    const digits = Number(ui.digits) || 2;
    const value = (Number(ui.numberStart) || 0) + index;
    text = `${text}-${String(value).padStart(digits, "0")}`;
  }
  return text || stem;
}

function fileSuffix(filename) {
  if (ui.task === "rename" || ui.format === "same") {
    const ext = (filename.match(/\.[^.]+$/) || [".png"])[0].toLowerCase();
    if (ext === ".jpeg" || ext === ".jpg") return ".jpg";
    if (ext === ".png" || ext === ".webp") return ext;
    return ".png";
  }
  return ui.format === "jpeg" ? ".jpg" : `.${ui.format}`;
}

function runBody() {
  return {
    task: ui.task,
    scale: ui.scale,
    look: ui.look,
    save: ui.save,
    fit: ui.fit,
    fit_a: Number(ui.fitA) || 0,
    fit_b: Number(ui.fitB) || 0,
    no_upscale: Boolean(ui.noUpscale),
    edge: ui.edge,
    fill_holes: Boolean(ui.fillHoles),
    trim: Boolean(ui.trim),
    padding: Number(ui.padding) || 0,
    background: ui.background,
    background_hex: ui.backgroundHex || "#ffffff",
    shadow: Boolean(ui.shadow),
    format: ui.format,
    quality: Number(ui.quality) || 90,
    also_webp: Boolean(ui.alsoWebp),
    srgb: Boolean(ui.srgb),
    prefix: ui.prefix || "",
    suffix: ui.suffix || "",
    find: ui.find || "",
    replace: ui.replace || "",
    number: Boolean(ui.number),
    number_start: Number(ui.numberStart) || 0,
    digits: Number(ui.digits) || 2,
    aspect_ratio: ui.aspectRatio || "auto",
    sharpen: Number(ui.sharpen) || 0,
    keep_exif: Boolean(ui.keepExif),
    brightness: Number(ui.brightness) || 100,
    contrast: Number(ui.contrast) || 100,
    saturation: Number(ui.saturation) || 100,
    auto_contrast: Boolean(ui.autoContrast),
    watermark_text: ui.watermarkText || "",
    watermark_pos: ui.watermarkPos || "bottom-right",
    watermark_opacity: Number(ui.watermarkOpacity) || 50,
  };
}

function takeSettings(data) {
  if (settingsReady || !data || !data.settings) return;
  settingsReady = true;
  Object.entries(SETTINGS_MAP).forEach(([from, to]) => {
    if (data.settings[from] !== undefined && data.settings[from] !== null) ui[to] = data.settings[from];
  });
  if (ui.task === "resize" && ui.fit === "none") ui.fit = "long";
  if (ui.task !== "resize" && ui.format === "same") ui.format = ui.task === "convert" ? "webp" : "png";
}

function show(id, on) {
  const node = $(id);
  if (node) node.hidden = !on;
}

function syncField(id, value) {
  const node = $(id);
  if (!node || document.activeElement === node) return;
  if (node.type === "checkbox") {
    node.checked = Boolean(value);
    return;
  }
  const next = value == null ? "" : String(value);
  if (node.value !== next) node.value = value == null ? "" : String(value);
}

function bindCheck(id, key) {
  $(id).addEventListener("change", () => {
    ui[key] = $(id).checked;
    render(snapshot);
  });
}

function bindNumber(id, key) {
  $(id).addEventListener("input", () => {
    const value = Number($(id).value);
    if (Number.isFinite(value)) ui[key] = value;
    render(snapshot);
  });
}

function bindText(id, key) {
  $(id).addEventListener("input", () => {
    ui[key] = $(id).value;
    render(snapshot);
  });
}

async function copyResult() {
  if (!ui.viewId) return;
  try {
    const response = await fetch(`/api/items/${ui.viewId}/file`);
    if (!response.ok) throw new Error("That file isn't saved yet.");
    const blob = await response.blob();
    const item = snapshot && snapshot.batch && snapshot.batch.items.find((entry) => entry.id === ui.viewId);
    const name = item && item.output ? item.output.split("/").pop() : "";
    if (name.toLowerCase().endsWith(".svg") || (blob.type || "").includes("svg")) {
      await navigator.clipboard.writeText(await blob.text());
    } else {
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d").drawImage(bitmap, 0, 0);
      const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
    }
    toast("Image copied to clipboard! 📋");
  } catch (error) {
    toast(error.message || "Couldn't copy picture.");
  }
}

function shownProgress(item) {
  if (item.status !== "running") {
    progressFloor.delete(item.id);
    return item.progress || 0;
  }
  const next = Math.max(progressFloor.get(item.id) || 0, item.progress || 0);
  progressFloor.set(item.id, next);
  return next;
}

function toast(message, duration = 2600) {
  if (!message) return;
  const container = $("toast-container");
  if (!container) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = "toast-out 200ms ease forwards";
    setTimeout(() => el.remove(), 220);
  }, duration);
}

function isImage(file) {
  return /\.(jpe?g|jpe|jfif|png|webp|gif|tiff?|bmp|heic|heif|avif)$/i.test(file.name)
    || (file.type || "").startsWith("image/");
}

async function filesFrom(transfer) {
  const items = [...(transfer.items || [])];
  const entries = items.map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...transfer.files];
  const files = [];
  for (const entry of entries) await walk(entry, files, true);
  return files;
}

async function walk(entry, files, top) {
  if (entry.isFile) {
    files.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
    return;
  }
  if (!entry.isDirectory || (!top && !ui.subfolders)) return;
  const reader = entry.createReader();
  let batch = [];
  do {
    batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    for (const child of batch) await walk(child, files, false);
  } while (batch.length);
}

async function postJSON(url) {
  const response = await fetch(url, { method: "POST" });
  const data = await readBody(response);
  if (!response.ok) throw new Error(errorText(data));
  return data;
}

async function getJSON(url) {
  const response = await fetch(url);
  const data = await readBody(response);
  if (!response.ok) throw new Error(errorText(data));
  return data;
}

async function readBody(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function errorText(data) {
  if (!data) return "The request failed.";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((part) => part.msg || "").join(" ");
  return "The request failed.";
}
