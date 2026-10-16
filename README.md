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
2. Ouvrez http://127.0.0.1:7860
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
| **Stockage** | ~5 Go (1 modèle léger) | ~65 Go (tous) |

> 💡 L'application détecte automatiquement votre VRAM et vous indique quels modèles peuvent tourner.

---

## 🚀 Installation

### Option A : Simple (recommandée)

1. **Téléchargez** le projet (ZIP ou `git clone`)
2. **Décompressez** le dossier
3. Installez **Python 3.11** depuis [python.org](https://www.python.org/downloads/) — ⚠️ cochez **"Add Python to PATH"**
4. **Double-cliquez sur `start.bat`**
5. Ouvrez **http://127.0.0.1:7860** dans votre navigateur

### Option B : En ligne de commande

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
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

1. **Choisissez le modèle** : Qwen-Image 2.1 / 2.1 Turbo ou FLUX.2 Klein 4B / 9B
   (pour les Qwen, le **mmproj** — 1,2 Go — est requis : l'app le propose en un clic).
2. **Déposez l'image à modifier** : elle devient l'« image 1 » (le canvas).
3. **Ajoutez des références** (vêtement, objet, visage, style, décor…) : jusqu'à
   **10 images au total**. **L'ordre compte** : utilisez ◀ ▶ pour le changer.
4. **Décrivez la modification** :
   - **Qwen-Image 2.1 / Turbo** → citez les images avec les balises
     `<image1>`, `<image2>`… (des boutons les insèrent pour vous) :
     `Keep the character and pose in <image1> unchanged, put the shirt from <image2> on them`
   - **FLUX.2 Klein** → **pas de balise**, le modèle ne « voit » pas les images via son
     encodeur de texte : désignez-les par la position en langage naturel :
     `Put the product from image 2 on the table in image 1, keep image 1's lighting`
5. **Lancez** : le résultat s'affiche en **avant / après**.

💡 Chaque référence ajoute des tokens : si vous manquez de VRAM, baissez le
**budget pixels des références** (0,5 MP / 0,25 MP) plutôt que le nombre d'images.
💡 Pour une **img2img classique** (re-dénouiser une image avec une « force » réglable),
gardez l'onglet **Générer** → *Image de départ* (SD 3.5).

---

## 🧠 Modèles disponibles (14)

| Modèle | Vitesse | Licence | Idéal pour |
|---|---|---|---|
| **FLUX.1 schnell** | ⚡ 4 étapes | Apache 2.0 ✅ | Tests rapides |
| **FLUX.2 Klein 4B** | ⚡ 4 étapes | Apache 2.0 ✅ | Rapide + édition ×10 images |
| **FLUX.2 Klein 9B** | ⚡ 4 étapes | Non-commercial | Qualité + édition ×10 images |
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

> ✅ = usage commercial autorisé · ⚠️ = usage personnel/non-commercial
>
> **Qwen-Image 2.1 Turbo** nécessite `sd-cli` `c150a6b` ou plus récent (8 étapes, CFG 1).
> **Iris-3B** nécessite `sd-cli` `f89d9b1` ou plus récent; ses poids font ~12 Go, plus l'encodeur Qwen3-VL-4B. Réinstalle le moteur depuis l'onglet Modèles si nécessaire.
> Fichiers : `models/diffusion/model.safetensors` (checkpoint officiel) et `models/llm/Qwen3VL-4B-Instruct-Q4_K_M.gguf`; aucun VAE.

### 💡 Quel modèle choisir ?

- **Vous débutez ?** → **FLUX.1 schnell** (le plus rapide)
- **Meilleure qualité rapide ?** → **FLUX.2 Klein 9B**, **Qwen-Image 2512** ou **Qwen-Image 2.1 Turbo**
- **Génération en espace pixel ?** → **Iris-3B** (100 étapes)
- **Édition d'images ?** → onglet **Édition** : **Qwen-Image 2.1 / 2.1 Turbo** (édition sémantique,
  jusqu'à 10 images) ou **FLUX.2 Klein** (édition rapide par position)
- **Img2img classique ?** → **SD 3.5 Medium/Large** (contrôle de la force)
- **Texte lisible dans l'image ?** → **ERNIE-Image Turbo** ou **Ideogram 4**
- **Le plus léger ?** → **SD 3.5 Medium** (~2 Go)

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

```
local-image-studio/
├── start.bat              ← Double-clic pour lancer
├── app.py                 ← Serveur web (Flask)
├── engine.py              ← Moteur sd-cli + téléchargements
├── registry.py            ← Définition des 14 modèles
├── prompt_enhancer.py     ← Enrichissement & traduction (LLM)
├── gpu_info.py            ← Détection VRAM
├── db.py                  ← Historique & statistiques
├── config.py              ← Configuration des chemins
├── requirements.txt       ← Dépendances Python
├── templates/             ← Pages HTML (generate.html, edit.html, …)
├── static/                ← CSS + JavaScript (generate.js, edit.js, …)
├── docs/                  ← Documentation
│   ├── ADD_MODEL_FR.md    ← Comment ajouter un modèle (FR)
│   └── ADD_MODEL_EN.md    ← How to add a model (EN)
│
├── bin/                   ← sd-cli.exe (téléchargé auto)
├── models/                ← GGUF/safetensors + VAE + encodeurs (téléchargés auto)
└── output/                ← Vos images générées
```

---

## ➕ Ajouter un modèle

L'application est conçue pour être **extensible**. Vous pouvez ajouter des modèles
GGUF compatibles avec `stable-diffusion.cpp` et certains checkpoints dans d'autres
formats acceptés par le moteur, comme les safetensors d'Iris-3B.

📖 **Voir le guide complet : [docs/ADD_MODEL_FR.md](./docs/ADD_MODEL_FR.md)**

En résumé : éditez `registry.py` → ajoutez une entrée dans le dictionnaire `MODELS` → redémarrez.

---

## 🛠️ Dépannage

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
