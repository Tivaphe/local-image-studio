# ⬆️ PiD ×4 — Super-résolution générative (NVIDIA Pixel Diffusion)

Documentation volontairement concise — l'installation se fait en 1 clic depuis l'onglet **Modèles**.

## Ce que c'est

**PiD (Pixel diffusion Decoder)** est un décodeur NVIDIA qui remplace le VAE final par une
**diffusion pixel-space conditionnée par le prompt** : il ré-encode l'image avec le VAE de la
famille de modèle, puis la décode directement en **4096×4096 en 4 étapes**. Résultat : il
*reconstruit des détails crédibles* (peau, tissu, texte, végétation) là où un RealESRGAN se
contente de lisser. C'est le « super-résolveur » open-weights le plus proche d'un vrai décodeur génératif.

| | ESRGAN ×4 | SeedVR2 ×2 | **PiD ×4** |
|---|---|---|---|
| Type | Super-résolution déterministe | Restauration par diffusion | **Décodage génératif (pixel-space)** |
| Guidé par le prompt | Non | Indirectement (image seule) | **Oui — prompt confirmé par vous (modale avant lancement)** |
| Sortie | ×4 | ×2 | **×4 → 4096×4096** |
| Poids | 17–64 Mo | ~6,8 Go | **~1,6 Go int8 par backbone** (+ socle commun ~5,4 Go) |
| Vitesse | Rapide | Lent (minutes) | 4 étapes, mais pixels 4096² (modéré) |
| Licence | Variable | Apache-2.0 | **NSCLv1 — non-commerciale** |

## ⚠️ Licence — à lire avant d'installer

- Les checkpoints PiD (et donc les repacks Comfy-Org/PixelDiT qui les distribuent) sont sous
  **NSCLv1 : usage de recherche et d'évaluation non-commerciale uniquement.**
  Usage personnel chez vous : OK. Tout usage commercial ou redistribution : interdit.
- Les poids officiels `nvidia/PiD` sont au format `.pth` PyTorch — **non utilisés ici**.
  L'app s'appuie sur les **safetensors `Comfy-Org/PixelDiT`**, relus par `sd-cli`
  (support ajouté en amont le 2026-05-31 — voir
  [stable-diffusion.cpp/docs/pid.md](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/pid.md)).
- L'encodeur de texte **Gemma 2 2B** est distribué par Comfy-Org/PixelDiT (non-gated).
  Le **tokenizer** (`tokenizer_gemma2.json`) provient du miroir **non-gated**
  `unsloth/gemma-2-2b-it` — le dépôt officiel `google/gemma-2-2b` est *gated*
  (connexion + licence Google requises), il n'est donc **pas** utilisé par le téléchargement 1-clic.

## Prérequis

1. **sd-cli ≥ 2026-05-31** — c'est le cas dès que vous réinstallez le moteur depuis l'onglet
   Modèles (les Binaires Pro). Une version antérieure ne connaît pas `--vae-format` / PiD.
2. **~7,1 Go de disque libre** pour le premier backbone (socle + modèle), +1,6 Go par backbone sup.
3. **~10–14 Go de VRAM conseillés** pour le décodage pixel-space 4096×4096. En dessous, sd-cli
   peut échouer proprement — dans ce cas, utilisez 🩹 Restaurer ×2 (SeedVR2, ~×2) ou 🔍 ×4 (ESRGAN).
4. Aucune dépendance Python en plus (tout passe par sd-cli).

## Installation (1 clic)

Onglet **Modèles** → section **⬆️ PiD** → choisissez votre backbone :

| Backbone | Familles compatibles | VAE (`--vae-format`) |
|---|---|---|
| **FLUX.1** (`pid_1.5_flux1_…_int8_convrot`) | FLUX.1 Dev / Schnell / Kontext / Chroma / Z-Image | `flux` → `models/vae/ae.safetensors` |
| **FLUX.2** (`pid_1.5_flux2_…_int8_convrot`) | FLUX.2 Klein 4B / 9B | `flux2` → `models/vae/flux2-vae.safetensors` |
| **Qwen-Image** (`pid_1.5_qwenimage_…_int8_convrot`) | Qwen-Image 2508 / 2512 (VAE Wan 2D) | `wan` → `models/vae/qwen_image_vae.safetensors` |

Le téléchargement récupère **automatiquement**, une seule fois pour tous les backbones :

- `models/pid/gemma_2_2b_it_elm_bf16.safetensors` (~5,4 Go) — encodeur de texte PiD ;
- `models/pid/tokenizer_gemma2.json` (~18 Mo) — tokenizer Gemma 2 (miroir unsloth non-gated) ;

puis, par backbone, `models/pid/pid_1.5_*_4step_int8_convrot.safetensors` (~1,6 Go) + le **VAE**
correspondant (réutilise les dépôts déjà utilisés par vos modèles FLUX/Qwen-Image — normalement déjà là).

## Utilisation

Un bouton **⬆️ PiD ×4** apparaît sur chaque résultat (Générer / Édition) et dans l'historique.
Concrètement :

1. **Vous confirmez le prompt** dans la modale « Prompt de reconstruction » qui s'ouvre avant
   le lancement : le prompt enregistré avec l'image est pré-rempli, **modifiable**, et si vous
   le videz c'est une description générique de qualité qui est utilisée. Un bouton
   « Description générique » ignore le prompt affiché. Si le texte ressemble à une
   *instruction d'édition* (« garde le sujet… », « redessine… », `<image…`…), un avertissement
   s'affiche. C'est important : PiD **reconstruit** l'image à partir du prompt — lui donner une
   recette d'édition au lieu d'une description du contenu emmène la reconstruction dans la
   mauvaise direction. Décrivez **ce que vous voyez**.
2. Le backbone est choisi automatiquement : d'abord la **famille du modèle source**
   (FLUX.1 → `flux1`, FLUX.2 → `flux2`, Qwen-Image → `qwenimage`) si elle est installée,
   sinon le premier backbone complet trouvé.
3. sd-cli encode l'image (`-r`) puis décode en 4096×4096 (`--steps 4`, `--cfg-scale 1.0`).
4. La sortie est enregistrée dans `output/` (préfixe `pid_`), taguée dans les métadonnées,
   et ajoutée à l'**historique** (bouton ⬆️ visible sur sa carte).
5. Côté serveur, si aucun prompt explicite n'est envoyé, celui de l'image est repris depuis
   l'historique **uniquement s'il décrit le contenu** : un prompt-instruction (édition, retouche,
   post-traitement) ou une image issue d'un post-traitement retombe sur la description générique
   (raison journalisée dans le log). L'API accepte un prompt explicite :
   `POST /api/pid-upscale {"path": "…", "prompt": "…"}`.

## Limites connues & dépannage

- **Qwen-Image 2.1 / 2512** : si vos modèles 2.1 utilisent des latents 64 canaux, PiD n'est
  pas entraîné pour cet espace → préférez 🩹 SeedVR2 pour ces modèles.
- **SD 1.5 / SDXL / SD3** : non proposés ici (VAE gated côté distribution) — utilisez 🩹 SeedVR2 ou ESRGAN.
- **« VAE requis introuvable »** : relancez le téléchargement PiD dans Modèles, ou installez
  d'abord le modèle de la famille (FLUX.1 / FLUX.2 / Qwen-Image) — le VAE est alors récupéré automatiquement.
- **« moteur sd-cli n'est pas installé / trop ancien »** : onglet Modèles → réinstaller le moteur.
- **Erreur CUDA / OOM à 4096×4096** : GPU sans assez de VRAM pour le pixel-space →
  basculez sur SeedVR2 ×2 ou ESRGAN ×4 ; ou réduisez la résolution source.
- **Sortie incohérente** : vérifiez que l'image source correspond bien à la famille du backbone
  choisi (le choix automatique se base sur le modèle d'origine ; forcez un autre backbone en appelant
  l'API `POST /api/pid-upscale {"path": "...", "backbone": "flux2"}` si besoin).

## Recette manuelle (sans l'app)

```bash
sd-cli --diffusion-model models/pid/pid_1.5_flux1_1024_to_4096_4step_int8_convrot.safetensors \
       --llm models/pid/gemma_2_2b_it_elm_bf16.safetensors \
       --tokenizer models/pid/tokenizer_gemma2.json \
       --vae models/vae/ae.safetensors --vae-format flux \
       --cfg-scale 1.0 -p "prompt de l'image" -r source.png \
       --steps 4 -H 4096 -W 4096 -s 42 -o sortie.png --rng cpu -v
```

## Liens

- [Comfy-Org/PixelDiT](https://huggingface.co/Comfy-Org/PixelDiT) — poids safetensors
  (`diffusion_models/`, `text_encoders/`), non-gated, licence NSCLv1
- [unsloth/gemma-2-2b-it](https://huggingface.co/unsloth/gemma-2-2b-it) — `tokenizer.json` (non-gated)
- [nvidia/PiD](https://huggingface.co/nvidia/PiD) — dépôt officiel (licence, paper, checkpoints .pth)
- [stable-diffusion.cpp/docs/pid.md](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/pid.md) — doc CLI amont
- Paper : arXiv **2605.23902** · Projet : research.nvidia.com/labs/sil/projects/pid/

> État des tests : les routes, la construction de commande, les téléchargements et l'historique
> sont couverts par `tests/test_feature_packs.py` ; la résolution du prompt de reconstruction
> (explicite > historique descriptif > description générique, + détection des instructions
> d'édition FR/EN) est couverte par `tests/test_pid_prompt.py`. Le décodage GPU réel n'a pas pu
> être validé dans l'environnement de développement (pas de GPU) — sur votre carte, la première
> exécution vous dira tout de suite si ça tient en VRAM.
