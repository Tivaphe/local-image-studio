<div align="center">

# 🎨 Local Image Studio

### Generate AI images **locally** — 100% private, no data sent to the internet

A simple web interface to generate images with the latest AI models (FLUX, Qwen-Image, Stable Diffusion 3.5, Z-Image…). Designed for **beginners**: no nodes, no command line, just a prompt and a button.

[🇫🇷 README en français](./README.md)

</div>

---

## ✨ In 30 seconds

```
1. Double-click start.bat
2. Chrome opens by itself on http://127.0.0.1:7860
3. Download a model → Write a prompt → Generate!
```

> 🔄 **Updating**: double-click **`update.bat`** — it detects your setup automatically:
> **git clone** (fast-forward pull + stash of local changes on confirmation) or **ZIP archive**
> (no git: downloads the chosen branch ZIP, backs up the code, then replaces the application
> files — ideal if you downloaded the GitHub ZIP). Either way: branch picker
> (`main` or others), your models, images, history and settings **never touched**, and
> **dependencies reinstalled in `.venv`** automatically.

**No image, no prompt ever leaves your computer.** Everything runs on your local GPU.

## 📸 Interface preview

| Generate — dark theme | Generate — light theme (☀️/🌙 toggle in the top bar) |
|---|---|
| ![Generate, dark theme](docs/screenshots/generate-dark.jpg) | ![Generate, light theme](docs/screenshots/generate-light.jpg) |
| ![Edit, dark theme](docs/screenshots/edit-dark.jpg) | ![History, dark theme](docs/screenshots/history-dark.jpg) |
| ![Models, dark theme](docs/screenshots/models-dark.jpg) | ![Settings, light theme](docs/screenshots/settings-light.jpg) |

> 🖼️ The JPGs are generated with a single command on your machine: `python3 scripts/take-screenshots.py`
> (see [`docs/screenshots/README.md`](docs/screenshots/README.md)).

---

## 🖥️ Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **NVIDIA GPU** | 6 GB VRAM | 12+ GB VRAM |
| **RAM** | 16 GB | 32 GB |
| **Python** | 3.10+ | 3.11 |
| **OS** | Windows 10/11 | Windows 11 |
| **Storage** | ~5 GB (1 small model) | ~70 GB (all) |

> 💡 The app auto-detects your VRAM and tells you which models can run.

---

## 🚀 Installation

### Option A: Simple (recommended)

1. **Download** the project (ZIP or `git clone`)
2. **Extract** the folder
3. Install **Python 3.11** from [python.org](https://www.python.org/downloads/) — ⚠️ check **"Add Python to PATH"**
4. **Double-click `start.bat`**
5. That's it: **Google Chrome opens automatically** on `http://127.0.0.1:7860`
   (if Chrome is not installed, your default browser opens instead)

### Option B: Command line

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src/app.py              # opens Chrome automatically on the right port
python src/app.py --no-browser # ...or no browser at all
python src/app.py --port 7861  # ...or another port
```

---

## 📖 Quick guide (first use)

### 1️⃣ Install the engine
**Models** tab → **"Install engine"** button (downloads `sd-cli`, ~350 MB).

### 2️⃣ Download a model
In the same tab, click **"Download"** on a model.

> **Where to start?** For your first tests, pick **FLUX.1 schnell** (very fast, 4 steps) or **Z-Image** (good quality, fast).

### 3️⃣ Generate an image
**Generate** tab:
1. **Type your description** (prompt) in any language
2. Click **🌐 Translate EN** to translate to English (models work best in English)
3. (Optional) Click **✨ Enrich** to automatically enrich your prompt
4. Choose the **number of images** (1 to 4) and the **format** (square, portrait, landscape…).
   With a source image, select **Original** to preserve its proportions.
5. Click **✨ Generate**

Your images are **automatically saved** in the `output/` folder.

---

### 4️⃣ Edit an image (and combine several)

The **✂️ Edit** tab — available on the models that really do editing:

1. **Pick a model**: Qwen-Image 2.1 / 2.1 Turbo or FLUX.2 / FLUX.3 Klein
   (Qwen needs the **mmproj** — 1.2 GB — offered in one click).
2. **Drop the image to edit**: it becomes “image 1” (the canvas).
3. **Add references** (garment, object, face, style, background…): up to
   **10 images in total**. **Order matters**: use ◀ ▶ to change it.
4. **Describe the change**:
   - **Qwen-Image 2.1 / Turbo** → address images with the `<image1>`, `<image2>`…
     tags (buttons insert them for you):
     `Keep the character and pose in <image1> unchanged, put the shirt from <image2> on them`
   - **FLUX.2 / FLUX.3 Klein** → **no tag**: its text encoder never sees the images, so refer to
     them by position in plain words:
     `Put the product from image 2 on the table in image 1, keep image 1's lighting`
5. **Run**: the result is shown **before / after**.

💡 Every reference adds tokens: short on VRAM? Lower the **reference pixel budget**
(0.5 MP / 0.25 MP) before lowering the number of images.
💡 For classic **img2img** (re-denoise an image with an adjustable strength), stay on the
**Generate** tab → *Starting image* (SD 3.5).

---

## 🧠 Available models (25)

| Model | Speed | License | Best for |
|---|---|---|---|
| **FLUX.1 schnell** | ⚡ 4 steps | Apache 2.0 ✅ | Quick tests |
| **FLUX.2 Klein 4B** | ⚡ 4 steps | Apache 2.0 ✅ | Fast + editing (up to 10 images) |
| **FLUX.2 Klein 9B** | ⚡ 4 steps | Non-commercial | Quality + editing |
| **FLUX.3 Image Klein** | ⚡ 16 steps | Non-commercial | Quality + editing (up to 10 images), readable text, bounding boxes |
| **SD 3.5 Large Turbo** | ⚡ 4 steps | Stability AI ⚠️ | Speed |
| **SD 3.5 Medium** | 30 steps | Stability AI ⚠️ | Lightweight all-rounder |
| **SD 3.5 Large** | 30 steps | Stability AI ⚠️ | High quality |
| **ERNIE-Image Turbo** | ⚡ 8 steps | Apache 2.0 ✅ | Text in images |
| **Z-Image** | 28 steps | Apache 2.0 ✅ | Versatile quality |
| **Qwen-Image 2512** | 30 steps | Apache 2.0 ✅ | Human realism |
| **Qwen-Image 2.1** | 25 steps | Qwen Research ⚠️ | Multi-image editing (×10) + transparency |
| **Qwen-Image 2.1 Turbo** | ⚡ 8 steps, CFG 1 | Qwen Research ⚠️ | Fast generation + multi-image editing |
| **Iris-3B** | 100 steps | Apache 2.0 ✅ | Pixel-space generation |
| **Ideogram 4** | 12 steps | Ideogram | Text rendering |
| **FHDR Uncensored** | 20 steps | Non-commercial | Uncensored |
| **Fibo 2.0 Dev** (GGUF) | 50 steps, CFG 5 | CC BY-NC 4.0 ⚠️ | Generation + reference-image editing |
| **Fibo 2.0 Edit Turbo** (GGUF) | ⚡ 4 steps, CFG 1 | CC BY-NC 4.0 ⚠️ | Fast reference-image editing |
| **MOSS-Image SFT** (GGUF) | 50 steps, CFG 3 | Apache 2.0 ✅ | Standard generation, text in images |
| **MOSS-Image Base** (GGUF) | 50 steps, CFG 3 | Apache 2.0 ✅ | Untuned base, for LoRAs trained on Base |
| **Krea 2 Turbo** (GGUF) | ⚡ 8 steps, CFG 1 | Krea Community ⚠️ | Fast photorealistic rendering |
| **FLUX.1 Dev** (GGUF) | 24 steps | FLUX [dev] ⚠️ | High fidelity (hands, skin, light), img2img + LoRA |
| **FLUX.1 Kontext Dev** (GGUF) | 24 steps | FLUX [dev] ⚠️ | Context editing: change things without breaking identity |
| **Chroma Unlocked** (GGUF) | 26 steps, CFG 4 | Apache 2.0 ✅ | Real negative prompt + organic textures (no "plastic skin") |
| **Chroma1-Radiance** (GGUF) | 26 steps, CFG 4 | Apache 2.0 ✅ | Pixel-space (no VAE): razor-sharp detail, negative prompt |
| **LongCat-Image** (GGUF) | 28 steps, CFG 5 | Apache 2.0 ✅ | Photorealism + exact text in "quotes" |

> ✅ = commercial use allowed · ⚠️ = personal/non-commercial use
>
> All 5 new models **reuse the existing shared dependencies**: FLUX.1 Dev / Kontext use
> `vae_flux`, `clip_l` and `t5xxl`; Chroma uses `vae_flux` + `t5xxl`; Chroma1-Radiance only needs
> `t5xxl`; LongCat-Image reuses `vae_flux` and the **Qwen2.5-VL-7B** encoder (already used by
> Qwen-Image 2512). If you already have FLUX.1 schnell or Qwen-Image, no big extra download is needed.
>
> **Chroma repo notes**: Chroma Unlocked points at the latest upstream v40, which only ships
> **Q4_0** (5.4 GB) and **Q8_0** (9.7 GB); Chroma1-Radiance points at **v0.3** (Q4_K_S → Q8_0),
> as v0.4 only offers BF16 and Q8_0. The `vae_flux` VAE (gated FLUX repo) automatically falls
> back to the public Comfy-Org mirror if the download fails (401).
>
> **Qwen-Image 2.1 Turbo** requires `sd-cli` `c150a6b` or newer (8 steps, CFG 1).
> **FLUX.3 Image Klein** requires `sd-cli` `8cd731e` (Oct 15, 2026) or newer; its GGUFs are converted with that same engine (documented VRAM peaks: 6.8 GB at Q3_K up to 9.8 GB at Q8_0) and it reuses the FLUX.2 VAE and the **Qwen3-VL-4B** encoder (already downloaded with FLUX.2 Klein / Iris-3B).
> **Fibo 2.0** requires a recent `sd-cli` (support added Oct 21, 2026). Its GGUFs come from `molbal/fibo-2.0-GGUF` (Q4_K_M, Q6_K, Q8_0) and use the Qwen3-VL-4B encoder and the FLUX.2 VAE. Editing needs the Qwen3-VL-4B **mmproj** (0.84 GB), downloadable from the Edit tab.
> **MOSS-Image** (Base and SFT) uses the **Qwen3.5-9B** encoder (GGUF, ~5.7 GB), the FLUX.2 VAE and an external `tokenizer.json`, all downloaded automatically. Official quants: `leejet/MOSS-Image-*-GGUF`.
> **Krea 2 Turbo** requires stable-diffusion.cpp `master-721` or newer. Quants from `realrebelai/KREA-2_GGUFs` (TURBO folder), Wan 2.1 VAE and Qwen3-VL-4B encoder.
> **Iris-3B** requires `sd-cli` `f89d9b1` or newer; its weights are about 12 GB, plus the Qwen3-VL-4B encoder. Reinstall the engine from the Models tab if needed.
> Files: `models/diffusion/model.safetensors` (official checkpoint) and `models/llm/Qwen3VL-4B-Instruct-Q4_K_M.gguf`; no VAE.

### 💡 Which model to choose?

- **Just starting?** → **FLUX.1 schnell** (fastest)
- **Best fast quality?** → **FLUX.3 Image Klein** (16 steps), **FLUX.2 Klein 9B**, **Qwen-Image 2512**, or **Qwen-Image 2.1 Turbo**
- **Pixel-space generation?** → **Iris-3B** (100 steps)
- **Image editing?** → **Edit** tab: **Qwen-Image 2.1 / 2.1 Turbo** (semantic editing, up to 10
  images) or **FLUX.2 / FLUX.3 Klein** (editing, images addressed by position, up to 10 images)
- **Classic img2img?** → **SD 3.5 Medium/Large** (strength control)
- **Readable text in image?** → **ERNIE-Image Turbo**, **Ideogram 4** or **LongCat-Image**
- **Edit without breaking identity?** → **FLUX.1 Kontext Dev** (change text, light, scenery)
- **Realistic hands & textures?** → **Chroma Unlocked** (true negative prompt) + **ADetailer**
- **Smallest?** → **SD 3.5 Medium** (~2 GB)

---

## ✨ Quality, Detail & Upscaling (one click, explained in-app)

The **Generate** and **Edit** pages include a collapsible "✨ Quality, Detail & Upscaling"
section with a clear explanation for every option:

| Option | Effect | Where |
|---|---|---|
| **🔍 ×4 Upscaling** | Dedicated super-resolution (1024→4096 px): **RealESRGAN ×4** (photo), **4× Nomos2 MoSR** (natural textures), **4× UltraSharp** (details & sharpness), **4× UltraMix Balanced** (softer UltraSharp), **4× Remacri** (natural photo grain), **RealESRGAN Anime 6B** (illustration) | During generation **or** afterwards: one-click "🔍 Upscale ×4" button on every result and in History |
| **🏗️ Hires Fix (2 passes)** | Pass 1 composes; pass 2 gently re-details at high resolution (up to ×2, ≤ ~2048 px) | Pure generation, img2img-capable models (SD 3.5, FLUX.1 Dev, Chroma) |
| **🙂 ADetailer** | YOLOv8 detector that finds **faces/hands** and automatically re-details them — also one-click on any existing image | Generate & Edit pages (after installing the detector in Models) |
| **⚡ Mini-VAE (TAE)** | Near-instant final decode for Qwen-Image models (~2 MB) | Quality → ⚡ Performance |
| **⚡ SageAttention CUDA** | Faster attention, less VRAM on NVIDIA GPUs (SM80+, recent drivers) — no Python install | Quality → ⚡ Performance |
| **📡 Live preview** | « LIVE » window: watch the image denoise step by step (**on by default, « Auto »**: Mini-VAE if installed, else latent projection) | Quality → ⚡ Performance |
| **🎭 Faithful Face (PuLID)** | Keeps a reference person's face (FLUX.1 Schnell/Dev/FHDR only) — see `docs/PULID_FR.md` (French) | Quality → 🎭 Faithful face |
| **🩹 Restore ×2 (SeedVR2)** | Diffusion-based detail reconstruction + 2× resolution for existing images (~6.8 GB weights, ~10 GB VRAM) | One-click on every result and in History |
| **⬆️ PiD ×4** | **Generative** super-resolution ×4 (1024→4096, 4 steps), prompt-conditioned — rebuilds plausible detail instead of smoothing | One-click "⬆️ PiD ×4" on every result and in History — see `docs/PID_FR.md` (French). **NSCLv1 non-commercial license** |
| **🔀 Vary (subtle / strong)** | Midjourney-style variation: re-generates the image via img2img with a **new seed** — subtle = strength 0.35 (light touch), strong = strength 0.75 (bold); prompt and settings are copied from the source image | « 🔀 Vary » buttons on every result / in History (img2img-capable models only: SD 3.5, FLUX.1 Dev, Chroma) |
On the **Générer** (Generate) page, a « ✨ Midjourney style » section provides **honest local
approximations** of Midjourney's aesthetic controls — everything stays editable afterwards:

| Option | Approximates | Actual effect |
|---|---|---|
| **🎭 Style pre-prompts** | 14 complete styles (🎬 Anamorphic cinema, 📷 Portra 400, 🖼️ Impressionism, 🎨 Watercolor, ✏️ Ink & charcoal, 🌸 Ukiyo-e, 🧸 3D Blender, 👾 Pixel art, 🔺 Low-poly, 🎞️ Film noir, ⬜ Flat/vector, 🎭 Mucha, 🌀 Dalí, 📖 Children's book) | « 🎭 Styles & renders » section of the pre-prompt dropdown (Generate) and « 🎭 Styles — keep the subject » (Edit, per-model reference token) |
| **Quick styles** | 12 chips (🎬 Cinema, 📷 Photo, 🖼️ Oil, 🎨 Watercolor, ⛩️ Anime, 👾 Pixel art, 🔺 Low-poly, 🌆 Cyberpunk, ⚙️ Steampunk, ⬜ Minimal, 💡 Neon, 🕶️ Noir) | Each click adds/removes a **visible** suffix in the prompt |
| **Stylisation (0–1000)** | ≈ « stylize », 100 = preset unchanged | Adjusts **Steps** and **CFG** on top of the active preset |
| **Weirdness (0–3000)** | ≈ « weird », 0 = Quality settings untouched | 0 → no-op; 1–999 → Euler A + Karras; 1000–1999 → DPM++ 2M + Beta; 2000–3000 → LCM + SGM Uniform |
| **Chaos (0–100)** | ≈ « chaos », 0 = consecutive seeds | Above 0: fixed seed ignored, **independent random seed per image** in the batch |

| **🎛️ Sampler / Scheduler** | Choose the sampler (euler, heun, dpm++2m, euler_a, lcm) and scheduler (karras, beta, exponential…) | Generate & Edit pages |
| **⚙️ VAE Tiling** | Tiled VAE decode — saves VRAM on large images | Expert settings |
| **⚙️ SLG (Skip Layer Guidance)** | Better prompt adherence on DiT models (recommended: 3) | Expert settings |

> 💡 **Live progress** : on the **History** page, every operation launched on an existing image
> ("🙂 Réparer" / repair, "🩹 Restaurer ×2", "🔍 Agrandir ×4", "⬆️ PiD ×4") shows a **real-time
> progress banner**: running or **queued** operation (with position), percentage, step x/y,
> elapsed time, latest sd-cli log line, and the **full error message** on failure —
> no more buttons stuck on "running…" with zero feedback.

Upscaler models (17–64 MB) and ADetailer detectors (6–22 MB) download in **one click** from the
dedicated sections at the bottom of the **Models** page.

> 💡 **Live preview — how it works**: sd-cli writes one preview frame every N steps
> (`--preview-interval`) into `.preview_cache/`; the UI polls it into the « LIVE » window above the
> results (Generate and Edit pages). Modes: **Auto** (default) = Mini-VAE if one is installed for the
> current model, else **proj** (latent projection, instant, no file needed). Projection is known for
> SD1.x/XL, SD 3.5, FLUX (Schnell/Dev/FHDR/Chroma/Kontext), FLUX.2 and Qwen-Image-2.1. On
> **Qwen-Image 2512**, only the Mini-VAE (Models → ⚡ Fast VAE) produces a preview. The old « vae »
> mode never decoded with the real VAE in this binary (the preview runner is always the Mini-VAE) —
> it is treated as « tae ». With the Mini-VAE, the **final** decode still uses the real VAE
> (`--taesd-preview-only`). If a model has neither a known projection nor a TAE, no preview frames are
> written: expected — the final image is unaffected.

> ⚠️ **New upscalers & licenses** — **4× UltraSharp**, **4× UltraMix Balanced** and **4× Remacri**
> are released under **CC-BY-NC-SA-4.0** (Kim2091 for the first two; Remacri by FoolhardyVEVO,
> shipped here as a GGUF converted by stable-diffusion.cpp itself, license unchanged):
> **private / non-commercial use only**. For commercial use, prefer **RealESRGAN ×4**
> (BSD-3-Clause) or **4× Nomos2 MoSR** (CC-BY-4.0). These three are recent additions and have
> **not been tested on a real GPU** — please report any issue.

---
---

## ⚠️ Gated models

Some models require a **free Hugging Face token**:

**FHDR, FLUX.2 Klein 9B, SD 3.5 (Medium/Large/Turbo)**

1. Create an account on [huggingface.co](https://huggingface.co/join)
2. Create a token: [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → type **Read**
3. Go to the model page and **accept the terms**
4. In the app → **Settings** tab → paste your token → **Save**

---

## 🌟 Features

| Feature | Description |
|---|---|
| 🖼️ **Generation** | 1 to 4 images per batch, 9 aspect ratios (1:1, 3:4, 4:3, 9:16, 16:9, 2:3, 4:5, 21:9, 9:21) + original aspect ratio when editing |
| ✂️ **Edit studio** | **Edit** tab: 1 canvas + up to **10 reference images**, reordering, before/after comparison |
| 🗂️ **Prompt batch** | One line per prompt (16 max), queued back-to-back |
| ⚔️ **Seed duel / Model compare** | Same prompt on 2 consecutive seeds or on 2 models |
| 📥 **PNG-embedded metadata** | Drag & drop any generated PNG: prompt, seed, model… restored instantly |
| ⬆️ **PiD ×4** | Generative super-resolution (FLUX.1 / FLUX.2 / Qwen-Image), 4 steps, 4096×4096 output |
| ✨ **Midjourney-style options** | Quick style chips (visible prompt suffixes), Stylisation (0–1000, adjusts steps/CFG), Weirdness (0–3000, adjusts sampler/scheduler) and Chaos (0–100, independent seeds per image in a batch) — honest local approximations, all controls stay editable | Générer tab, section « ✨ Style Midjourney » |
| 🌗 **Light / dark theme** | ☀️/🌙 toggle in the top bar — remembered in the browser | All pages |
| 🌐 **Translation** | Translates your prompt (FR, ES…) to English |
| ✨ **Enrichment** | An LLM enriches your prompt (style, lighting, composition…) |
| 📊 **Statistics** | Generation time per model, most used model, etc. |
| 📚 **History** | All your images with their prompt, reusable in 1 click |
| 💾 **Auto-save** | Images saved in `output/` |
| 🚫 **Negative prompt** | Pre-filled automatically (editable) |
| 📄 **Licenses** | Shown for each model |
| 🔗 **HF links** | Direct access to each model's page |

---

## 📁 Project structure

```
local-image-studio/
├── start.bat              ← ⭐ Double-click to launch (Windows)
├── update.bat             ← 🔄 Update (git clone or ZIP): branch picker + refreshes .venv
├── README.md              ← Documentation principale (FR)
├── README_EN.md           ← This document (EN)
├── requirements.txt       ← Python dependencies
├── LICENSE
│
├── src/                   ← Application code (nothing to touch here)
│   ├── app.py             ← Web server (Flask) + startup options
│   ├── browser_launch.py  ← Open Chrome automatically on startup
│   ├── engine.py          ← sd-cli engine + downloads + task queue
│   ├── registry.py        ← 25 model definitions + ×4 upscalers + ADetailer detectors
│   ├── prompt_enhancer.py ← Prompt boost & translation (LLM)
│   ├── gpu_info.py        ← VRAM detection
│   ├── db.py              ← History & statistics
│   ├── config.py          ← Path configuration
│   ├── templates/         ← HTML pages (generate.html, edit.html, …)
│   └── static/            ← CSS + JavaScript (generate.js, edit.js, quality.js, …)
│
├── docs/                  ← Documentation
│   ├── ADD_MODEL_FR.md    ← Comment ajouter un modèle (FR)
│   ├── ADD_MODEL_EN.md    ← How to add a model (EN)
│   ├── PULID_FR.md        ← PuLID: portrait fingerprints & install (FR)
│   └── PID_FR.md          ← PiD: generative ×4 super-resolution (FR)
├── tests/                 ← Unit tests (python -m unittest discover -s tests)
│
└── (created automatically on first launch)
    ├── .venv/             ← Isolated Python environment (created by start.bat)
    ├── bin/               ← sd-cli.exe (auto-downloaded)
    ├── models/            ← GGUF/safetensors + VAE + encoders + upscalers (auto-downloaded)
    ├── source_images/     ← Your input images (img2img / editing)
    ├── output/            ← Your generated images
    ├── history.db         ← History (SQLite database)
    └── settings.json      ← Your settings
```

---

## ➕ Add a model

The app is designed to be **extensible**. You can add GGUF models supported by
`stable-diffusion.cpp`, as well as some other formats accepted by the engine,
such as Iris-3B's safetensors checkpoint.

📖 **Full guide: [docs/ADD_MODEL_EN.md](./docs/ADD_MODEL_EN.md)**

In short: edit `src/registry.py` → add an entry to the `MODELS` dictionary → restart.

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---|---|
| **Buttons don't work** | `Ctrl+F5` in your browser (clear cache) |
| **"Engine not installed"** | Models tab → Install engine |
| **Slow generation** | Use Q4_K_M, or a "Turbo"/"schnell" model |
| **White image** | Make sure you have the latest code version |
| **"token required"** | Add your HF token in Settings |
| **Enrichment unavailable** | Install Microsoft [C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/), then rerun `start.bat` |
| **Low VRAM** | Use Q4_K_M, reduce resolution |
| **Python not found** | Reinstall Python 3.11 checking "Add to PATH" |
| **The browser does not open** | Is Chrome installed? Otherwise your default browser opens. Also check **Settings → Open Chrome at startup**, or run `python src/app.py --no-browser` to disable it entirely |
| **The tab opens before the server is ready** | Nothing to do: the page loads as soon as the port is listening (opening waits for the server) |
| **Port 7860 already in use** | Run `python src/app.py --port 7861` (the tab opens on the right port) |

---

## 🔧 How it works

The app drives **`sd-cli.exe`** (the C/C++ engine from
[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) by leejet).
This engine runs FLUX, Qwen-Image, Stable Diffusion 3.5, Z-Image, ERNIE,
Ideogram 4 and other **GGUF** models; Iris-3B uses its **safetensors** weights
(without a VAE).

The web interface (Flask) automatically builds the correct command line for each
model, manages downloads, and displays everything behind a simple page.

**Enrichment and translation** use a small LLM (Qwen3-4B, already downloaded as
a dependency of Z-Image/FLUX.2) via `llama-cpp-python` on CPU.

---

## 📜 License

This project is open-source. The models used have their own licenses (see the
Models tab in the app). Always check the model's license before using generated
images commercially.

---

<div align="center">

**Made with ❤️ to make AI image generation accessible to everyone.**

[Report a bug](https://github.com/) · [Add a model](./docs/ADD_MODEL_EN.md) · [Français](./README.md)

</div>
