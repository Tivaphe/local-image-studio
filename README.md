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
| **Stockage** | ~5 Go (1 modèle) | ~50 Go (tous) |

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
4. Choisissez le **nombre d'images** (1 à 4) et le **format** (carré, portrait, paysage…)
5. Cliquez **✨ Générer**

Vos images sont **automatiquement sauvegardées** dans le dossier `output/`.

---

## 🧠 Modèles disponibles (11)

| Modèle | Vitesse | Licence | Idéal pour |
|---|---|---|---|
| **FLUX.1 schnell** | ⚡ 4 étapes | Apache 2.0 ✅ | Tests rapides |
| **FLUX.2 Klein 4B** | ⚡ 4 étapes | Apache 2.0 ✅ | Rapide + qualité |
| **FLUX.2 Klein 9B** | ⚡ 4 étapes | Non-commercial | Qualité maximale rapide |
| **SD 3.5 Large Turbo** | ⚡ 4 étapes | Stability AI ⚠️ | Rapidité |
| **SD 3.5 Medium** | 30 étapes | Stability AI ⚠️ | Polyvalent léger |
| **SD 3.5 Large** | 30 étapes | Stability AI ⚠️ | Haute qualité |
| **ERNIE-Image Turbo** | ⚡ 8 étapes | Apache 2.0 ✅ | Texte dans l'image |
| **Z-Image** | 28 étapes | Apache 2.0 ✅ | Qualité polyvalente |
| **Qwen-Image 2512** | 30 étapes | Apache 2.0 ✅ | Réalisme humain |
| **Ideogram 4** | 12 étapes | Ideogram | Rendu de texte |
| **FHDR Uncensored** | 20 étapes | Non-commercial | Sans censure |

> ✅ = usage commercial autorisé · ⚠️ = usage personnel/non-commercial

### 💡 Quel modèle choisir ?

- **Vous débutez ?** → **FLUX.1 schnell** (le plus rapide)
- **Meilleure qualité rapide ?** → **FLUX.2 Klein 9B** ou **Qwen-Image 2512**
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
| 🖼️ **Génération** | 1 à 4 images par lot, 5 formats |
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
├── registry.py            ← Définition des 11 modèles
├── prompt_enhancer.py     ← Enrichissement & traduction (LLM)
├── gpu_info.py            ← Détection VRAM
├── db.py                  ← Historique & statistiques
├── config.py              ← Configuration des chemins
├── requirements.txt       ← Dépendances Python
├── templates/             ← Pages HTML
├── static/                ← CSS + JavaScript
├── docs/                  ← Documentation
│   ├── ADD_MODEL_FR.md    ← Comment ajouter un modèle (FR)
│   └── ADD_MODEL_EN.md    ← How to add a model (EN)
│
├── bin/                   ← sd-cli.exe (téléchargé auto)
├── models/                ← GGUF + VAE + encodeurs (téléchargés auto)
└── output/                ← Vos images générées
```

---

## ➕ Ajouter un modèle

L'application est conçue pour être **extensible**. Vous pouvez ajouter n'importe
quel modèle GGUF compatible avec `stable-diffusion.cpp`.

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
Ce moteur est reconnu pour faire tourner FLUX, Qwen-Image, Stable Diffusion 3.5,
Z-Image, ERNIE, Ideogram 4 et bien d'autres au format **GGUF** (quantifié).

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
