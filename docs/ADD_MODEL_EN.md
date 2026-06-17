# ➕ How to add a model manually

This guide explains how to add **any compatible GGUF model** to the application
(runs on `stable-diffusion.cpp`).

---

## Step 1: Check compatibility

The model must:
1. Be in **GGUF** format (`.gguf`)
2. Be supported by `stable-diffusion.cpp`. Check the official list:
   **https://github.com/leejet/stable-diffusion.cpp** → *Supported models* section

Supported architectures: `flux`, `flux2`, `sd3`, `zimage`, `ernie`, `ideogram`,
`qwen_image`, `wan`, `chroma`, `hidream`, `anima`, etc.

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
| `qwen_image` | `qwen25vl_7b`                      | `vae_qwen`    | Qwen-Image |
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
Wan-type architectures (ERNIE, Qwen-Image) need `--flow-shift 3`.
This is handled automatically if `arch` is `ernie` or `qwen_image`.

---

## Step 6: Test

1. Restart the app (`start.bat`).
2. Go to the **Models** tab → your model appears.
3. Click **Download**, then test generation.

If generation fails, check the **Log** panel on the Generate page
("show/hide" button) for the full `sd-cli` output.
