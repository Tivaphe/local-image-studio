# 🎭 Visage fidèle (PuLID) — Guide

PuLID permet de **conserver le visage d'une photo** dans vos générations, sans
ré-entraîner le modèle ni altérer le reste de l'image (contrairement à une LoRA
d'identité, qui « imprime » le visage partout). sd-cli prend en charge PuLID
uniquement pour les modèles **FLUX**.

## En trois étapes

### 1. Télécharger les poids PuLID (une fois)

Onglet **Modèles → 🎭 Visage fidèle (PuLID)** → « Télécharger (~1,14 Go) ».
Les poids officiels sont ceux de `guozinan/PuLID` (`pulid_flux_v0.9.1.safetensors`).

⚠️ La version **v0.9.x uniquement** est supportée par sd-cli. Les poids v1.1
(clés `id_adapter_attn_layers.*`) ne sont **pas** compatibles.

### 2. Créer l'empreinte d'identité d'un portrait (une fois par personne)

Le moteur a besoin d'un fichier `.pulidembd` (un tensor gguf `pulid_id`,
typiquement 2048×32 en F16, ~131 Ko). On le produit avec le script fourni,
`scripts/pulid_extract_id.py` — la référence officielle de stable-diffusion.cpp,
qui dépend de PyTorch.

```bash
# a) Installer la pile externe (une fois, dans un venv dédié si possible)
python3 -m venv /tmp/pulidenv && source /tmp/pulidenv/bin/activate
pip install torch torchvision insightface facexlib opencv-python gguf huggingface_hub Pillow numpy safetensors

# b) Récupérer le dépôt ToTheBeginning/PuLID (contient pulid/ et eva_clip/)
git clone https://github.com/ToTheBeginning/PuLID /tmp/PuLID
export PYTHONPATH=/tmp/PuLID:$PYTHONPATH

# c) Lancer l'extraction (détecteur antelopev2 téléchargé automatiquement au 1er run)
python scripts/pulid_extract_id.py \
  --portrait /chemin/vers/photo.jpg \
  --pulid-weights models/pulid/pulid_flux_v0.9.1.safetensors \
  --out portraits/prenom.pulidembd
```

Conseils photo : visage de face, bien éclairé, net, sans lunettes sombres ni
mains devant le visage. `insightface` détecte et aligne automatiquement. Si
aucune face n'est détectée, le script échoue explicitement.

L'empreinte `portraits/prenom.pulidembd` reste **locale** à votre machine
(le dossier `portraits/` est ignoré par Git). Vous pouvez associer la même
photo `prenom.jpg` à côté du `.pulidembd` pour afficher la vignette dans
l'onglet Modèles.

### 3. Générer avec ce visage

Sur la page **Générer**, section « ✨ Qualité, Détails & Agrandissement » →
« 🎭 Visage fidèle (PuLID) » :

1. choisissez le portrait dans la liste (les empreintes présentes dans
   `portraits/` apparaissent automatiquement) ;
2. réglez la **Force de l'empreinte** — 0,7 à 1,2 est le plus naturel ;
   1,0 par défaut ; 0 désactive l'injection (l'image est alors identique à une
   génération sans PuLID, à seed égal) ;
3. générez avec **FLUX.1 Schnell, FLUX.1 Dev ou FLUX.1 FHDR** — les autres
   architectures ne sont pas compatibles (le sélecteur est grisé).

## Fonctionnement interne

- CLI : `--pulid-weights … --pulid-id-embedding … --pulid-id-weight <w>` —
  les trois options sont requises ensemble.
- Le `.pulidembd` est un container **gguf** standard : un tensor `pulid_id`,
  shape `[2048, 32]` (token_dim, num_tokens), F16 (F32/BF16 acceptés),
  métadonnée `general.architecture="pulid"` et `pulid.version=1`.
- Exemple FLUX Schnell : cfg 1.0, euler, 4 steps. Pour FLUX Dev : ajoutez
  `--guidance 3.5` et 20 steps (les presets du modèle font déjà cela).

## Dépannage

- **« Les poids PuLID-FLUX ne sont pas installés »** → Modèles → section PuLID →
  Télécharger.
- **« Empreinte de portrait introuvable »** → vérifiez que `portraits/*.pulidembd`
  existe et fait plus de 50 Ko (le script l'écrit lui-même).
- **Script d'extraction qui échoue sur `insightface`** → vérifiez que le modèle
  ONNX `antelopev2` a pu être téléchargé (connexion Internet au premier run),
  et que `PYTHONPATH` pointe bien sur le dépôt PuLID.
- **Visage déformé / trop « copié »** → baissez la force (0,6–0,8) ; une empreinte
  est plus ou moins fidèle selon la qualité du portrait.
- **PuLID + Hires Fix** : l'empreinte est propagée à la passe haute résolution
  automatiquement.

## Confidentialité

Les photos de portraits et les empreintes ne quittent jamais votre machine.
Le dossier `portraits/` n'est versionné ni envoyé nulle part (hors téléchargements
insightface/PuLID initiaux depuis Hugging Face / GitHub).
