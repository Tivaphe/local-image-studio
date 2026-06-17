# ➕ Comment ajouter un modèle manuellement

Ce guide explique comment ajouter **n'importe quel modèle GGUF compatible** avec
`stable-diffusion.cpp` (le moteur de cette application).

---

## Étape 1 : Vérifier la compatibilité

Le modèle doit :
1. Être au format **GGUF** (`.gguf`)
2. Être supporté par `stable-diffusion.cpp`. Consultez la liste officielle :
   **https://github.com/leejet/stable-diffusion.cpp** → section *Supported models*

Les architectures actuellement supportées : `flux`, `flux2`, `sd3`, `zimage`,
`ernie`, `ideogram`, `qwen_image`, `wan`, `chroma`, `hidream`, `anima`, etc.

---

## Étape 2 : Ouvrir `registry.py`

Cherchez le dictionnaire `MODELS` (vers la ligne 70). Ajoutez une nouvelle entrée
en copiant le modèle d'un modèle existant qui a la **même architecture**.

### Exemple : ajouter un modèle FLUX.1-dev

```python
"mon-flux-dev": {
    "name": "Mon FLUX.1-dev",              # Nom affiché dans l'interface
    "arch": "flux",                        # Architecture (voir tableau ci-dessous)
    "repo": "unsloth/FLUX.1-dev-GGUF",     # Dépôt Hugging Face
    "quants": ["Q4_K_M", "Q5_K_M", "Q6_K"],# Niveaux proposés (entre Q4 et Q6)
    "default_quant": "Q5_K_M",             # Quant sélectionnée par défaut
    "file_for_quant": {                    # Nom EXACT du fichier GGUF
        "Q4_K_M": "flux1-dev-Q4_K_M.gguf",
        "Q5_K_M": "flux1-dev-Q5_K_M.gguf",
        "Q6_K":   "flux1-dev-Q6_K.gguf",
    },
    "size_gb": {"Q4_K_M": 6.9, "Q5_K_M": 8.4, "Q6_K": 9.8},  # Taille approximative
    "deps": ["vae_flux", "clip_l", "t5xxl"],                   # Dépendances partagées
    "supports_neg": True,     # Le modèle gère-t-il un prompt négatif ?
    "needs_token": False,     # Le dépôt est-il protégé (gated) ?
    "license": "FLUX.1-dev Non-Commercial",
    "hf_url": "https://huggingface.co/unsloth/FLUX.1-dev-GGUF",
    "vram_min_gb": 6,         # VRAM minimum recommandée
    "desc": "Description courte affichée dans l'interface.",
    "defaults": {"steps": 20, "cfg": 3.5, "sampler": "euler"},
    "min_steps": 8, "max_steps": 40,
},
```

---

## Étape 3 : Choisir la bonne architecture (`arch`)

| `arch`       | Encodeurs de texte requis          | VAE           | Remarques |
|---|---|---|---|
| `flux`       | `clip_l` + `t5xxl`                 | `vae_flux`    | FLUX.1 schnell/dev, FHDR |
| `flux2`      | `qwen3_4b` ou `qwen3_8b`           | `vae_flux2`   | FLUX.2 Klein 4B/9B |
| `sd3`        | `clip_l` + `clip_g` + `t5xxl`     | `vae_sd3`     | Stable Diffusion 3.5 |
| `zimage`     | `qwen3_4b`                         | `vae_flux`    | Z-Image |
| `ernie`      | `ministral_3b`                     | `vae_flux2`   | ERNIE-Image Turbo |
| `qwen_image` | `qwen25vl_7b`                      | `vae_qwen`    | Qwen-Image |
| `ideogram`   | `qwen3vl_8b`                       | `vae_flux2`   | Ideogram 4 (needs uncond) |

> **Astuce** : trouvez la doc officielle du modèle sur
> https://github.com/leejet/stable-diffusion.cpp/tree/master/docs
> pour connaître les arguments exacts et les dépendances.

---

## Étape 4 : Réutiliser les dépendances existantes

Les VAE et encodeurs de texte sont **partagés** entre modèles. Regardez le
dictionnaire `DEPS` dans `registry.py`. Si votre modèle utilise un encodeur
déjà présent (ex: `clip_l`, `t5xxl`, `qwen3_4b`...), référencez-le simplement
dans `"deps": [...]`. Il ne sera téléchargé qu'une fois.

Si le modèle a besoin d'un **nouvel** encodeur, ajoutez-le dans `DEPS` :

```python
"mon_nouvel_encodeur": {
    "type": "exact",                          # "exact" = fichier précis, "gguf" = résolution auto
    "repo": "le-depot/hugging-face",
    "filename": "fichier.safetensors",        # pour type="exact"
    "dest": LLM_DIR / "fichier.safetensors",  # dossier de destination
    "size_gb": 2.0,
},
```

---

## Étape 5 : Cas particuliers

### Modèle avec `--diffusion-fa` cassé (image blanche)
Certains modèles produisent une image blanche avec Flash Attention.
Ajoutez `"diffusion_fa": False` dans la définition du modèle.

### Modèle avec modèle uncond (Ideogram)
Ajoutez un champ `uncond_file_for_quant` comme Ideogram 4.

### Modèle avec paramètre `--flow-shift`
Les architectures type Wan (ERNIE, Qwen-Image) nécessitent `--flow-shift 3`.
C'est géré automatiquement si `arch` est `ernie` ou `qwen_image`.
Pour d'autres architectures, ajoutez la logique dans `build_command()`.

---

## Étape 6 : Tester

1. Redémarrez l'application (`start.bat`).
2. Allez dans l'onglet **Modèles** → votre modèle apparaît.
3. Cliquez **Télécharger**, puis testez la génération.

Si la génération échoue, consultez le **Journal** (bouton "afficher/masquer" sur la
page Générer) qui affiche la sortie complète de `sd-cli`.
