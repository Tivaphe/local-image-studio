# ➕ How to add a model manually

This guide explains how to add **a model supported by `stable-diffusion.cpp`**
(the engine used by this application), as GGUF or another format supported by its
architecture.

---

## Step 1: Check compatibility

The model must:
1. Be in **GGUF** format (`.gguf`) or another format supported by its architecture (`.safetensors` for Iris-3B)
2. Be supported by `stable-diffusion.cpp`. Check the official list:
   **https://github.com/leejet/stable-diffusion.cpp** → *Supported models* section

Supported architectures: `flux`, `flux2`, `sd3`, `zimage`, `ernie`, `ideogram`,
`qwen_image`, `iris`, `wan`, `chroma`, `hidream`, `anima`, etc.

---

## Step 2: Open `registry.py`

Find the `MODELS` dictionary (around line 70). Add a new entry by copying
an existing model that has the **same architecture**.

### Example: add a FLUX.1-dev model

```python
"my-flux-dev": {
    "name": "My FLUX.1-dev",               # Display name in the UI
    "arch": "flux",                        # Architecture (see table below)
    "repo": "unsloth/FLUX.1-dev-GGUF",     # Hugging Face repo
    "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],# Available quants (Q4–Q6)
    "default_quant": "Q5_K_M",             # Default selected quant
    "file_for_quant": {                    # EXACT GGUF filenames
        "Q4_K_M": "flux1-dev-Q4_K_M.gguf",
        "Q5_K_M": "flux1-dev-Q5_K_M.gguf",
        "Q6_K":   "flux1-dev-Q6_K.gguf",
    },
    "size_gb": {"Q4_K_M": 6.9, "Q5_K_M": 8.4, "Q6_K": 9.8},
    "deps": ["vae_flux", "clip_l", "t5xxl"],
    "supports_neg": True,     # Does it support negative prompts?
    "needs_token": False,     # Is the repo gated?
    "license": "FLUX.1-dev Non-Commercial",
    "hf_url": "https://huggingface.co/unsloth/FLUX.1-dev-GGUF",
    "vram_min_gb": 6,
    "desc": "Short description shown in the UI.",
    "defaults": {"steps": 20, "cfg": 3.5, "sampler": "euler"},
    "min_steps": 8, "max_steps": 40,
},
```

---

## Step 3: Choose the right architecture (`arch`)

| `arch`       | Text encoders required              | VAE           | Notes |
|---|---|---|---|
| `flux`       | `clip_l` + `t5xxl`                 | `vae_flux`    | FLUX.1 schnell/dev, FHDR |
| `flux2`      | `qwen3_4b` or `qwen3_8b`           | `vae_flux2`   | FLUX.2 Klein 4B/9B |
| `sd3`        | `clip_l` + `clip_g` + `t5xxl`     | `vae_sd3`     | Stable Diffusion 3.5 |
| `zimage`     | `qwen3_4b`                         | `vae_flux`    | Z-Image |
| `ernie`      | `ministral_3b`                     | `vae_flux2`   | ERNIE-Image Turbo |
| `qwen_image` | `qwen25vl_7b` (standard) / `qwen3vl_8b` (2.1/Turbo) | `vae_qwen` / `vae_qwen_21` | Qwen-Image |
| `iris` | `qwen3vl_4b` | None | Iris-3B (safetensors) |
| `ideogram`   | `qwen3vl_8b`                       | `vae_flux2`   | Ideogram 4 (needs uncond) |

> **Tip**: find the model's official doc at
> https://github.com/leejet/stable-diffusion.cpp/tree/master/docs
> for exact arguments and dependencies.

---

## Step 4: Reuse existing dependencies

VAE and text encoders are **shared** between models. Check the `DEPS` dictionary
in `registry.py`. If your model uses an existing encoder (e.g. `clip_l`, `t5xxl`...),
just reference it in `"deps": [...]`. It will only be downloaded once.

To add a **new** encoder, add it to `DEPS`:

```python
"my_new_encoder": {
    "type": "exact",                          # "exact" = specific file, "gguf" = auto-resolve
    "repo": "the/hf-repo",
    "filename": "file.safetensors",
    "dest": LLM_DIR / "file.safetensors",
    "size_gb": 2.0,
},
```

---

## Step 5: Special cases

### Model with broken `--diffusion-fa` (white image)
Some models produce a blank image with Flash Attention.
Add `"diffusion_fa": False` to the model definition.

### Model with uncond model (Ideogram)
Add an `uncond_file_for_quant` field like Ideogram 4.

### Model needing `--flow-shift`
ERNIE and Qwen-Image 2512 need `--flow-shift 3`; this does not apply to every Qwen-Image model.
`build_command()` handles it for ERNIE and Qwen-Image 2512.

### Model with fixed steps and custom sigmas
Qwen-Image-2.1 Turbo requires the exact `--sigmas` list from its model card, 8 steps, and CFG 1.
The required `stable-diffusion.cpp` fix is included in builds from October 6, 2026 onward.
Add the fixed values to the registry and pass `--sigmas` from `build_command()`.

---

## Step 6: Declare image input capabilities (editing / img2img)

`sd-cli` takes images in two very different ways:

| Mode | Flag | Behaviour |
|---|---|---|
| `ref` | `-r` / `--ref-image` | **Repeatable, once per image** (documented as “can be used multiple times”). This is the mode of semantic editing models: the image is not “denoised”, it is context. |
| `init` | `-i` / `--init-img` | A **single** starting image + `--strength` (classic img2img). |

A model declares what it accepts in `registry.py`:

```python
"my-edit-model": {
    ...
    "supports_ref_images": True,      # listed by the Edit studio (/edit page)
    "input_modes": ["ref"],           # "ref", "init", or both
    "max_ref_images": 10,             # canvas + references (UI guard rail)
    "ref_tag_syntax": "<image{n}>",   # or None when the model has no syntax
    "ref_needs_vlm": True,            # is a mmproj required for references?
    "ref_hint": "How to address the images…",
    "ref_examples": ["Keep the subject in <image1>, …"],
},
```

Rules worth knowing (checked against the engine, `docs/edit.md` and
`docs/qwen_image_2.1.md` of stable-diffusion.cpp):

- **`pass_to_vlm` ⇒ mmproj mandatory.** The auto-detected reference preset
  (`--ref-image-args`) feeds the images to the text encoder for `qwen`
  (`pass_to_vlm=true`): without `--llm_vision` the engine refuses/ignores them.
  For `flux2` (`pass_to_vlm=false`) references only reach the DiT: **no mmproj**,
  and therefore **no tag** — the model addresses images by position in plain words.
- **The order of `-r` defines the indexes.** `ref_index_mode=increase` (already the
  default of the `qwen` and `flux2` presets) numbers images from 1: the first one is
  the edited canvas.
- **The engine does not cap the number of images**, but every reference adds tokens
  (VRAM + time). `max_ref_images` protects the user; the fine-grained lever is
  `--ref-image-args "vae_input_max_pixels=524288"` (exposed in the UI as the
  “reference pixel budget”).
- **`--strength` has no effect in `ref` mode**: don't send it then.
- A model **not** declared here (FLUX.1 schnell, Z-Image, ERNIE, Ideogram 4,
  Iris-3B…) accepts no reference: the app won't pass the argument.
- `--mask` (inpainting) only works with dedicated “inpaint” weights
  (e.g. FLUX.1-Fill-dev): no point exposing it for the current registry models.

On the app side these fields are served by `/api/models`, validated by
`registry.check_images_input()` (count, mode, duplicates) and end up in
`registry.build_command(ref_images=[...], input_mode=…, ref_max_pixels=…)`.

---

## Step 7: Test

1. Restart the app (`start.bat`).
2. Go to the **Models** tab → your model appears.
3. Click **Download**, then test generation.

If generation fails, check the **Log** panel on the Generate page
(“show/hide” button) for the full `sd-cli` output.
