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
2. Open http://127.0.0.1:7860
3. Download a model → Write a prompt → Generate!
```

**No image, no prompt ever leaves your computer.** Everything runs on your local GPU.

---

## 🖥️ Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **NVIDIA GPU** | 6 GB VRAM | 12+ GB VRAM |
| **RAM** | 16 GB | 32 GB |
| **Python** | 3.10+ | 3.11 |
| **OS** | Windows 10/11 | Windows 11 |
| **Storage** | ~5 GB (1 model) | ~50 GB (all) |

> 💡 The app auto-detects your VRAM and tells you which models can run.

---

## 🚀 Installation

### Option A: Simple (recommended)

1. **Download** the project (ZIP or `git clone`)
2. **Extract** the folder
3. Install **Python 3.11** from [python.org](https://www.python.org/downloads/) — ⚠️ check **"Add Python to PATH"**
4. **Double-click `start.bat`**
5. Open **http://127.0.0.1:7860** in your browser

### Option B: Command line

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
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
4. Choose the **number of images** (1 to 4) and the **format** (square, portrait, landscape…, **🖼 Original** = the uploaded image's format, or **✂ a custom size**)
5. Click **✨ Generate**

Your images are **automatically saved** in the `output/` folder.

---

### 4️⃣ Edit an image (img2img / editing)

1. Expand **"Source image (img2img / editing)"** and upload your image (PNG, JPG, WEBP)
2. Describe the change you want: *"add sunglasses"*, *"make it sunset"*, *"watercolor style"*…
3. Pick a model that can edit: **Qwen-Image 2.1** (semantic editing),
   **FLUX.2 Klein** (reference editing) or **SD 3.5** (classic img2img, *Strength* setting)
4. Click **✨ Generate**

#### 📐 Choosing the output format

The **Format** field offers three ways to set the size of the generated image:

| Choice | Result |
|---|---|
| **1:1 · 3:4 · 4:3 · 9:16 · 16:9** | Preset formats (1024 px base) |
| **🖼 Original** | **Keeps the uploaded image's format** — selected automatically on upload |
| **✂ Custom** | Any width × height (multiple of 16, from 256 to 2048 px) |

**🖼 Original** preserves the file's framing exactly and computes the output at ~1 MP:
that's the models' native resolution, so generation stays fast and fits in VRAM.
*e.g. a 1920×1080 photo → 1360×768, the 16:9 framing is preserved*

The **"Exact file size"** checkbox (under the chip) uses the original pixel count instead,
capped at 2048 px / ~4 MP so VRAM isn't exhausted — slower and heavier.
*e.g. 1920×1080 → 1920×1088*

> 💡 Dimensions are always aligned to a multiple of **16 px** (required by the models'
> VAE/patch sizes). The format actually used is shown above the results and stored in history.

---

## 🧠 Available models (12)

| Model | Speed | License | Best for |
|---|---|---|---|
| **FLUX.1 schnell** | ⚡ 4 steps | Apache 2.0 ✅ | Quick tests |
| **FLUX.2 Klein 4B** | ⚡ 4 steps | Apache 2.0 ✅ | Fast + quality |
| **FLUX.2 Klein 9B** | ⚡ 4 steps | Non-commercial | Top quality, fast |
| **SD 3.5 Large Turbo** | ⚡ 4 steps | Stability AI ⚠️ | Speed |
| **SD 3.5 Medium** | 30 steps | Stability AI ⚠️ | Lightweight all-rounder |
| **SD 3.5 Large** | 30 steps | Stability AI ⚠️ | High quality |
| **ERNIE-Image Turbo** | ⚡ 8 steps | Apache 2.0 ✅ | Text in images |
| **Z-Image** | 28 steps | Apache 2.0 ✅ | Versatile quality |
| **Qwen-Image 2512** | 30 steps | Apache 2.0 ✅ | Human realism |
| **Qwen-Image 2.1** | 25 steps | Qwen Research ⚠️ | Editing + transparency |
| **FLUX.2 Klein 4B** | ⚡ 4 steps | Apache 2.0 ✅ | Fast + editing |
| **FLUX.2 Klein 9B** | ⚡ 4 steps | Non-commercial | Quality + editing |
| **Ideogram 4** | 12 steps | Ideogram | Text rendering |
| **FHDR Uncensored** | 20 steps | Non-commercial | Uncensored |

> ✅ = commercial use allowed · ⚠️ = personal/non-commercial use

### 💡 Which model to choose?

- **Just starting?** → **FLUX.1 schnell** (fastest)
- **Best fast quality?** → **FLUX.2 Klein 9B** or **Qwen-Image 2512**
- **Image editing?** → **Qwen-Image 2.1** (advanced editing) or **FLUX.2 Klein** (fast editing)
- **Classic img2img?** → **SD 3.5 Medium/Large** (strength control)
- **Readable text in image?** → **ERNIE-Image Turbo** or **Ideogram 4**
- **Smallest?** → **SD 3.5 Medium** (~2 GB)

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
| 🖼️ **Generation** | 1 to 4 images per batch, 5 ratios + "Original" chip (uploaded file's format) + custom size |
| 🌐 **Translation** | Translates your prompt (FR, ES…) to English |
| ✨ **Enrichment** | An LLM enriches your prompt (style, lighting, composition…) |
| 📊 **Statistics** | Generation time per model, most used model, etc. |
| 📚 **History** | All your images with their prompt, reusable in 1 click |
| 💾 **Auto-save** | Images saved in `output/` |
| 🚫 **Negative prompt** | Pre-filled automatically (editable) |
| 📐 **Format preserved** | In img2img/editing, the output keeps the uploaded file's framing (or its exact pixels) |
| 📄 **Licenses** | Shown for each model |
| 🔗 **HF links** | Direct access to each model's page |

---

## 📁 Project structure

```
local-image-studio/
├── start.bat              ← Double-click to launch
├── app.py                 ← Web server (Flask)
├── engine.py              ← sd-cli engine + downloads
├── registry.py            ← 11 model definitions
├── prompt_enhancer.py     ← Enrichment & translation (LLM)
├── image_utils.py         ← Image dimensions + output format (img2img)
├── gpu_info.py            ← VRAM detection
├── db.py                  ← History & statistics
├── config.py              ← Path configuration
├── requirements.txt       ← Python dependencies
├── templates/             ← HTML pages
├── static/                ← CSS + JavaScript
├── docs/                  ← Documentation
│   ├── ADD_MODEL_FR.md    ← How to add a model (FR)
│   └── ADD_MODEL_EN.md    ← How to add a model (EN)
│
├── tests/                 ← Tests (python -m unittest discover -s tests)
├── bin/                   ← sd-cli.exe (auto-downloaded)
├── models/                ← GGUF + VAE + encoders (auto-downloaded)
└── output/                ← Your generated images
```

---

## ➕ Add a model

The app is designed to be **extensible**. You can add any GGUF model compatible
with `stable-diffusion.cpp`.

📖 **Full guide: [docs/ADD_MODEL_EN.md](./docs/ADD_MODEL_EN.md)**

In short: edit `registry.py` → add an entry to the `MODELS` dictionary → restart.

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

---

## 🔧 How it works

The app drives **`sd-cli.exe`** (the C/C++ engine from
[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) by leejet).
This engine runs FLUX, Qwen-Image, Stable Diffusion 3.5, Z-Image, ERNIE,
Ideogram 4 and more in **GGUF** (quantized) format.

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
