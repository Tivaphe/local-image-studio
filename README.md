<div align="center">

# 🎨 Local Image Studio

### Générez des images par IA **en local** — 100% privé, aucune donnée envoyée sur internet

Interface web simple pour générer des images avec les modèles d'IA les plus récents (FLUX, Qwen-Image, Stable Diffusion 3.5, Z-Image…). Pensé pour les **débutants** : pas de nœuds, pas de ligne de commande, juste un prompt et un bouton.

[🇬🇧 English README](./README_EN.md)

</div>

---

## ✨ En 30 secondes

```
1. Double-cliquez sur start.bat
2. Chrome s'ouvre tout seul sur http://127.0.0.1:7860
3. Téléchargez un modèle → Écrivez un prompt → Générer !
```

**Aucune image, aucun prompt ne quitte votre ordinateur.** Tout tourne sur votre GPU local.

---

## 🖥️ Configuration requise

| Élément | Minimum | Recommandé |
|---|---|---|
| **GPU NVIDIA** | 6 Go VRAM | 12+ Go VRAM |
| **RAM** | 16 Go | 32 Go |
| **Python** | 3.10+ | 3.11 |
| **OS** | Windows 10/11 | Windows 11 |
| **Stockage** | ~5 Go (1 modèle léger) | ~70 Go (tous) |

> 💡 L'application détecte automatiquement votre VRAM et vous indique quels modèles peuvent tourner.

---

## 🚀 Installation

### Option A : Simple (recommandée)

1. **Téléchargez** le projet (ZIP ou `git clone`)
2. **Décompressez** le dossier
3. Installez **Python 3.11** depuis [python.org](https://www.python.org/downloads/) — ⚠️ cochez **"Add Python to PATH"**
4. **Double-cliquez sur `start.bat`**
5. C'est tout : **Google Chrome s'ouvre automatiquement** sur `http://127.0.0.1:7860`
   (si Chrome n'est pas installé, c'est votre navigateur par défaut qui s'ouvre)

> 🔄 **Mise à jour** : double-cliquez sur **`update.bat`** — il détecte automatiquement votre cas :
> **clone Git** (avance rapide + stash des modifications locales sur confirmation) ou **archive ZIP**
> (sans git : télécharge le ZIP de la branche choisie, fait une sauvegarde du code puis remplace
> les fichiers de l'application — idéal si vous avez téléchargé le ZIP GitHub). Dans les deux cas :
> choix de la branche (`main` ou autres), vos modèles, images, historique et réglages **jamais
> touchés**, et **réinstallation des dépendances dans `.venv`** automatiquement.

### Option B : En ligne de commande

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python src/app.py              # ouvre Chrome automatiquement sur le bon port
python src/app.py --no-browser # ...ou pas de navigateur du tout
python src/app.py --port 7861  # ...ou un autre port
```

---

## 📖 Guide rapide (première utilisation)

### 1️⃣ Installer le moteur
Onglet **Modèles** → bouton **« Installer le moteur »** (télécharge `sd-cli`, ~350 Mo).

### 2️⃣ Télécharger un modèle
Dans le même onglet, cliquez **« Télécharger »** sur un modèle.

> **Par où commencer ?** Pour vos premiers tests, choisissez **FLUX.1 schnell** (très rapide, 4 étapes) ou **Z-Image** (bonne qualité, rapide).

### 3️⃣ Générer une image
Onglet **Générer** :
1. **Tapez votre description** (prompt) en français ou anglais
2. Cliquez **🌐 Traduire EN** pour traduire en anglais (langue préférée des modèles)
3. (Optionnel) Cliquez **✨ Enrichir** pour enrichir votre prompt automatiquement
4. Choisissez le **nombre d'images** (1 à 4) et le **format** (carré, portrait, paysage…).
   Avec une image source, sélectionnez **Original** pour conserver ses proportions.
5. Cliquez **✨ Générer**

Vos images sont **automatiquement sauvegardées** dans le dossier `output/`.

### 4️⃣ Éditer une image (et en combiner plusieurs)

Onglet **✂️ Édition** — réservé aux modèles qui savent vraiment éditer :

1. **Choisissez le modèle** : Qwen-Image 2.1 / 2.1 Turbo ou FLUX.2 / FLUX.3 Klein
   (pour les Qwen, le **mmproj** — 1,2 Go — est requis : l'app le propose en un clic).
2. **Déposez l'image à modifier** : elle devient l'« image 1 » (le canvas).
3. **Ajoutez des références** (vêtement, objet, visage, style, décor…) : jusqu'à
   **10 images au total**. **L'ordre compte** : utilisez ◀ ▶ pour le changer.
4. **Décrivez la modification** :
   - **Qwen-Image 2.1 / Turbo** → citez les images avec les balises
     `<image1>`, `<image2>`… (des boutons les insèrent pour vous) :
     `Keep the character and pose in <image1> unchanged, put the shirt from <image2> on them`
   - **FLUX.2 / FLUX.3 Klein** → **pas de balise**, le modèle ne « voit » pas les images via son
     encodeur de texte : désignez-les par la position en langage naturel :
     `Put the product from image 2 on the table in image 1, keep image 1's lighting`
5. **Lancez** : le résultat s'affiche en **avant / après**.

💡 Chaque référence ajoute des tokens : si vous manquez de VRAM, baissez le
**budget pixels des références** (0,5 MP / 0,25 MP) plutôt que le nombre d'images.
💡 Pour une **img2img classique** (re-dénouiser une image avec une « force » réglable),
gardez l'onglet **Générer** → *Image de départ* (SD 3.5).

---

## 🧠 Modèles disponibles (25)

| Modèle | Vitesse | Licence | Idéal pour |
|---|---|---|---|
| **FLUX.1 schnell** | ⚡ 4 étapes | Apache 2.0 ✅ | Tests rapides |
| **FLUX.2 Klein 4B** | ⚡ 4 étapes | Apache 2.0 ✅ | Rapide + édition ×10 images |
| **FLUX.2 Klein 9B** | ⚡ 4 étapes | Non-commercial | Qualité + édition ×10 images |
| **FLUX.3 Image Klein** | ⚡ 16 étapes | Non-commercial | Qualité + édition ×10 images, texte lisible, boîtes englobantes |
| **SD 3.5 Large Turbo** | ⚡ 4 étapes | Stability AI ⚠️ | Rapidité |
| **SD 3.5 Medium** | 30 étapes | Stability AI ⚠️ | Polyvalent léger |
| **SD 3.5 Large** | 30 étapes | Stability AI ⚠️ | Haute qualité |
| **ERNIE-Image Turbo** | ⚡ 8 étapes | Apache 2.0 ✅ | Texte dans l'image |
| **Z-Image** | 28 étapes | Apache 2.0 ✅ | Qualité polyvalente |
| **Qwen-Image 2512** | 30 étapes | Apache 2.0 ✅ | Réalisme humain |
| **Qwen-Image 2.1** | 25 étapes | Qwen Research ⚠️ | Édition multi-images (×10) + transparence |
| **Qwen-Image 2.1 Turbo** | ⚡ 8 étapes, CFG 1 | Qwen Research ⚠️ | Génération + édition rapide multi-images |
| **Iris-3B** | 100 étapes | Apache 2.0 ✅ | Génération en espace pixel |
| **Ideogram 4** | 12 étapes | Ideogram | Rendu de texte |
| **FHDR Uncensored** | 20 étapes | Non-commercial | Sans censure |
| **Fibo 2.0 Dev** (GGUF) | 50 étapes, CFG 5 | CC BY-NC 4.0 ⚠️ | Génération + édition par références |
| **Fibo 2.0 Edit Turbo** (GGUF) | ⚡ 4 étapes, CFG 1 | CC BY-NC 4.0 ⚠️ | Édition rapide par références |
| **MOSS-Image SFT** (GGUF) | 50 étapes, CFG 3 | Apache 2.0 ✅ | Génération standard, texte dans l'image |
| **MOSS-Image Base** (GGUF) | 50 étapes, CFG 3 | Apache 2.0 ✅ | Base non ajustée, pour LoRA entraînés sur Base |
| **Krea 2 Turbo** (GGUF) | ⚡ 8 étapes, CFG 1 | Krea Community ⚠️ | Rendu photoréaliste rapide |
| **FLUX.1 Dev** (GGUF) | 24 étapes | FLUX [dev] ⚠️ | Haute finesse (mains, peau, lumière), img2img + LoRA |
| **FLUX.1 Kontext Dev** (GGUF) | 24 étapes | FLUX [dev] ⚠️ | Édition contextuelle : modifier sans casser l'identité |
| **Chroma Unlocked** (GGUF) | 26 étapes, CFG 4 | Apache 2.0 ✅ | Prompt négatif + textures organiques (anti « peau plastique ») |
| **Chroma1-Radiance** (GGUF) | 26 étapes, CFG 4 | Apache 2.0 ✅ | Espace pixel sans VAE : piqué remarquable, prompt négatif |
| **LongCat-Image** (GGUF) | 28 étapes, CFG 5 | Apache 2.0 ✅ | Photoréalisme + texte exact entre «guillemets» |

> ✅ = usage commercial autorisé · ⚠️ = usage personnel/non-commercial
>
> Les 5 derniers modèles **réutilisent les dépendances existantes** : FLUX.1 Dev / Kontext utilisent
> `vae_flux`, `clip_l` et `t5xxl` ; Chroma utilise `vae_flux` + `t5xxl` ; Chroma1-Radiance n'a besoin
> que de `t5xxl` ; LongCat-Image réutilise `vae_flux` et l'encodeur **Qwen2.5-VL-7B** (déjà utilisé
> par Qwen-Image 2512). Si vous avez déjà FLUX.1 schnell ou Qwen-Image, aucun gros téléchargement
> supplémentaire n'est nécessaire.
>
> **Qwen-Image 2.1 Turbo** nécessite `sd-cli` `c150a6b` ou plus récent (8 étapes, CFG 1).
> **FLUX.3 Image Klein** nécessite `sd-cli` `8cd731e` (15 oct. 2026) ou plus récent ; ses GGUF sont convertis avec ce même moteur (pics VRAM documentés : 6,8 Go en Q3_K à 9,8 Go en Q8_0) et il réutilise le VAE FLUX.2 et l'encodeur **Qwen3-VL-4B** (déjà téléchargés avec FLUX.2 Klein / Iris-3B).
> **Fibo 2.0** nécessite un `sd-cli` récent (support ajouté le 21 oct. 2026). Ses GGUF viennent de `molbal/fibo-2.0-GGUF` (Q4_K_M, Q6_K, Q8_0) et utilisent l'encodeur Qwen3-VL-4B et le VAE FLUX.2. L'édition demande le **mmproj** Qwen3-VL-4B (0,84 Go), téléchargeable depuis l'onglet Édition.
> **MOSS-Image** (Base et SFT) utilise l'encodeur **Qwen3.5-9B** (GGUF, ~5,7 Go), le VAE FLUX.2 et un `tokenizer.json` externe, téléchargés automatiquement. Quants officiels `leejet/MOSS-Image-*-GGUF`.
> **Krea 2 Turbo** nécessite stable-diffusion.cpp `master-721` ou plus récent. Quants `realrebelai/KREA-2_GGUFs` (dossier TURBO), VAE Wan 2.1 et encodeur Qwen3-VL-4B.
> **Iris-3B** nécessite `sd-cli` `f89d9b1` ou plus récent; ses poids font ~12 Go, plus l'encodeur Qwen3-VL-4B. Réinstalle le moteur depuis l'onglet Modèles si nécessaire.
> Fichiers : `models/diffusion/model.safetensors` (checkpoint officiel) et `models/llm/Qwen3VL-4B-Instruct-Q4_K_M.gguf`; aucun VAE.

### 💡 Quel modèle choisir ?

- **Vous débutez ?** → **FLUX.1 schnell** (le plus rapide)
- **Meilleure qualité rapide ?** → **FLUX.3 Image Klein** (16 étapes), **FLUX.2 Klein 9B**, **Qwen-Image 2512** ou **Qwen-Image 2.1 Turbo**
- **Génération en espace pixel ?** → **Iris-3B** (100 étapes)
- **Édition d'images ?** → onglet **Édition** : **Qwen-Image 2.1 / 2.1 Turbo** (édition sémantique,
  jusqu'à 10 images), **FLUX.2 / FLUX.3 Klein** (édition par position, jusqu'à 10 images) ou **Fibo 2.0 Edit Turbo** (4 étapes)
- **Img2img classique ?** → **SD 3.5 Medium/Large** (contrôle de la force)
- **Texte lisible dans l'image ?** → **ERNIE-Image Turbo**, **Ideogram 4** ou **LongCat-Image**
- **Éditer sans casser l'identité ?** → **FLUX.1 Kontext Dev** (changer le texte, la lumière, le décor)
- **Mains et textures réalistes ?** → **Chroma Unlocked** (vrai prompt négatif) + **ADetailer**
- **Le plus léger ?** → **SD 3.5 Medium** (~2 Go)

---

## ✨ Qualité, Détails & Agrandissement (1 clic, explications intégrées)

Sur les pages **Générer** et **Édition**, une section repliable « ✨ Qualité, Détails &
Agrandissement » regroupe toutes les options avancées, chacune avec une **explication en français** :

| Option | Effet | Où ? |
|---|---|---|
| **🔍 Agrandissement ×4** | Super-résolution dédiée (1024→4096 px). Choix : **RealESRGAN ×4** (photo), **4× Nomos2 MoSR** (textures naturelles), **4× UltraSharp** (détails & netteté), **4× UltraMix Balanced** (UltraSharp adouci), **4× Remacri** (grain photo naturel), **RealESRGAN Anime 6B** (illustration) | Pendant la génération (case option) **ou** après coup : bouton « 🔍 Agrandir ×4 » sur chaque résultat et dans l'historique |
| **🏗️ Hires Fix (2 passes)** | 1ʳᵉ passe : composition à taille choisie ; 2ᵉ passe : re-détaillage doux en haute résolution (jusqu'à ×2, ≤ ~2048 px) | Génération pure, modèles compatibles img2img (SD 3.5, FLUX.1 Dev, Chroma) |
| **🙂 ADetailer** | Détecteur YOLOv8 qui repère **visages/mains** puis les re-détaille automatiquement — aussi en 1 clic après coup sur n'importe quelle image | Pages Générer & Édition (après installation du détecteur dans Modèles) |
| **⚡ Mini-VAE (TAE)** | Décodage final Quasi instantané pour les modèles Qwen-Image (~2 Mo) | Section Qualité → ⚡ Performance |
| **⚡ SageAttention CUDA** | Attention plus rapide et moins de VRAM sur GPU NVIDIA (SM80+, pilotes récents) — aucune installation Python | Section Qualité → ⚡ Performance |
| **📡 Aperçu en direct** | Fenêtre « LIVE » : voyez l'image se débruiter pas à pas (**activé par défaut, mode « Auto »** : mini-VAE si installé, sinon projection des latents) | Section Qualité → ⚡ Performance |
| **🎭 Visage fidèle (PuLID)** | Conserve le visage d'une photo (FLUX.1 Schnell/Dev/FHDR uniquement) | Section Qualité → 🎭 Visage fidèle — voir `docs/PULID_FR.md` |
| **⬆️ PiD ×4** | Super-résolution **générative** ×4 (1024→4096 en 4 étapes), conditionnée par le prompt de l'image — reconstruit la matière là où ESRGAN lisse | Bouton « ⬆️ PiD ×4 » sur chaque résultat / dans l'historique (voir `docs/PID_FR.md`, licence NSCLv1) |
| **🎛️ Sampler / Scheduler** | Choix de l'échantillonneur (euler, heun, dpm++2m, euler_a, lcm) et du planificateur (karras, beta, exponential…) | Pages Générer & Édition |
| **⚙️ VAE Tiling** | Décodage par tuiles — économise la VRAM sur grandes images | Réglages experts |
| **⚙️ SLG (Skip Layer Guidance)** | Améliore le respect du prompt sur les modèles DiT (valeur conseillée : 3) | Réglages experts |

Les modèles d'agrandissement (17–64 Mo) et les détecteurs ADetailer (6–22 Mo) se téléchargent
en **1 clic** depuis la page **Modèles** (sections dédiées en bas de page).

> 💡 **Aperçu en direct — comment ça marche** : le binaire sd-cli écrit une image d'aperçu toutes les
> N étapes (`--preview-interval`) dans `.preview_cache/`, et l'interface l'affiche dans la fenêtre
> « LIVE » au-dessus des résultats (pages Générer et Édition). Trois modes : **Auto** (défaut) =
> mini-VAE si un TAE est installé pour ce modèle, sinon **proj** (projection des latents, instantanée,
> sans fichier) ; la projection est connue pour SD1.x/XL, SD 3.5, FLUX (Schnell/Dev/FHDR/Chroma/Kontext),
> FLUX.2 et Qwen-Image-2.1. Sur **Qwen-Image 2512**, seul le mini-VAE (Modèles → ⚡ VAE rapide) produit
> un aperçu. L'ancienne option « vae » n'a jamais décodé avec le vrai VAE dans ce binaire (le runner
> d'aperçu est toujours le mini-VAE) — elle est traitée comme « tae ». Avec le mini-VAE, le décodage
> **final** reste fait par le vrai VAE (`--taesd-preview-only`). Aucune image d'aperçu avec un modèle
> sans projection connue ni TAE : normal, l'image finale est inchangée.

> ⚠️ **Licences des nouveaux agrandisseurs** — **4× UltraSharp**, **4× UltraMix Balanced** et
> **4× Remacri** sont publiés en **CC-BY-NC-SA-4.0** (Kim2091 pour les deux premiers ; Remacri par
> FoolhardyVEVO, fourni ici en GGUF converti par stable-diffusion.cpp lui-même, licence inchangée) :
> **usage privé / non commercial**. Pour un usage commercial, préférez **RealESRGAN ×4**
> (BSD-3-Clause) ou **4× Nomos2 MoSR** (CC-BY-4.0). Ces trois modèles sont des ajouts récents :
> **non testés sur GPU réel** — signalez tout problème via une issue.

---

## 🩹 Restauration & Réparation (images existantes)

Deux outils agissent directement sur une image déjà générée (boutons sur chaque résultat et dans l'historique) :

| Outil | Principe | Note |
|---|---|---|
| **🩹 Restauration ×2 (SeedVR2)** | Reconstruit la matière (peau, tissus, texte) et double la résolution par diffusion | ~6,8 Go à installer, ~10 Go de VRAM, lent mais bluffant sur vieilles photos |
| **🙂 Réparation visages & mains (ADetailer)** | Le détecteur repère visages/mains et le modèle re-détaille ces zones uniquement | Quelques Mo à installer, modifie uniquement les zones détectées |
| **🔍 Agrandissement ×4 (ESRGAN)** | Super-résolution classique | 17–64 Mo, rapide |
| **⬆️ PiD ×4 (NVIDIA Pixel Diffusion)** | Ré-encode l'image avec le VAE du backbone puis la décode en **4096×4096 en 4 étapes**, guidée par le prompt de l'image — backbones FLUX.1 / FLUX.2 / Qwen-Image | ~1,6 Go par backbone + socle ~5,4 Go (Gemma 2 2B), **licence NSCLv1 non-commerciale** — voir `docs/PID_FR.md` |

> 💡 **Suivi en direct** : depuis la page **Historique**, chaque opération lancée sur une image existante
> (« 🙂 Réparer », « 🩹 Restaurer ×2 », « 🔍 Agrandir ×4 », « ⬆️ PiD ×4 ») affiche un **bandeau de
> progression en temps réel** : opération en cours ou **en file d'attente** (position), pourcentage,
> étape x/y, chronomètre, dernière ligne du moteur sd-cli, et **le message d'erreur complet** en cas
> d'échec — plus de bouton bloqué sur « en cours » sans retour.

---

## 📥 Métadonnées intégrées dans chaque PNG

Chaque image générée porte désormais un bloc de métadonnées (prompt, seed, modèle…).
Concrètement vous pouvez :

- **Glisser-déposer un PNG** généré n'importe où sur le panneau **Générer** ou **Édition** :
  tous les réglages (prompt, négatif, seed, modèle, taille, sampler…) sont restaurés instantanément ;
- utiliser **🗂️ Lot de prompts** (une image par ligne, 16 max) pour générer série après série ;
- utiliser **⚔️ Duel de seeds** (même prompt, deux seeds consécutifs) et **🥊 Comparer deux modèles**
  pour trancher entre variantes — les deux images atterrissent dans l'historique ;
- profiter de l'**aperçu en direct** pendant l'échantillonnage (section ⚡ Performance) ;
- les anciens PNG sans métadonnées sont tagués à la volée lors de la prochaine génération
  (sans jamais réécrire vos fichiers existants).

---

## ⚠️ Modèles protégés (gated)

Certains modèles nécessitent un **token Hugging Face gratuit** :

**FHDR, FLUX.2 Klein 9B, SD 3.5 (Medium/Large/Turbo)**

1. Créez un compte sur [huggingface.co](https://huggingface.co/join)
2. Créez un token : [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → type **Read**
3. Allez sur la page du modèle et **acceptez les conditions**
4. Dans l'app → onglet **Paramètres** → collez votre token → **Enregistrer**

---

## 🌟 Fonctionnalités

| Fonction | Description |
|---|---|
| 🖼️ **Génération** | 1 à 4 images par lot, 5 formats + proportions originales en édition |
| ✂️ **Studio d'édition** | Onglet **Édition** : 1 canvas + jusqu'à **10 images** de référence, réordonnancement, comparaison avant/après |
| 🗂️ **Lot de prompts** | Une ligne par prompt (16 max), générés en file d'attente |
| ⚔️ **Duel / Comparaison** | Même prompt en 2 seeds consécutifs, ou sur 2 modèles |
| 📡 **Aperçu en direct** | L'image se construit à l'écran pendant l'échantillonnage |
| 📥 **Réglages dans le PNG** | Glissez-déposez n'importe quel PNG généré : prompt, seed, modèle… restaurés |
| ⬆️ **PiD ×4** | Super-résolution générative (FLUX.1 / FLUX.2 / Qwen-Image), 4 étapes, sortie 4096×4096 |
| 🌐 **Traduction** | Traduit votre prompt (FR, ES…) vers l'anglais automatiquement |
| ✨ **Enrichissement** | Un LLM enrichit votre prompt (style, lumière, composition…) |
| 📊 **Statistiques** | Temps de génération par modèle, modèle le plus utilisé, etc. |
| 📚 **Historique** | Toutes vos images avec leur prompt, réutilisables en 1 clic |
| 💾 **Auto-save** | Images sauvées dans `output/` |
| 🚫 **Prompt négatif** | Pré-rempli automatiquement (modifiable) |
| 📄 **Licences** | Indiquées pour chaque modèle |
| 🔗 **Liens HF** | Accès direct à la page de chaque modèle |

---

## 📁 Structure du projet

**Après décompression du ZIP, vous ne touchez qu'à `start.bat`** (double-clic) — tout le reste
est rangé dans des sous-dossiers :

```
local-image-studio/
├── start.bat              ← ⭐ Double-cliquez ici pour lancer (Windows)
├── update.bat             ← 🔄 Mise à jour (clone Git ou ZIP) : branche au choix + rafraîchit .venv
├── README.md              ← Ce document (FR)
├── README_EN.md           ← English documentation
├── requirements.txt       ← Dépendances Python
├── LICENSE
│
├── src/                   ← Code de l'application (rien à toucher ici)
│   ├── app.py             ← Serveur web (Flask) + options de démarrage
│   ├── browser_launch.py  ← Ouvrir Chrome automatiquement au démarrage
│   ├── engine.py          ← Moteur sd-cli + téléchargements + file d'attente
│   ├── registry.py        ← Définition des 25 modèles + upscalers ×4 + détecteurs ADetailer
│   ├── prompt_enhancer.py ← Enrichissement & traduction (LLM)
│   ├── metadata.py        ← Métadonnées PNG (lecture / injection des réglages)
│   ├── gpu_info.py        ← Détection VRAM
│   ├── db.py              ← Historique & statistiques
│   ├── config.py          ← Configuration des chemins
│   ├── templates/         ← Pages HTML (generate.html, edit.html, …)
│   └── static/            ← CSS + JavaScript (generate.js, edit.js, quality.js, …)
│
├── docs/                  ← Documentation
│   ├── ADD_MODEL_FR.md    ← Comment ajouter un modèle (FR)
│   ├── ADD_MODEL_EN.md    ← How to add a model (EN)
│   ├── PULID_FR.md        ← PuLID : installation & empreintes de portrait (FR)
│   └── PID_FR.md          ← PiD : super-résolution générative ×4 (FR)
├── tests/                 ← Tests unitaires (python -m unittest discover -s tests)
│
└── (créés automatiquement au premier lancement)
    ├── .venv/             ← Environnement Python isolé (créé par start.bat)
    ├── bin/               ← sd-cli.exe (téléchargé auto)
    ├── models/            ← GGUF/safetensors + VAE + encodeurs + upscalers (téléchargés auto)
    ├── source_images/     ← Vos images de départ (img2img / édition)
    ├── output/            ← Vos images générées
    ├── history.db         ← Historique (base SQLite)
    └── settings.json      ← Vos réglages
```

---

## ➕ Ajouter un modèle

L'application est conçue pour être **extensible**. Vous pouvez ajouter des modèles
GGUF compatibles avec `stable-diffusion.cpp` et certains checkpoints dans d'autres
formats acceptés par le moteur, comme les safetensors d'Iris-3B.

📖 **Voir le guide complet : [docs/ADD_MODEL_FR.md](./docs/ADD_MODEL_FR.md)**

En résumé : éditez `src/registry.py` → ajoutez une entrée dans le dictionnaire `MODELS` → redémarrez.

---

## 🛠️ Dépannage

> 💡 **Métadonnées PNG indisponibles** — les fonctions « Glisser-déposer un PNG » et
> « Réglages restaurés » exigent **Pillow** (`pip install -r requirements.txt`, normalement
> déjà fait par `start.bat`). Sans Pillow, tout le reste fonctionne ; seules ces deux
> fonctionnalités sont désactivées.

> 💡 **SageAttention sans effet** — l'option `--sage-attn` demande un GPU NVIDIA RTX 30/40/50
> (ou Ampere SM80+) avec pilotes ≥ 555 (CUDA 12.8+). Sur une autre carte, sd-cli l'ignore
> proprement sans planter.

> 💡 **Aperçu en direct « tae » grisé** — la méthode d'aperçu tae requiert le mini-VAE
> correspondant (onglet Modèles → ⚡ VAE rapide, ~2 Mo, modèles Qwen-Image uniquement).
> Utilisez « proj » pour un aperçu sans aucun prérequis.



| Problème | Solution |
|---|---|
| **Les boutons ne marchent pas** | `Ctrl+F5` dans le navigateur (vider le cache) |
| **« Le moteur n'est pas installé »** | Onglet Modèles → Installer le moteur |
| **Génération lente** | Utilisez Q4_K_M, ou un modèle "Turbo"/"schnell" |
| **Image blanche** | Vérifiez que vous avez la dernière version du code |
| **« token requis »** | Ajoutez votre token HF dans Paramètres |
| **Enrichissement indisponible** | Installez les [C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) Microsoft, puis relancez `start.bat` |
| **VRAM insuffisante** | Descendez en Q4_K_M, réduisez la résolution |
| **Python introuvable** | Réinstallez Python 3.11 en cochant "Add to PATH" |
| **Le navigateur ne s'ouvre pas** | Chrome est-il installé ? Sinon c'est le navigateur par défaut qui s'ouvre. Vérifiez aussi la case **Paramètres → Ouvrir Chrome au démarrage**, ou lancez `python src/app.py --no-browser` pour désactiver complètement |
| **L'onglet s'ouvre avant que le serveur soit prêt** | Rien à faire : la page se charge dès que le port écoute (l'ouverture attend le serveur) |
| **Port 7860 déjà utilisé** | Lancez `python src/app.py --port 7861` (l'onglet s'ouvrira sur le bon port) |

---

## 🔧 Comment ça marche ?

L'application pilote **`sd-cli.exe`** (le moteur C/C++ de
[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) par leejet).
Ce moteur fait tourner FLUX, Qwen-Image, Stable Diffusion 3.5, Z-Image, ERNIE,
Ideogram 4 et d'autres modèles au format **GGUF**; Iris-3B utilise ses poids
**safetensors** (sans VAE).

L'interface web (Flask) construit automatiquement la bonne ligne de commande pour
chaque modèle, gère les téléchargements, et affiche tout derrière une page simple.

**L'enrichissement et la traduction** utilisent un petit LLM (Qwen3-4B, déjà
téléchargé comme dépendance de Z-Image/FLUX.2) via `llama-cpp-python` sur CPU.

---

## 📜 Licence

Ce projet est open-source. Les modèles utilisés ont leurs propres licences
(voir l'onglet Modèles dans l'application). Vérifiez toujours la licence du
modèle avant d'utiliser les images générées commercialement.

---

<div align="center">

**Fait avec ❤️ pour rendre la génération d'images IA accessible à tous.**

[Signaler un bug](https://github.com/) · [Ajouter un modèle](./docs/ADD_MODEL_FR.md) · [English](./README_EN.md)

</div>
