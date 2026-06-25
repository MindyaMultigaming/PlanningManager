# app_v25_planner.py
"""
Planificateur multi-employés v25
--------------------------------
Version ergonomique basée sur app_v24.py.

Objectifs de cette version :
- interface plus claire avec onglets : Planning, Tâches passives, Employés, Projets ;
- compatibilité avec les fichiers JSON existants : users.json, projects.json, calendar.json,
  user_constraints.json, passive_tasks.json ;
- attribution rapide des tâches avec durée multi-blocs ;
- filtres par utilisateur et projet ;
- gestion plus propre des employés, absences, projets et tâches ;
- sauvegarde automatique + sauvegarde manuelle + backup JSON ;
- annuler/rétablir pour les actions principales.

Dépendances :
- Python 3.10+
- ttkbootstrap recommandé : pip install ttkbootstrap
- tkcalendar optionnel : pip install tkcalendar
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
import tkinter.ttk as ttk_std

try:
    import ttkbootstrap as ttk  # type: ignore
    from ttkbootstrap.constants import BOTH, LEFT, RIGHT, TOP, BOTTOM, X, Y, VERTICAL, HORIZONTAL, END, W, E, N, S, CENTER
    TT_BOOTSTRAP_AVAILABLE = True
except Exception:
    ttk = ttk_std  # type: ignore
    TT_BOOTSTRAP_AVAILABLE = False
    BOTH = tk.BOTH
    LEFT = tk.LEFT
    RIGHT = tk.RIGHT
    TOP = tk.TOP
    BOTTOM = tk.BOTTOM
    X = tk.X
    Y = tk.Y
    VERTICAL = tk.VERTICAL
    HORIZONTAL = tk.HORIZONTAL
    END = tk.END
    W = tk.W
    E = tk.E
    N = tk.N
    S = tk.S
    CENTER = tk.CENTER

try:
    from tkcalendar import DateEntry  # type: ignore
    TKCALENDAR_AVAILABLE = True
except Exception:
    DateEntry = None  # type: ignore
    TKCALENDAR_AVAILABLE = False


# -----------------------------------------------------------------------------
# Constantes et configuration
# -----------------------------------------------------------------------------

APP_TITLE = "Planificateur employés & tâches — v25"
APP_SIZE = "1420x860"

BASE_DIR = Path(__file__).resolve().parent
DATA_FILES = {
    "users": BASE_DIR / "users.json",
    "projects": BASE_DIR / "projects.json",
    "calendar": BASE_DIR / "calendar.json",
    "constraints": BASE_DIR / "user_constraints.json",
    "passive": BASE_DIR / "passive_tasks.json",
}
BACKUP_DIR = BASE_DIR / "planner_backups"

DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
BLOCK_LABELS = ["Bloc 1", "Bloc 2", "Bloc 3", "Bloc 4"]
DEFAULT_PROJECT_COLOR = "#87CEEB"
DEFAULT_EMPTY_COLOR = "#f3f4f6"
DEFAULT_BUSY_COLOR = "#d9d9d9"
ABSENCE_COLOR = "#ffe3e3"
FILTERED_COLOR = "#eeeeee"

# Lundi de référence historique de la v24.
START_DATE = datetime(2025, 9, 8)


# -----------------------------------------------------------------------------
# Utilitaires JSON / dates
# -----------------------------------------------------------------------------

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[load_json] Erreur lecture {path.name}: {exc}")
        return default


def save_json(path: Path, data: Any) -> None:
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as exc:
        print(f"[save_json] Erreur écriture {path.name}: {exc}")
        messagebox.showerror("Erreur sauvegarde", f"Impossible de sauvegarder {path.name}:\n{exc}")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def to_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def week_offset_from_monday(monday: datetime) -> int:
    return (monday - START_DATE).days // 7


def normalize_calendar_dict(raw: Any) -> Dict[Tuple[int, int, int], Dict[str, str]]:
    """Convertit les clés JSON 'w,d,b' vers des tuples (week_offset, day, block)."""
    out: Dict[Tuple[int, int, int], Dict[str, str]] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            if isinstance(key, str):
                parts = [int(p) for p in key.split(",") if p != ""]
            elif isinstance(key, (tuple, list)):
                parts = [int(p) for p in key]
            else:
                continue
            if len(parts) == 2:
                w, d, b = 0, parts[0], parts[1]
            elif len(parts) >= 3:
                w, d, b = parts[0], parts[1], parts[2]
            else:
                continue
            if isinstance(value, dict):
                out[(w, d, b)] = {
                    "user": str(value.get("user", "")),
                    "project": str(value.get("project", "")),
                    "task": str(value.get("task", "")),
                }
        except Exception as exc:
            print(f"[normalize_calendar_dict] Clé ignorée {key!r}: {exc}")
    return out


def serialize_calendar(calendar: Dict[Tuple[int, int, int], Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {f"{w},{d},{b}": value for (w, d, b), value in sorted(calendar.items())}


def safe_color(value: Any, fallback: str = DEFAULT_BUSY_COLOR) -> str:
    if isinstance(value, str) and value.startswith("#") and len(value) in (4, 7):
        return value
    return fallback


def deep_copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

class PlannerApp:
    def __init__(self) -> None:
        if TT_BOOTSTRAP_AVAILABLE:
            self.root = ttk.Window(themename="flatly")  # type: ignore[attr-defined]
        else:
            self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(APP_SIZE)
        self.root.minsize(1180, 720)

        self.users: List[str] = []
        self.user_constraints: Dict[str, Dict[str, Any]] = {}
        self.projects: List[Dict[str, Any]] = []
        self.calendar_data: Dict[Tuple[int, int, int], Dict[str, str]] = {}
        self.passive_tasks: List[Dict[str, Any]] = []

        self.current_monday = datetime.combine(monday_of(date.today()), datetime.min.time())
        self.history: List[Dict[str, Any]] = []
        self.redo_history: List[Dict[str, Any]] = []

        self.filter_user_var = tk.StringVar(value="Tous")
        self.filter_project_var = tk.StringVar(value="Tous")
        self.status_var = tk.StringVar(value="Prêt")
        self.week_label_var = tk.StringVar()

        self.calendar_buttons: Dict[Tuple[int, int], tk.Button] = {}
        self.calendar_headers: List[ttk.Label] = []
        self.passive_tree: Optional[ttk.Treeview] = None
        self.employee_tree: Optional[ttk.Treeview] = None
        self.project_tree: Optional[ttk.Treeview] = None
        self.task_tree: Optional[ttk.Treeview] = None
        self.selected_project_id: Optional[str] = None

        self._load_all_data()
        self._build_ui()
        self._bind_shortcuts()
        self.refresh_all()
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Chargement / sauvegarde
    # ------------------------------------------------------------------

    def _load_all_data(self) -> None:
        self.users = load_json(DATA_FILES["users"], [])
        if not isinstance(self.users, list):
            self.users = []
        self.users = sorted({str(u).strip() for u in self.users if str(u).strip()}, key=str.lower)

        self.user_constraints = load_json(DATA_FILES["constraints"], {})
        if not isinstance(self.user_constraints, dict):
            self.user_constraints = {}

        self.projects = load_json(DATA_FILES["projects"], [])
        if not isinstance(self.projects, list):
            self.projects = []

        raw_calendar = load_json(DATA_FILES["calendar"], {})
        self.calendar_data = normalize_calendar_dict(raw_calendar)

        self.passive_tasks = load_json(DATA_FILES["passive"], [])
        if not isinstance(self.passive_tasks, list):
            self.passive_tasks = []

        self._normalize_data()
        self.save_all(silent=True)

    def _normalize_data(self) -> None:
        # Employés
        for user in self.users:
            self.user_constraints.setdefault(user, {"weekly_pattern": [1, 1, 1, 1, 1], "holidays": []})
            pattern = self.user_constraints[user].get("weekly_pattern", [1, 1, 1, 1, 1])
            if not isinstance(pattern, list):
                pattern = [1, 1, 1, 1, 1]
            pattern = (pattern + [1, 1, 1, 1, 1])[:5]
            self.user_constraints[user]["weekly_pattern"] = [1 if int(x) else 0 for x in pattern]
            holidays = self.user_constraints[user].get("holidays", [])
            if not isinstance(holidays, list):
                holidays = []
            self.user_constraints[user]["holidays"] = sorted({str(h) for h in holidays if to_date(str(h))})

        # Nettoyer contraintes d'anciens employés uniquement si elles sont invalides ? On conserve volontairement.

        # Projets
        normalized_projects = []
        seen_ids = set()
        seen_names = set()
        for project in self.projects:
            if not isinstance(project, dict):
                continue
            name = str(project.get("name", "")).strip()
            if not name:
                continue
            pid = str(project.get("id", "")).strip() or uuid.uuid4().hex
            if pid in seen_ids:
                pid = uuid.uuid4().hex
            seen_ids.add(pid)
            if name.lower() in seen_names:
                name = f"{name} ({pid[:4]})"
            seen_names.add(name.lower())
            tasks = project.get("tasks", [])
            if not isinstance(tasks, list):
                tasks = []
            clean_tasks = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_name = str(task.get("name", "")).strip()
                if not task_name:
                    continue
                try:
                    duration = max(1, int(task.get("duration", 1)))
                except Exception:
                    duration = 1
                clean_tasks.append({"name": task_name, "duration": duration})
            normalized_projects.append({
                "id": pid,
                "name": name,
                "tasks": sorted(clean_tasks, key=lambda t: t["name"].lower()),
                "color": safe_color(project.get("color"), DEFAULT_PROJECT_COLOR),
            })
        self.projects = sorted(normalized_projects, key=lambda p: p["name"].lower())

        # Tâches passives
        clean_passive = []
        for task in self.passive_tasks:
            if not isinstance(task, dict):
                continue
            project = str(task.get("project", "")).strip()
            task_name = str(task.get("task", "")).strip()
            user = str(task.get("user", "")).strip()
            start_date = str(task.get("start_date", "")).strip()
            if not project or not task_name or not to_date(start_date):
                continue
            try:
                duration = max(1, int(task.get("duration", 1)))
            except Exception:
                duration = 1
            clean_passive.append({
                "id": str(task.get("id", "")).strip() or uuid.uuid4().hex,
                "project": project,
                "task": task_name,
                "duration": duration,
                "start_date": start_date,
                "user": user,
                "note": str(task.get("note", "")),
            })
        self.passive_tasks = clean_passive

    def snapshot(self) -> Dict[str, Any]:
        return {
            "users": list(self.users),
            "constraints": deep_copy_json(self.user_constraints),
            "projects": deep_copy_json(self.projects),
            "calendar": serialize_calendar(self.calendar_data),
            "passive": deep_copy_json(self.passive_tasks),
        }

    def push_history(self) -> None:
        self.history.append(self.snapshot())
        if len(self.history) > 50:
            self.history.pop(0)
        self.redo_history.clear()

    def restore_snapshot(self, snap: Dict[str, Any]) -> None:
        self.users = sorted(snap.get("users", []), key=str.lower)
        self.user_constraints = snap.get("constraints", {})
        self.projects = snap.get("projects", [])
        self.calendar_data = normalize_calendar_dict(snap.get("calendar", {}))
        self.passive_tasks = snap.get("passive", [])
        self._normalize_data()
        self.save_all(silent=True)
        self.refresh_all()

    def save_all(self, silent: bool = False) -> None:
        save_json(DATA_FILES["users"], self.users)
        save_json(DATA_FILES["constraints"], self.user_constraints)
        save_json(DATA_FILES["projects"], self.projects)
        save_json(DATA_FILES["calendar"], serialize_calendar(self.calendar_data))
        save_json(DATA_FILES["passive"], self.passive_tasks)
        if not silent:
            self.set_status("Sauvegarde terminée")

    def backup_data(self) -> None:
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"backup_{stamp}"
        dest.mkdir(exist_ok=True)
        for path in DATA_FILES.values():
            if path.exists():
                shutil.copy2(path, dest / path.name)
        self.set_status(f"Backup créé : {dest.name}")
        messagebox.showinfo("Backup", f"Backup créé dans :\n{dest}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_top_bar()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        self.tab_planning = ttk.Frame(self.notebook)
        self.tab_passive = ttk.Frame(self.notebook)
        self.tab_employees = ttk.Frame(self.notebook)
        self.tab_projects = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_planning, text="📅 Planning")
        self.notebook.add(self.tab_passive, text="⏳ Tâches passives")
        self.notebook.add(self.tab_employees, text="👥 Employés")
        self.notebook.add(self.tab_projects, text="📦 Projets & tâches")

        self._build_planning_tab()
        self._build_passive_tab()
        self._build_employees_tab()
        self._build_projects_tab()

        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))

    def _build_top_bar(self) -> None:
        top = ttk.Frame(self.root)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        top.columnconfigure(8, weight=1)

        ttk.Button(top, text="◀ Semaine", command=self.prev_week).grid(row=0, column=0, padx=3)
        ttk.Button(top, text="Aujourd'hui", command=self.goto_today).grid(row=0, column=1, padx=3)
        ttk.Button(top, text="Semaine ▶", command=self.next_week).grid(row=0, column=2, padx=3)

        ttk.Label(top, textvariable=self.week_label_var, font=("Segoe UI", 12, "bold")).grid(row=0, column=3, padx=18)

        ttk.Label(top, text="Filtre employé").grid(row=0, column=4, padx=(12, 4))
        self.filter_user_cb = ttk.Combobox(top, textvariable=self.filter_user_var, state="readonly", width=18)
        self.filter_user_cb.grid(row=0, column=5, padx=3)
        self.filter_user_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_planning())

        ttk.Label(top, text="Filtre projet").grid(row=0, column=6, padx=(12, 4))
        self.filter_project_cb = ttk.Combobox(top, textvariable=self.filter_project_var, state="readonly", width=22)
        self.filter_project_cb.grid(row=0, column=7, padx=3)
        self.filter_project_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_planning())

        ttk.Button(top, text="Sauver", command=lambda: self.save_all(silent=False)).grid(row=0, column=9, padx=3, sticky="e")
        ttk.Button(top, text="Backup", command=self.backup_data).grid(row=0, column=10, padx=3, sticky="e")
        ttk.Button(top, text="Annuler", command=self.undo).grid(row=0, column=11, padx=3, sticky="e")
        ttk.Button(top, text="Rétablir", command=self.redo).grid(row=0, column=12, padx=3, sticky="e")

    def _build_planning_tab(self) -> None:
        self.tab_planning.columnconfigure(0, weight=1)
        self.tab_planning.rowconfigure(1, weight=1)

        help_frame = ttk.Frame(self.tab_planning)
        help_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Label(
            help_frame,
            text="Clique sur un bloc pour attribuer, modifier ou supprimer une tâche. Les tâches longues se posent automatiquement sur plusieurs blocs.",
            anchor="w",
        ).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(help_frame, text="+ Tâche rapide", command=self.open_assignment_dialog).pack(side=RIGHT, padx=4)
        ttk.Button(help_frame, text="Nettoyer semaine affichée", command=self.clear_current_week).pack(side=RIGHT, padx=4)

        grid_frame = ttk.LabelFrame(self.tab_planning, text="Planning semaine")
        grid_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        for col in range(6):
            grid_frame.columnconfigure(col, weight=1)
        for row in range(6):
            grid_frame.rowconfigure(row, weight=1)

        ttk.Label(grid_frame, text="", anchor="center").grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.calendar_headers = []
        for day_index, day_name in enumerate(DAYS):
            lbl = ttk.Label(grid_frame, text=day_name, anchor="center", font=("Segoe UI", 11, "bold"))
            lbl.grid(row=0, column=day_index + 1, sticky="nsew", padx=4, pady=4)
            self.calendar_headers.append(lbl)

        for block_index, label in enumerate(BLOCK_LABELS):
            ttk.Label(grid_frame, text=label, anchor="center", font=("Segoe UI", 10, "bold")).grid(
                row=block_index + 1, column=0, sticky="nsew", padx=4, pady=4
            )
            for day_index in range(5):
                btn = tk.Button(
                    grid_frame,
                    text="",
                    wraplength=185,
                    justify="center",
                    relief="groove",
                    borderwidth=1,
                    bg=DEFAULT_EMPTY_COLOR,
                    activebackground="#e2e8f0",
                    command=lambda d=day_index, b=block_index: self.open_assignment_dialog(d, b),
                )
                btn.grid(row=block_index + 1, column=day_index + 1, sticky="nsew", padx=4, pady=4, ipady=16)
                self.calendar_buttons[(day_index, block_index)] = btn

        summary = ttk.LabelFrame(self.tab_planning, text="Résumé semaine")
        summary.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        summary.columnconfigure(0, weight=1)
        self.week_summary_var = tk.StringVar()
        ttk.Label(summary, textvariable=self.week_summary_var, anchor="w").grid(row=0, column=0, sticky="ew", padx=8, pady=6)

    def _build_passive_tab(self) -> None:
        self.tab_passive.columnconfigure(0, weight=1)
        self.tab_passive.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.tab_passive)
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="+ Ajouter tâche passive", command=self.open_passive_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer sélection", command=self.delete_selected_passive_task).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Convertir en planning", command=self.convert_passive_to_calendar).pack(side=LEFT, padx=3)
        ttk.Label(toolbar, text="Les tâches passives sont des tâches à planifier plus tard ou à garder en attente.").pack(side=LEFT, padx=18)

        columns = ("start", "duration", "user", "project", "task", "note")
        self.passive_tree = ttk.Treeview(self.tab_passive, columns=columns, show="headings", height=18)
        headers = {
            "start": "Début",
            "duration": "Jours ouvrés",
            "user": "Employé",
            "project": "Projet",
            "task": "Tâche",
            "note": "Note",
        }
        widths = {"start": 95, "duration": 90, "user": 140, "project": 190, "task": 280, "note": 360}
        for col in columns:
            self.passive_tree.heading(col, text=headers[col])
            self.passive_tree.column(col, width=widths[col], anchor="w")
        self.passive_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        sb = ttk.Scrollbar(self.tab_passive, orient=VERTICAL, command=self.passive_tree.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        self.passive_tree.configure(yscrollcommand=sb.set)
        self.passive_tree.bind("<Double-1>", lambda e: self.open_passive_dialog(edit=True))

    def _build_employees_tab(self) -> None:
        self.tab_employees.columnconfigure(0, weight=1)
        self.tab_employees.columnconfigure(1, weight=1)
        self.tab_employees.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.tab_employees)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="+ Ajouter employé", command=self.add_employee_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Renommer", command=self.rename_employee_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer", command=self.delete_employee).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Modifier disponibilités", command=self.edit_employee_constraints).pack(side=LEFT, padx=3)

        columns = ("name", "availability", "holidays")
        self.employee_tree = ttk.Treeview(self.tab_employees, columns=columns, show="headings", height=18)
        self.employee_tree.heading("name", text="Employé")
        self.employee_tree.heading("availability", text="Disponibilité hebdo")
        self.employee_tree.heading("holidays", text="Absences spécifiques")
        self.employee_tree.column("name", width=220, anchor="w")
        self.employee_tree.column("availability", width=360, anchor="w")
        self.employee_tree.column("holidays", width=420, anchor="w")
        self.employee_tree.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.employee_tree.bind("<Double-1>", lambda e: self.edit_employee_constraints())

    def _build_projects_tab(self) -> None:
        self.tab_projects.columnconfigure(0, weight=1)
        self.tab_projects.columnconfigure(1, weight=1)
        self.tab_projects.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.tab_projects)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="+ Projet", command=self.add_project_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Renommer projet", command=self.rename_project_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Couleur", command=self.choose_project_color).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer projet", command=self.delete_project).pack(side=LEFT, padx=3)
        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=10)
        ttk.Button(toolbar, text="+ Tâche", command=self.add_task_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Modifier tâche", command=self.edit_task_dialog).pack(side=LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer tâche", command=self.delete_task).pack(side=LEFT, padx=3)

        project_frame = ttk.LabelFrame(self.tab_projects, text="Projets")
        project_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        project_frame.rowconfigure(0, weight=1)
        project_frame.columnconfigure(0, weight=1)

        self.project_tree = ttk.Treeview(project_frame, columns=("name", "tasks", "color"), show="headings", height=18)
        self.project_tree.heading("name", text="Projet")
        self.project_tree.heading("tasks", text="Nb tâches")
        self.project_tree.heading("color", text="Couleur")
        self.project_tree.column("name", width=280, anchor="w")
        self.project_tree.column("tasks", width=80, anchor="center")
        self.project_tree.column("color", width=90, anchor="center")
        self.project_tree.grid(row=0, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", lambda e: self.on_project_selected())
        self.project_tree.bind("<Double-1>", lambda e: self.rename_project_dialog())

        task_frame = ttk.LabelFrame(self.tab_projects, text="Tâches du projet sélectionné")
        task_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))
        task_frame.rowconfigure(0, weight=1)
        task_frame.columnconfigure(0, weight=1)

        self.task_tree = ttk.Treeview(task_frame, columns=("name", "duration"), show="headings", height=18)
        self.task_tree.heading("name", text="Tâche")
        self.task_tree.heading("duration", text="Durée blocs")
        self.task_tree.column("name", width=420, anchor="w")
        self.task_tree.column("duration", width=100, anchor="center")
        self.task_tree.grid(row=0, column=0, sticky="nsew")
        self.task_tree.bind("<Double-1>", lambda e: self.edit_task_dialog())

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-s>", lambda e: self.save_all(silent=False))
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<F5>", lambda e: self.refresh_all())
        self.root.bind("<Control-n>", lambda e: self.open_assignment_dialog())

    # ------------------------------------------------------------------
    # Refresh UI
    # ------------------------------------------------------------------

    def refresh_all(self) -> None:
        self._normalize_data()
        self.refresh_filters()
        self.refresh_planning()
        self.refresh_passive_tree()
        self.refresh_employee_tree()
        self.refresh_project_tree()
        self.set_status("Interface actualisée")

    def refresh_filters(self) -> None:
        users = ["Tous"] + sorted(self.users, key=str.lower)
        if self.filter_user_var.get() not in users:
            self.filter_user_var.set("Tous")
        self.filter_user_cb["values"] = users

        project_names = ["Tous"] + [p["name"] for p in sorted(self.projects, key=lambda p: p["name"].lower())]
        if self.filter_project_var.get() not in project_names:
            self.filter_project_var.set("Tous")
        self.filter_project_cb["values"] = project_names

    def refresh_planning(self) -> None:
        week_start = self.current_monday.date()
        week_end = week_start + timedelta(days=4)
        self.week_label_var.set(f"Semaine du {week_start.strftime('%d/%m/%Y')} au {week_end.strftime('%d/%m/%Y')}")

        for d, lbl in enumerate(self.calendar_headers):
            day_date = week_start + timedelta(days=d)
            lbl.configure(text=f"{DAYS[d]}\n{day_date.strftime('%d/%m/%Y')}")

        week_offset = week_offset_from_monday(self.current_monday)
        filter_user = self.filter_user_var.get()
        filter_project = self.filter_project_var.get()
        counts_by_user: Dict[str, int] = {}
        counts_by_project: Dict[str, int] = {}

        for day_index in range(5):
            day_date = week_start + timedelta(days=day_index)
            for block_index in range(4):
                key = (week_offset, day_index, block_index)
                btn = self.calendar_buttons[(day_index, block_index)]
                entry = self.calendar_data.get(key)

                absent_hint = ""
                absent_for_filter = False
                if filter_user != "Tous" and self.is_user_absent(filter_user, day_date):
                    absent_for_filter = True
                    absent_hint = "\n(absent)"

                if not entry:
                    bg = ABSENCE_COLOR if absent_for_filter else DEFAULT_EMPTY_COLOR
                    text = f"Libre{absent_hint}" if absent_for_filter else "Libre"
                    btn.configure(text=text, bg=bg, fg="black")
                    continue

                user = entry.get("user", "")
                project = entry.get("project", "")
                task = entry.get("task", "")
                visible = True
                if filter_user != "Tous" and user != filter_user:
                    visible = False
                if filter_project != "Tous" and project != filter_project:
                    visible = False

                counts_by_user[user] = counts_by_user.get(user, 0) + 1
                counts_by_project[project] = counts_by_project.get(project, 0) + 1

                if not visible:
                    btn.configure(text="Masqué par filtre", bg=FILTERED_COLOR, fg="#777777")
                    continue

                project_obj = self.find_project_by_name(project)
                color = safe_color(project_obj.get("color") if project_obj else None, DEFAULT_BUSY_COLOR)
                warning = " ⚠ absent" if self.is_user_absent(user, day_date) else ""
                btn.configure(text=f"{project}\n{task}\n👤 {user}{warning}", bg=color, fg="black")

        user_bits = ", ".join(f"{u}: {n} bloc(s)" for u, n in sorted(counts_by_user.items(), key=lambda x: x[0].lower())) or "Aucun bloc planifié"
        project_bits = ", ".join(f"{p}: {n}" for p, n in sorted(counts_by_project.items(), key=lambda x: x[0].lower())) or "Aucun projet"
        self.week_summary_var.set(f"Charge par employé — {user_bits}    |    Charge par projet — {project_bits}")

    def refresh_passive_tree(self) -> None:
        if self.passive_tree is None:
            return
        self.passive_tree.delete(*self.passive_tree.get_children())
        for task in sorted(self.passive_tasks, key=lambda t: (t.get("start_date", ""), t.get("project", ""), t.get("task", ""))):
            self.passive_tree.insert(
                "",
                END,
                iid=task["id"],
                values=(
                    task.get("start_date", ""),
                    task.get("duration", 1),
                    task.get("user", ""),
                    task.get("project", ""),
                    task.get("task", ""),
                    task.get("note", ""),
                ),
            )

    def refresh_employee_tree(self) -> None:
        if self.employee_tree is None:
            return
        self.employee_tree.delete(*self.employee_tree.get_children())
        for user in sorted(self.users, key=str.lower):
            constraints = self.user_constraints.get(user, {})
            pattern = constraints.get("weekly_pattern", [1, 1, 1, 1, 1])
            availability = ", ".join(DAYS[i] for i, flag in enumerate(pattern[:5]) if int(flag)) or "Aucun jour"
            holidays = ", ".join(constraints.get("holidays", [])) or "—"
            self.employee_tree.insert("", END, iid=user, values=(user, availability, holidays))

    def refresh_project_tree(self) -> None:
        if self.project_tree is None or self.task_tree is None:
            return
        selected = self.selected_project_id
        self.project_tree.delete(*self.project_tree.get_children())
        for project in sorted(self.projects, key=lambda p: p["name"].lower()):
            self.project_tree.insert(
                "",
                END,
                iid=project["id"],
                values=(project["name"], len(project.get("tasks", [])), project.get("color", "")),
            )
        if selected and selected in self.project_tree.get_children(""):
            self.project_tree.selection_set(selected)
        elif self.projects:
            first = sorted(self.projects, key=lambda p: p["name"].lower())[0]["id"]
            self.project_tree.selection_set(first)
            self.selected_project_id = first
        self.refresh_task_tree()

    def refresh_task_tree(self) -> None:
        if self.task_tree is None:
            return
        self.task_tree.delete(*self.task_tree.get_children())
        project = self.find_project_by_id(self.selected_project_id)
        if not project:
            return
        for index, task in enumerate(sorted(project.get("tasks", []), key=lambda t: t["name"].lower())):
            self.task_tree.insert("", END, iid=str(index), values=(task["name"], task["duration"]))

    def on_project_selected(self) -> None:
        if not self.project_tree:
            return
        sel = self.project_tree.selection()
        self.selected_project_id = sel[0] if sel else None
        self.refresh_task_tree()

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    # ------------------------------------------------------------------
    # Navigation semaine
    # ------------------------------------------------------------------

    def prev_week(self) -> None:
        self.current_monday -= timedelta(days=7)
        self.refresh_planning()

    def next_week(self) -> None:
        self.current_monday += timedelta(days=7)
        self.refresh_planning()

    def goto_today(self) -> None:
        self.current_monday = datetime.combine(monday_of(date.today()), datetime.min.time())
        self.refresh_planning()

    # ------------------------------------------------------------------
    # Planning actions
    # ------------------------------------------------------------------

    def open_assignment_dialog(self, day_index: Optional[int] = None, block_index: Optional[int] = None) -> None:
        if not self.users:
            messagebox.showwarning("Employés", "Ajoute au moins un employé avant de planifier une tâche.")
            self.notebook.select(self.tab_employees)
            return
        if not self.projects:
            messagebox.showwarning("Projets", "Ajoute au moins un projet avant de planifier une tâche.")
            self.notebook.select(self.tab_projects)
            return

        if day_index is None:
            day_index = 0
        if block_index is None:
            block_index = 0

        week_offset = week_offset_from_monday(self.current_monday)
        key = (week_offset, day_index, block_index)
        existing = self.calendar_data.get(key)

        top = self.make_dialog("Attribuer une tâche", "440x470")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Jour").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        day_var = tk.StringVar(value=DAYS[day_index])
        day_cb = ttk.Combobox(top, textvariable=day_var, values=DAYS, state="readonly")
        day_cb.grid(row=0, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Bloc").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        block_var = tk.StringVar(value=BLOCK_LABELS[block_index])
        block_cb = ttk.Combobox(top, textvariable=block_var, values=BLOCK_LABELS, state="readonly")
        block_cb.grid(row=1, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Employé").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        user_var = tk.StringVar(value=(existing.get("user") if existing else self.default_user()))
        user_cb = ttk.Combobox(top, textvariable=user_var, values=sorted(self.users, key=str.lower), state="readonly")
        user_cb.grid(row=2, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Projet").grid(row=3, column=0, sticky="w", padx=12, pady=8)
        project_names = [p["name"] for p in sorted(self.projects, key=lambda p: p["name"].lower())]
        project_var = tk.StringVar(value=(existing.get("project") if existing else project_names[0]))
        project_cb = ttk.Combobox(top, textvariable=project_var, values=project_names, state="readonly")
        project_cb.grid(row=3, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Tâche").grid(row=4, column=0, sticky="w", padx=12, pady=8)
        task_var = tk.StringVar(value=(existing.get("task") if existing else ""))
        task_cb = ttk.Combobox(top, textvariable=task_var, state="readonly")
        task_cb.grid(row=4, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Durée").grid(row=5, column=0, sticky="w", padx=12, pady=8)
        duration_var = tk.StringVar(value="1")
        duration_spin = ttk.Spinbox(top, from_=1, to=80, textvariable=duration_var, width=6)
        duration_spin.grid(row=5, column=1, sticky="w", padx=12, pady=8)

        mode_var = tk.StringVar(value="shift")
        mode_frame = ttk.LabelFrame(top, text="Si des blocs sont déjà occupés")
        mode_frame.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Radiobutton(mode_frame, text="Décaler automatiquement", variable=mode_var, value="shift").pack(anchor="w", padx=10, pady=3)
        ttk.Radiobutton(mode_frame, text="Écraser les blocs concernés", variable=mode_var, value="overwrite").pack(anchor="w", padx=10, pady=3)

        current_info = ttk.Label(top, text="", anchor="w")
        current_info.grid(row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        if existing:
            current_info.configure(text=f"Bloc actuel : {existing.get('project')} / {existing.get('task')} / {existing.get('user')}")
        else:
            current_info.configure(text="Bloc actuel : libre")

        def refresh_tasks(*_: Any) -> None:
            project = self.find_project_by_name(project_var.get())
            tasks = sorted(project.get("tasks", []), key=lambda t: t["name"].lower()) if project else []
            names = [t["name"] for t in tasks]
            task_cb["values"] = names
            if task_var.get() not in names:
                task_var.set(names[0] if names else "")
            selected_task = next((t for t in tasks if t["name"] == task_var.get()), None)
            if selected_task:
                duration_var.set(str(selected_task.get("duration", 1)))

        def on_task_selected(*_: Any) -> None:
            project = self.find_project_by_name(project_var.get())
            if not project:
                return
            task = next((t for t in project.get("tasks", []) if t["name"] == task_var.get()), None)
            if task:
                duration_var.set(str(task.get("duration", 1)))

        project_cb.bind("<<ComboboxSelected>>", refresh_tasks)
        task_cb.bind("<<ComboboxSelected>>", on_task_selected)
        refresh_tasks()

        buttons = ttk.Frame(top)
        buttons.grid(row=8, column=0, columnspan=2, sticky="ew", padx=12, pady=14)

        def save_assignment() -> None:
            try:
                d = DAYS.index(day_var.get())
                b = BLOCK_LABELS.index(block_var.get())
                duration = max(1, int(duration_var.get()))
            except Exception:
                messagebox.showerror("Erreur", "Jour, bloc ou durée invalide.")
                return
            user = user_var.get().strip()
            project = project_var.get().strip()
            task = task_var.get().strip()
            if not user or not project or not task:
                messagebox.showwarning("Champs manquants", "Sélectionne un employé, un projet et une tâche.")
                return
            self.push_history()
            if mode_var.get() == "overwrite":
                self.insert_task_overwrite(week_offset, d, b, user, project, task, duration)
            else:
                self.insert_task_shift(week_offset, d, b, user, project, task, duration)
            self.save_all(silent=True)
            self.refresh_planning()
            self.set_status(f"Tâche planifiée : {project} / {task} / {user}")
            top.destroy()

        def delete_current() -> None:
            d = DAYS.index(day_var.get())
            b = BLOCK_LABELS.index(block_var.get())
            k = (week_offset, d, b)
            if k not in self.calendar_data:
                top.destroy()
                return
            if not messagebox.askyesno("Supprimer", "Supprimer uniquement ce bloc ?"):
                return
            self.push_history()
            del self.calendar_data[k]
            self.save_all(silent=True)
            self.refresh_planning()
            self.set_status("Bloc supprimé")
            top.destroy()

        ttk.Button(buttons, text="Valider", command=save_assignment).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Supprimer bloc", command=delete_current).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=top.destroy).pack(side=RIGHT, padx=4)

    def insert_task_overwrite(self, week_offset: int, day_index: int, block_index: int, user: str, project: str, task: str, duration: int) -> None:
        w, d, b = week_offset, day_index, block_index
        for _ in range(duration):
            d, b, w = self.normalize_slot(w, d, b)
            self.calendar_data[(w, d, b)] = {"user": user, "project": project, "task": task}
            b += 1

    def insert_task_shift(self, week_offset: int, day_index: int, block_index: int, user: str, project: str, task: str, duration: int) -> None:
        w, d, b = week_offset, day_index, block_index
        placed = 0
        while placed < duration:
            d, b, w = self.normalize_slot(w, d, b)
            slot_date = (START_DATE + timedelta(days=d + 7 * w)).date()
            if self.is_user_absent(user, slot_date):
                b += 1
                continue
            if (w, d, b) in self.calendar_data:
                self.shift_slot_forward(w, d, b)
            self.calendar_data[(w, d, b)] = {"user": user, "project": project, "task": task}
            placed += 1
            b += 1

    def shift_slot_forward(self, week_offset: int, day_index: int, block_index: int) -> None:
        key = (week_offset, day_index, block_index)
        if key not in self.calendar_data:
            return
        entry = self.calendar_data[key]
        w, d, b = week_offset, day_index, block_index + 1
        while True:
            d, b, w = self.normalize_slot(w, d, b)
            slot_date = (START_DATE + timedelta(days=d + 7 * w)).date()
            user = entry.get("user", "")
            if self.is_user_absent(user, slot_date):
                b += 1
                continue
            next_key = (w, d, b)
            if next_key in self.calendar_data:
                self.shift_slot_forward(w, d, b)
            self.calendar_data[next_key] = entry
            del self.calendar_data[key]
            return

    @staticmethod
    def normalize_slot(week_offset: int, day_index: int, block_index: int) -> Tuple[int, int, int]:
        w, d, b = week_offset, day_index, block_index
        while b > 3:
            b -= 4
            d += 1
        while d > 4:
            d -= 5
            w += 1
        while b < 0:
            b += 4
            d -= 1
        while d < 0:
            d += 5
            w -= 1
        return d, b, w

    def clear_current_week(self) -> None:
        week_offset = week_offset_from_monday(self.current_monday)
        entries = [k for k in self.calendar_data if k[0] == week_offset]
        if not entries:
            messagebox.showinfo("Planning", "La semaine affichée est déjà vide.")
            return
        if not messagebox.askyesno("Nettoyer semaine", "Supprimer tous les blocs de la semaine affichée ?"):
            return
        self.push_history()
        for key in entries:
            del self.calendar_data[key]
        self.save_all(silent=True)
        self.refresh_planning()
        self.set_status("Semaine nettoyée")

    # ------------------------------------------------------------------
    # Tâches passives
    # ------------------------------------------------------------------

    def open_passive_dialog(self, edit: bool = False) -> None:
        selected_task = self.get_selected_passive_task() if edit else None
        top = self.make_dialog("Modifier tâche passive" if selected_task else "Ajouter tâche passive", "500x420")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Projet").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        project_names = [p["name"] for p in sorted(self.projects, key=lambda p: p["name"].lower())]
        project_var = tk.StringVar(value=selected_task.get("project") if selected_task else (project_names[0] if project_names else ""))
        project_cb = ttk.Combobox(top, textvariable=project_var, values=project_names, state="readonly")
        project_cb.grid(row=0, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Tâche").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        task_var = tk.StringVar(value=selected_task.get("task") if selected_task else "")
        task_entry = ttk.Entry(top, textvariable=task_var)
        task_entry.grid(row=1, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Employé").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        user_var = tk.StringVar(value=selected_task.get("user") if selected_task else self.default_user())
        user_cb = ttk.Combobox(top, textvariable=user_var, values=sorted(self.users, key=str.lower), state="readonly")
        user_cb.grid(row=2, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Début").grid(row=3, column=0, sticky="w", padx=12, pady=8)
        start_var = tk.StringVar(value=selected_task.get("start_date") if selected_task else date.today().isoformat())
        if TKCALENDAR_AVAILABLE and DateEntry is not None:
            start_entry = DateEntry(top, date_pattern="yyyy-mm-dd")
            try:
                start_entry.set_date(to_date(start_var.get()) or date.today())
            except Exception:
                pass
            start_entry.grid(row=3, column=1, sticky="w", padx=12, pady=8)
        else:
            start_entry = ttk.Entry(top, textvariable=start_var)
            start_entry.grid(row=3, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(top, text="Durée jours ouvrés").grid(row=4, column=0, sticky="w", padx=12, pady=8)
        duration_var = tk.StringVar(value=str(selected_task.get("duration", 1)) if selected_task else "1")
        ttk.Spinbox(top, from_=1, to=365, textvariable=duration_var, width=8).grid(row=4, column=1, sticky="w", padx=12, pady=8)

        ttk.Label(top, text="Note").grid(row=5, column=0, sticky="nw", padx=12, pady=8)
        note_text = tk.Text(top, height=5, wrap="word")
        note_text.grid(row=5, column=1, sticky="nsew", padx=12, pady=8)
        note_text.insert("1.0", selected_task.get("note", "") if selected_task else "")

        buttons = ttk.Frame(top)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=12)

        def save_passive() -> None:
            project = project_var.get().strip()
            task_name = task_var.get().strip()
            user = user_var.get().strip()
            if TKCALENDAR_AVAILABLE and DateEntry is not None and isinstance(start_entry, DateEntry):
                start = start_entry.get_date().isoformat()
            else:
                start = start_var.get().strip()
            try:
                duration = max(1, int(duration_var.get()))
            except Exception:
                messagebox.showerror("Erreur", "Durée invalide.")
                return
            if not project or not task_name or not to_date(start):
                messagebox.showwarning("Champs invalides", "Projet, tâche et date de début sont obligatoires.")
                return
            self.push_history()
            payload = {
                "id": selected_task.get("id") if selected_task else uuid.uuid4().hex,
                "project": project,
                "task": task_name,
                "user": user,
                "start_date": start,
                "duration": duration,
                "note": note_text.get("1.0", "end").strip(),
            }
            if selected_task:
                index = next((i for i, t in enumerate(self.passive_tasks) if t["id"] == selected_task["id"]), None)
                if index is not None:
                    self.passive_tasks[index] = payload
            else:
                self.passive_tasks.append(payload)
            self.save_all(silent=True)
            self.refresh_passive_tree()
            self.set_status("Tâche passive sauvegardée")
            top.destroy()

        ttk.Button(buttons, text="Valider", command=save_passive).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=top.destroy).pack(side=RIGHT, padx=4)

    def get_selected_passive_task(self) -> Optional[Dict[str, Any]]:
        if not self.passive_tree:
            return None
        sel = self.passive_tree.selection()
        if not sel:
            return None
        task_id = sel[0]
        return next((t for t in self.passive_tasks if t.get("id") == task_id), None)

    def delete_selected_passive_task(self) -> None:
        task = self.get_selected_passive_task()
        if not task:
            messagebox.showinfo("Tâches passives", "Sélectionne une tâche passive.")
            return
        if not messagebox.askyesno("Supprimer", f"Supprimer la tâche passive :\n{task.get('project')} / {task.get('task')} ?"):
            return
        self.push_history()
        self.passive_tasks = [t for t in self.passive_tasks if t.get("id") != task.get("id")]
        self.save_all(silent=True)
        self.refresh_passive_tree()
        self.set_status("Tâche passive supprimée")

    def convert_passive_to_calendar(self) -> None:
        task = self.get_selected_passive_task()
        if not task:
            messagebox.showinfo("Tâches passives", "Sélectionne une tâche passive à convertir.")
            return
        start = to_date(task.get("start_date", "")) or date.today()
        self.current_monday = datetime.combine(monday_of(start), datetime.min.time())
        day_index = start.weekday() if start.weekday() < 5 else 0
        self.push_history()
        # Ici on convertit jours ouvrés en blocs de 4/jour.
        duration_blocks = max(1, int(task.get("duration", 1))) * 4
        self.insert_task_shift(
            week_offset_from_monday(self.current_monday),
            day_index,
            0,
            task.get("user", ""),
            task.get("project", ""),
            task.get("task", ""),
            duration_blocks,
        )
        self.passive_tasks = [t for t in self.passive_tasks if t.get("id") != task.get("id")]
        self.save_all(silent=True)
        self.notebook.select(self.tab_planning)
        self.refresh_all()
        self.set_status("Tâche passive convertie en planning")

    # ------------------------------------------------------------------
    # Employés
    # ------------------------------------------------------------------

    def add_employee_dialog(self) -> None:
        name = self.ask_text("Ajouter employé", "Nom de l'employé :")
        if not name:
            return
        if name in self.users:
            messagebox.showwarning("Doublon", "Cet employé existe déjà.")
            return
        self.push_history()
        self.users.append(name)
        self.users = sorted(self.users, key=str.lower)
        self.user_constraints[name] = {"weekly_pattern": [1, 1, 1, 1, 1], "holidays": []}
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Employé ajouté : {name}")

    def selected_employee(self) -> Optional[str]:
        if not self.employee_tree:
            return None
        sel = self.employee_tree.selection()
        return sel[0] if sel else None

    def rename_employee_dialog(self) -> None:
        old = self.selected_employee()
        if not old:
            messagebox.showinfo("Employés", "Sélectionne un employé.")
            return
        new = self.ask_text("Renommer employé", "Nouveau nom :", old)
        if not new or new == old:
            return
        if new in self.users:
            messagebox.showwarning("Doublon", "Ce nom existe déjà.")
            return
        self.push_history()
        self.users = [new if u == old else u for u in self.users]
        self.user_constraints[new] = self.user_constraints.pop(old, {"weekly_pattern": [1, 1, 1, 1, 1], "holidays": []})
        for entry in self.calendar_data.values():
            if entry.get("user") == old:
                entry["user"] = new
        for task in self.passive_tasks:
            if task.get("user") == old:
                task["user"] = new
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Employé renommé : {old} → {new}")

    def delete_employee(self) -> None:
        user = self.selected_employee()
        if not user:
            messagebox.showinfo("Employés", "Sélectionne un employé.")
            return
        used = any(e.get("user") == user for e in self.calendar_data.values()) or any(t.get("user") == user for t in self.passive_tasks)
        msg = f"Supprimer l'employé '{user}' ?"
        if used:
            msg += "\n\nAttention : ses blocs déjà planifiés resteront visibles mais l'employé sera retiré de la liste."
        if not messagebox.askyesno("Supprimer employé", msg):
            return
        self.push_history()
        self.users = [u for u in self.users if u != user]
        self.user_constraints.pop(user, None)
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Employé supprimé : {user}")

    def edit_employee_constraints(self) -> None:
        user = self.selected_employee()
        if not user:
            messagebox.showinfo("Employés", "Sélectionne un employé.")
            return
        constraints = self.user_constraints.setdefault(user, {"weekly_pattern": [1, 1, 1, 1, 1], "holidays": []})
        top = self.make_dialog(f"Disponibilités — {user}", "560x440")
        top.columnconfigure(0, weight=1)
        pattern = list(constraints.get("weekly_pattern", [1, 1, 1, 1, 1]))[:5]
        vars_days = []

        ttk.Label(top, text="Jours travaillés habituellement", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        day_frame = ttk.Frame(top)
        day_frame.pack(fill=X, padx=12, pady=4)
        for i, day_name in enumerate(DAYS):
            var = tk.IntVar(value=int(pattern[i]))
            vars_days.append(var)
            ttk.Checkbutton(day_frame, text=day_name, variable=var).pack(side=LEFT, padx=8)

        ttk.Label(top, text="Absences spécifiques YYYY-MM-DD", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(16, 6))
        list_frame = ttk.Frame(top)
        list_frame.pack(fill=BOTH, expand=True, padx=12, pady=4)
        holiday_list = tk.Listbox(list_frame, height=8)
        holiday_list.pack(side=LEFT, fill=BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=VERTICAL, command=holiday_list.yview)
        sb.pack(side=RIGHT, fill=Y)
        holiday_list.configure(yscrollcommand=sb.set)
        for h in constraints.get("holidays", []):
            holiday_list.insert(END, h)

        add_frame = ttk.Frame(top)
        add_frame.pack(fill=X, padx=12, pady=8)
        date_var = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(add_frame, textvariable=date_var, width=14).pack(side=LEFT, padx=4)

        def add_holiday() -> None:
            value = date_var.get().strip()
            if not to_date(value):
                messagebox.showerror("Date invalide", "Format attendu : YYYY-MM-DD")
                return
            current = list(holiday_list.get(0, END))
            if value not in current:
                holiday_list.insert(END, value)

        def remove_holiday() -> None:
            sel = holiday_list.curselection()
            if sel:
                holiday_list.delete(sel[0])

        ttk.Button(add_frame, text="Ajouter absence", command=add_holiday).pack(side=LEFT, padx=4)
        ttk.Button(add_frame, text="Supprimer sélection", command=remove_holiday).pack(side=LEFT, padx=4)

        buttons = ttk.Frame(top)
        buttons.pack(fill=X, padx=12, pady=12)

        def save_constraints() -> None:
            self.push_history()
            self.user_constraints[user] = {
                "weekly_pattern": [v.get() for v in vars_days],
                "holidays": sorted(set(holiday_list.get(0, END))),
            }
            self.save_all(silent=True)
            self.refresh_all()
            self.set_status(f"Disponibilités sauvegardées : {user}")
            top.destroy()

        ttk.Button(buttons, text="Valider", command=save_constraints).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=top.destroy).pack(side=RIGHT, padx=4)

    # ------------------------------------------------------------------
    # Projets / tâches
    # ------------------------------------------------------------------

    def add_project_dialog(self) -> None:
        name = self.ask_text("Ajouter projet", "Nom du projet :")
        if not name:
            return
        if self.find_project_by_name(name):
            messagebox.showwarning("Doublon", "Ce projet existe déjà.")
            return
        color = colorchooser.askcolor(title="Couleur du projet")[1] or DEFAULT_PROJECT_COLOR
        self.push_history()
        self.projects.append({"id": uuid.uuid4().hex, "name": name, "tasks": [], "color": safe_color(color, DEFAULT_PROJECT_COLOR)})
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Projet ajouté : {name}")

    def rename_project_dialog(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("Projets", "Sélectionne un projet.")
            return
        old = project["name"]
        new = self.ask_text("Renommer projet", "Nouveau nom :", old)
        if not new or new == old:
            return
        if self.find_project_by_name(new):
            messagebox.showwarning("Doublon", "Ce projet existe déjà.")
            return
        self.push_history()
        project["name"] = new
        for entry in self.calendar_data.values():
            if entry.get("project") == old:
                entry["project"] = new
        for task in self.passive_tasks:
            if task.get("project") == old:
                task["project"] = new
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Projet renommé : {old} → {new}")

    def choose_project_color(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("Projets", "Sélectionne un projet.")
            return
        color = colorchooser.askcolor(title=f"Couleur — {project['name']}")[1]
        if not color:
            return
        self.push_history()
        project["color"] = color
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status("Couleur projet mise à jour")

    def delete_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("Projets", "Sélectionne un projet.")
            return
        name = project["name"]
        used = any(e.get("project") == name for e in self.calendar_data.values()) or any(t.get("project") == name for t in self.passive_tasks)
        msg = f"Supprimer le projet '{name}' ?"
        if used:
            msg += "\n\nLes blocs/tâches passives liés à ce projet seront aussi supprimés."
        if not messagebox.askyesno("Supprimer projet", msg):
            return
        self.push_history()
        self.projects = [p for p in self.projects if p.get("id") != project.get("id")]
        self.calendar_data = {k: v for k, v in self.calendar_data.items() if v.get("project") != name}
        self.passive_tasks = [t for t in self.passive_tasks if t.get("project") != name]
        self.selected_project_id = None
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status(f"Projet supprimé : {name}")

    def add_task_dialog(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("Projets", "Sélectionne un projet.")
            return
        self.open_task_editor(project)

    def edit_task_dialog(self) -> None:
        project = self.get_selected_project()
        task = self.get_selected_task(project) if project else None
        if not project or not task:
            messagebox.showinfo("Tâches", "Sélectionne une tâche.")
            return
        self.open_task_editor(project, task)

    def open_task_editor(self, project: Dict[str, Any], task: Optional[Dict[str, Any]] = None) -> None:
        top = self.make_dialog("Modifier tâche" if task else "Ajouter tâche", "360x220")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Nom").grid(row=0, column=0, sticky="w", padx=12, pady=10)
        name_var = tk.StringVar(value=task.get("name") if task else "")
        ttk.Entry(top, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=12, pady=10)
        ttk.Label(top, text="Durée blocs").grid(row=1, column=0, sticky="w", padx=12, pady=10)
        duration_var = tk.StringVar(value=str(task.get("duration", 1)) if task else "1")
        ttk.Spinbox(top, from_=1, to=80, textvariable=duration_var, width=8).grid(row=1, column=1, sticky="w", padx=12, pady=10)

        def save_task() -> None:
            name = name_var.get().strip()
            try:
                duration = max(1, int(duration_var.get()))
            except Exception:
                messagebox.showerror("Erreur", "Durée invalide.")
                return
            if not name:
                messagebox.showwarning("Nom manquant", "Le nom de tâche est obligatoire.")
                return
            if task is None and any(t["name"].lower() == name.lower() for t in project.get("tasks", [])):
                messagebox.showwarning("Doublon", "Cette tâche existe déjà dans le projet.")
                return
            self.push_history()
            if task:
                old_name = task["name"]
                task["name"] = name
                task["duration"] = duration
                for entry in self.calendar_data.values():
                    if entry.get("project") == project["name"] and entry.get("task") == old_name:
                        entry["task"] = name
                for passive in self.passive_tasks:
                    if passive.get("project") == project["name"] and passive.get("task") == old_name:
                        passive["task"] = name
            else:
                project.setdefault("tasks", []).append({"name": name, "duration": duration})
            project["tasks"] = sorted(project.get("tasks", []), key=lambda t: t["name"].lower())
            self.save_all(silent=True)
            self.refresh_all()
            self.set_status("Tâche sauvegardée")
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=16)
        ttk.Button(buttons, text="Valider", command=save_task).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=top.destroy).pack(side=RIGHT, padx=4)

    def delete_task(self) -> None:
        project = self.get_selected_project()
        task = self.get_selected_task(project) if project else None
        if not project or not task:
            messagebox.showinfo("Tâches", "Sélectionne une tâche.")
            return
        if not messagebox.askyesno("Supprimer tâche", f"Supprimer la tâche '{task['name']}' du projet '{project['name']}' ?"):
            return
        self.push_history()
        task_name = task["name"]
        project["tasks"] = [t for t in project.get("tasks", []) if t["name"] != task_name]
        # On ne supprime pas les blocs déjà planifiés : ils restent comme historique visuel.
        self.save_all(silent=True)
        self.refresh_all()
        self.set_status("Tâche supprimée")

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def undo(self) -> None:
        if not self.history:
            messagebox.showinfo("Annuler", "Aucune action à annuler.")
            return
        self.redo_history.append(self.snapshot())
        snap = self.history.pop()
        self.restore_snapshot(snap)
        self.set_status("Action annulée")

    def redo(self) -> None:
        if not self.redo_history:
            messagebox.showinfo("Rétablir", "Aucune action à rétablir.")
            return
        self.history.append(self.snapshot())
        snap = self.redo_history.pop()
        self.restore_snapshot(snap)
        self.set_status("Action rétablie")

    # ------------------------------------------------------------------
    # Helpers métier
    # ------------------------------------------------------------------

    def is_user_absent(self, user: str, day: date) -> bool:
        constraints = self.user_constraints.get(user)
        if not constraints:
            return False
        if day.weekday() >= 5:
            return True
        pattern = constraints.get("weekly_pattern", [1, 1, 1, 1, 1])
        try:
            if int(pattern[day.weekday()]) == 0:
                return True
        except Exception:
            pass
        return day.isoformat() in constraints.get("holidays", [])

    def default_user(self) -> str:
        filter_user = self.filter_user_var.get()
        if filter_user != "Tous" and filter_user in self.users:
            return filter_user
        return sorted(self.users, key=str.lower)[0] if self.users else ""

    def find_project_by_id(self, project_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not project_id:
            return None
        return next((p for p in self.projects if p.get("id") == project_id), None)

    def find_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return next((p for p in self.projects if p.get("name") == name), None)

    def get_selected_project(self) -> Optional[Dict[str, Any]]:
        if not self.project_tree:
            return None
        sel = self.project_tree.selection()
        if sel:
            self.selected_project_id = sel[0]
        return self.find_project_by_id(self.selected_project_id)

    def get_selected_task(self, project: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not project or not self.task_tree:
            return None
        sel = self.task_tree.selection()
        if not sel:
            return None
        values = self.task_tree.item(sel[0], "values")
        if not values:
            return None
        task_name = values[0]
        return next((t for t in project.get("tasks", []) if t.get("name") == task_name), None)

    # ------------------------------------------------------------------
    # Mini-dialogues
    # ------------------------------------------------------------------

    def make_dialog(self, title: str, geometry: str) -> tk.Toplevel:
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry(geometry)
        top.transient(self.root)
        top.grab_set()
        top.focus_force()
        return top

    def ask_text(self, title: str, label: str, initial: str = "") -> Optional[str]:
        top = self.make_dialog(title, "380x160")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text=label).grid(row=0, column=0, sticky="w", padx=12, pady=(14, 6))
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(top, textvariable=var)
        entry.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        entry.focus_set()
        result: Dict[str, Optional[str]] = {"value": None}

        def validate(*_: Any) -> None:
            value = var.get().strip()
            result["value"] = value if value else None
            top.destroy()

        def cancel() -> None:
            result["value"] = None
            top.destroy()

        buttons = ttk.Frame(top)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
        ttk.Button(buttons, text="Valider", command=validate).pack(side=LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=cancel).pack(side=RIGHT, padx=4)
        top.bind("<Return>", validate)
        top.bind("<Escape>", lambda e: cancel())
        self.root.wait_window(top)
        return result["value"]


if __name__ == "__main__":
    PlannerApp()
