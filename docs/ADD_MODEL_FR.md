# ➕ Comment ajouter un modèle manuellement

Ce guide explique comment ajouter **un modèle compatible** avec `stable-diffusion.cpp`
(le moteur de cette application), en GGUF ou dans un autre format pris en charge par
son architecture.

---

## Étape 1 : Vérifier la compatibilité

Le modèle doit :
1. Être au format **GGUF** (`.gguf`) ou un autre format accepté par son architecture (`.safetensors` pour Iris-3B)
2. Être supporté par `stable-diffusion.cpp`. Consultez la liste officielle :
   **https://github.com/leejet/stable-diffusion.cpp** → section *Supported models*

Les architectures actuellement supportées : `flux`, `flux2`, `sd3`, `zimage`,
`ernie`, `ideogram`, `qwen_image`, `iris`, `wan`, `chroma`, `hidream`, `anima`, etc.

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
| `qwen_image` | `qwen25vl_7b` (standard) / `qwen3vl_8b` (2.1/Turbo) | `vae_qwen` / `vae_qwen_21` | Qwen-Image |
| `iris` | `qwen3vl_4b` | Aucun | Iris-3B (safetensors) |
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
ERNIE et Qwen-Image 2512 nécessitent `--flow-shift 3`; ce n'est pas universel à tous les modèles Qwen-Image.
C'est géré automatiquement pour ERNIE et Qwen-Image 2512 dans `build_command()`.

### Modèle avec sigmas et nombre d'étapes fixes
Qwen-Image-2.1 Turbo exige la liste `--sigmas` fournie sur sa fiche et exactement 8 étapes avec CFG 1.
Le correctif de `stable-diffusion.cpp` nécessaire aux sigmas personnalisés est inclus dans les builds du 6 octobre 2026 ou plus récents.
Ajoutez les valeurs fixes au registre et transmettez `--sigmas` depuis `build_command()`.

---

## Étape 6 : Déclarer les capacités d'entrée image (édition / img2img)

`sd-cli` accepte les images de deux façons très différentes :

| Mode | Flag | Comportement |
|---|---|---|
| `ref` | `-r` / `--ref-image` | **Répétable une fois par image** (documenté comme « can be used multiple times »). C'est le mode des modèles d'édition sémantique : l'image n'est pas « débruitée », elle sert de contexte. |
| `init` | `-i` / `--init-img` | Image de départ **unique** + `--strength` (img2img classique). |

Un modèle déclare ce qu'il accepte dans `registry.py` :

```python
"mon-modele-edit": {
    ...
    "supports_ref_images": True,      # le Studio d'édition (page /edit) le listera
    "input_modes": ["ref"],           # "ref", "init", ou les deux
    "max_ref_images": 10,             # canvas + références (limite d'interface)
    "ref_tag_syntax": "<image{n}>",   # ou None si le modèle n'a pas de syntaxe
    "ref_needs_vlm": True,            # un mmproj est-il nécessaire pour les refs ?
    "ref_hint": "Comment citer les images…",
    "ref_examples": ["Keep the subject in <image1>, …"],
},
```

Règles à connaître (vérifiées sur le moteur, `docs/edit.md` et
`docs/qwen_image_2.1.md` de stable-diffusion.cpp) :

- **`pass_to_vlm` ⇒ mmproj obligatoire.** Le preset de références-auto-détecté
  (`--ref-image-args`) envoie les images dans l'encodeur de texte pour `qwen`
  (`pass_to_vlm=true`) : sans `--llm_vision`, le moteur refuse/ignore les images.
  Pour `flux2` (`pass_to_vlm=false`), les références ne vont qu'au DiT : **pas de
  mmproj**, et donc **pas de balise** `<image1>` — le modèle désigne les images par
  leur position en langage naturel.
- **L'ordre des `-r` définit les index.** `ref_index_mode=increase` (déjà le défaut
  des presets `qwen` et `flux2`) numérote les images à partir de 1 : la première est
  le canvas édité.
- **Le nombre d'images n'est pas plafonné par le moteur**, mais chaque référence
  ajoute des tokens (VRAM + temps). `max_ref_images` sert à protéger l'utilisateur ;
  le levier fin est `--ref-image-args "vae_input_max_pixels=524288"` (exposé dans l'UI
  sous « budget pixels des références »).
- **`--strength` n'a aucun effet en mode `ref`** : ne pas l'envoyer dans ce cas.
- Un modèle **non** listé ici (FLUX.1 schnell, Z-Image, ERNIE, Ideogram 4, Iris-3B…)
  n'accepte pas de référence : le moteur ne lui fournira pas l'argument.
- `--mask` (inpainting) n'a d'effet que sur des poids dédiés « inpaint »
  (ex. FLUX.1-Fill-dev) : inutile de l'exposer pour les modèles du registre actuel.

Côté application, ces champs remontent dans `/api/models`, sont validés par
`registry.check_images_input()` (nombre, mode, doublons) et aboutissent dans
`registry.build_command(ref_images=[...], input_mode=…, ref_max_pixels=…)`.

---

## Étape 7 : Tester

1. Redémarrez l'application (`start.bat`).
2. Allez dans l'onglet **Modèles** → votre modèle apparaît.
3. Cliquez **Télécharger**, puis testez la génération.

Si la génération échoue, consultez le **Journal** (bouton "afficher/masquer" sur la
page Générer) qui affiche la sortie complète de `sd-cli`.
