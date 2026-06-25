# Planning Manager

Application desktop Python pour gerer des utilisateurs, des etudes/projets, des taches et generer un planning local.

## Lancer en developpement

```bat
cd Base
py app_v25_planner.py
```

Les donnees sont sauvegardees dans:

```text
%LOCALAPPDATA%\MindyaPlanningManager
```

Fichiers crees automatiquement:

- `users.json`
- `projects.json`
- `assignments.json`
- `blocks.json`
- `settings.json`

## Logique planning

- 1 creneau = 30 minutes.
- 1 jour complet = 17 creneaux = 8h30.
- Chaque utilisateur a une capacite par jour de semaine.
- Un jour special peut mettre une capacite reduite ou `0` pour une absence.
- Les taches sont triees par priorite, puis planifiees automatiquement.
- Passer une tache en priorite `5` la remonte au prochain recalcul et decale le reste.
- Le dashboard affiche une ligne par utilisateur et 17 colonnes de creneaux.
- La vue `Jour` affiche une journee; la vue `Semaine` affiche les 5 jours ouvrables.
- Les absences completes ou par creneau sont visibles en rouge.
- Les creneaux non travailles a cause d'une capacite reduite sont grises.
- Depuis une case du dashboard, on peut couper une tache puis la coller sur une autre case: elle est forcee a ce nouveau depart et le reste est recalcule.
- Depuis une case du dashboard, on peut ajouter une absence sur un ou plusieurs creneaux: les taches presentes sont decalees au recalcul.

## Generer un exe

Installer PyInstaller:

```bat
py -m pip install pyinstaller
```

Puis:

```bat
py -m PyInstaller --onefile --windowed --name PlanningManager Base\app_v25_planner.py
```

L'executable sera genere dans `dist\PlanningManager.exe`.
