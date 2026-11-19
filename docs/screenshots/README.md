# Captures d'écran

Les captures ne sont pas encore générées dans le dépôt. Pour les produire **sur votre machine**
(avec un navigateur installé), une seule commande suffit :

```bash
pip install playwright
playwright install chromium
python3 app.py --no-browser          # terminal 1 : l'app sur :7860
python3 scripts/take-screenshots.py  # terminal 2 : écrit les JPG ici
git add docs/screenshots && git commit -m "docs: captures d'écran"
```

Fichiers générés : `generate-dark.jpg`, `generate-light.jpg`, `edit-dark.jpg`,
`history-dark.jpg`, `models-dark.jpg`, `settings-light.jpg`.

Une fois les JPG présents, la grille ci-dessous (identique dans les README FR/EN)
s'affiche telle quelle :

| | |
|---|---|
| ![Générer, thème sombre](generate-dark.jpg) | ![Générer, thème clair](generate-light.jpg) |
| ![Édition, thème sombre](edit-dark.jpg) | ![Historique, thème sombre](history-dark.jpg) |
| ![Modèles, thème sombre](models-dark.jpg) | ![Paramètres, thème clair](settings-light.jpg) |
