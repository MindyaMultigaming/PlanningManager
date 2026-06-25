"""
Planning Manager - desktop app.

Application Tkinter sans dependance obligatoire:
- donnees locales persistantes en JSON;
- utilisateurs avec capacite par jour et jours speciaux;
- etudes/projets avec taches en creneaux de 30 minutes;
- recalcul automatique du planning sur une base de 8h30 par jour.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox
import tkinter.ttk as ttk


APP_TITLE = "Planning Manager"
APP_SIZE = "1280x820"

SLOT_MINUTES = 30
SLOTS_PER_DAY = 17
WORKDAY_START = time(8, 30)
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
STATUSES = ["a_planifier", "planifie", "en_cours", "termine"]
FREE_COLOR = "#f8fafc"
TASK_COLOR = "#dbeafe"
URGENT_COLOR = "#fde68a"
ABSENCE_COLOR = "#fecaca"
UNAVAILABLE_COLOR = "#e5e7eb"
SELECTED_COLOR = "#bbf7d0"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path(os.environ.get("PLANNING_MANAGER_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", BASE_DIR)) / "MindyaPlanningManager")


def today_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def date_to_fr(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def new_id() -> str:
    return uuid.uuid4().hex


def clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(minimum, min(maximum, number))


def slot_label(slot_index: int) -> str:
    start_dt = datetime.combine(date.today(), WORKDAY_START) + timedelta(minutes=slot_index * SLOT_MINUTES)
    end_dt = start_dt + timedelta(minutes=SLOT_MINUTES)
    return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"


def duration_label(slots: int) -> str:
    minutes = max(1, slots) * SLOT_MINUTES
    hours = minutes // 60
    rest = minutes % 60
    if hours and rest:
        return f"{hours}h{rest:02d}"
    if hours:
        return f"{hours}h"
    return f"{rest}min"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        messagebox.showerror("Lecture JSON", f"Impossible de lire {path.name}:\n{exc}")
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    tmp.replace(path)


@dataclass
class ScheduleResult:
    assignments: List[Dict[str, Any]]
    unscheduled: List[Dict[str, Any]]
    summary: Dict[str, int]


class PlannerStore:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        self.data_dir = data_dir
        self.paths = {
            "users": data_dir / "users.json",
            "projects": data_dir / "projects.json",
            "assignments": data_dir / "assignments.json",
            "blocks": data_dir / "blocks.json",
            "settings": data_dir / "settings.json",
        }
        self.backup_dir = data_dir / "backups"
        self.users: List[Dict[str, Any]] = []
        self.projects: List[Dict[str, Any]] = []
        self.assignments: List[Dict[str, Any]] = []
        self.blocks: List[Dict[str, Any]] = []
        self.settings: Dict[str, Any] = {}

    def load(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_old_files()
        self.users = read_json(self.paths["users"], [])
        self.projects = read_json(self.paths["projects"], [])
        self.assignments = read_json(self.paths["assignments"], [])
        self.blocks = read_json(self.paths["blocks"], [])
        self.settings = read_json(self.paths["settings"], {})
        self.normalize()
        self.save()

    def _migrate_old_files(self) -> None:
        legacy = {
            "users": BASE_DIR / "users.json",
            "projects": BASE_DIR / "projects.json",
            "assignments": BASE_DIR / "assignments.json",
            "blocks": BASE_DIR / "blocks.json",
            "settings": BASE_DIR / "settings.json",
        }
        for key, source in legacy.items():
            target = self.paths[key]
            if source.exists() and not target.exists():
                shutil.copy2(source, target)

    def normalize(self) -> None:
        if not isinstance(self.settings, dict):
            self.settings = {}
        self.settings.setdefault("planning_start", today_monday().isoformat())
        self.settings.setdefault("horizon_weeks", 8)
        self.settings["horizon_weeks"] = clamp_int(self.settings.get("horizon_weeks"), 1, 52, 8)

        clean_users: List[Dict[str, Any]] = []
        seen_user_names = set()
        for raw in self.users if isinstance(self.users, list) else []:
            if isinstance(raw, str):
                raw = {"name": raw}
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            lower = name.lower()
            if lower in seen_user_names:
                continue
            seen_user_names.add(lower)
            user_id = str(raw.get("id") or new_id())
            weekly = raw.get("weekly_capacity", [SLOTS_PER_DAY] * 5)
            if not isinstance(weekly, list):
                weekly = [SLOTS_PER_DAY] * 5
            weekly = (weekly + [SLOTS_PER_DAY] * 5)[:5]
            special_days = raw.get("special_days", {})
            if isinstance(special_days, list):
                special_days = {str(day): 0 for day in special_days}
            if not isinstance(special_days, dict):
                special_days = {}
            clean_special = {
                str(day): clamp_int(value, 0, SLOTS_PER_DAY, 0)
                for day, value in special_days.items()
                if parse_date(str(day))
            }
            clean_users.append(
                {
                    "id": user_id,
                    "name": name,
                    "weekly_capacity": [clamp_int(x, 0, SLOTS_PER_DAY, SLOTS_PER_DAY) for x in weekly],
                    "special_days": dict(sorted(clean_special.items())),
                    "note": str(raw.get("note", "")),
                }
            )
        self.users = sorted(clean_users, key=lambda item: item["name"].lower())

        clean_projects: List[Dict[str, Any]] = []
        seen_project_names = set()
        valid_user_ids = {user["id"] for user in self.users}
        for raw in self.projects if isinstance(self.projects, list) else []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            if not name:
                continue
            lower = name.lower()
            if lower in seen_project_names:
                name = f"{name} ({len(seen_project_names) + 1})"
            seen_project_names.add(name.lower())
            project_id = str(raw.get("id") or new_id())
            tasks = []
            for task in raw.get("tasks", []) if isinstance(raw.get("tasks", []), list) else []:
                if not isinstance(task, dict):
                    continue
                task_name = str(task.get("name", "")).strip()
                if not task_name:
                    continue
                assignee_id = str(task.get("assignee_id", "")).strip()
                if assignee_id not in valid_user_ids:
                    assignee_id = ""
                status = str(task.get("status", "a_planifier"))
                if status not in STATUSES:
                    status = "a_planifier"
                tasks.append(
                    {
                        "id": str(task.get("id") or new_id()),
                        "name": task_name,
                        "duration_slots": clamp_int(task.get("duration_slots", task.get("duration", 1)), 1, 500, 1),
                        "priority": clamp_int(task.get("priority", 2), 0, 5, 2),
                        "assignee_id": assignee_id,
                        "status": status,
                        "manual_start": self._normalize_manual_start(task.get("manual_start"), assignee_id),
                        "note": str(task.get("note", "")),
                    }
                )
            clean_projects.append(
                {
                    "id": project_id,
                    "name": name,
                    "color": str(raw.get("color", "#dbeafe")),
                    "tasks": sorted(tasks, key=lambda item: (-item["priority"], item["name"].lower())),
                }
            )
        self.projects = sorted(clean_projects, key=lambda item: item["name"].lower())

        if not isinstance(self.assignments, list):
            self.assignments = []

        clean_blocks: List[Dict[str, Any]] = []
        valid_user_ids = {user["id"] for user in self.users}
        for raw in self.blocks if isinstance(self.blocks, list) else []:
            if not isinstance(raw, dict):
                continue
            user_id = str(raw.get("user_id", "")).strip()
            day = parse_date(str(raw.get("date", "")))
            if user_id not in valid_user_ids or not day:
                continue
            start_slot = clamp_int(raw.get("slot_index", 0), 0, SLOTS_PER_DAY - 1, 0)
            duration = clamp_int(raw.get("duration_slots", 1), 1, SLOTS_PER_DAY - start_slot, 1)
            clean_blocks.append(
                {
                    "id": str(raw.get("id") or new_id()),
                    "user_id": user_id,
                    "date": day.isoformat(),
                    "slot_index": start_slot,
                    "duration_slots": duration,
                    "kind": str(raw.get("kind", "absence")),
                    "note": str(raw.get("note", "")),
                }
            )
        self.blocks = sorted(clean_blocks, key=lambda row: (row["date"], row["user_id"], row["slot_index"]))

    @staticmethod
    def _normalize_manual_start(raw: Any, fallback_user_id: str = "") -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        day = parse_date(str(raw.get("date", "")))
        if not day:
            return {}
        return {
            "date": day.isoformat(),
            "slot_index": clamp_int(raw.get("slot_index", 0), 0, SLOTS_PER_DAY - 1, 0),
            "user_id": str(raw.get("user_id") or fallback_user_id or ""),
        }

    def save(self) -> None:
        write_json(self.paths["users"], self.users)
        write_json(self.paths["projects"], self.projects)
        write_json(self.paths["assignments"], self.assignments)
        write_json(self.paths["blocks"], self.blocks)
        write_json(self.paths["settings"], self.settings)

    def backup(self) -> Path:
        self.save()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.backup_dir / stamp
        target.mkdir(parents=True, exist_ok=True)
        for path in self.paths.values():
            if path.exists():
                shutil.copy2(path, target / path.name)
        return target

    def user_name(self, user_id: str) -> str:
        user = self.find_user(user_id)
        return user["name"] if user else ""

    def find_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return next((user for user in self.users if user.get("id") == user_id), None)

    def find_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return next((project for project in self.projects if project.get("id") == project_id), None)

    def find_task(self, project_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        project = self.find_project(project_id)
        if not project:
            return None
        return next((task for task in project.get("tasks", []) if task.get("id") == task_id), None)

    def capacity_for(self, user: Dict[str, Any], day: date) -> int:
        if day.weekday() >= 5:
            return 0
        day_key = day.isoformat()
        special_days = user.get("special_days", {})
        if day_key in special_days:
            return clamp_int(special_days[day_key], 0, SLOTS_PER_DAY, 0)
        weekly = user.get("weekly_capacity", [SLOTS_PER_DAY] * 5)
        return clamp_int(weekly[day.weekday()], 0, SLOTS_PER_DAY, SLOTS_PER_DAY)

    def block_at(self, user_id: str, day: date, slot_index: int) -> Optional[Dict[str, Any]]:
        day_key = day.isoformat()
        for block in self.blocks:
            if block.get("user_id") != user_id or block.get("date") != day_key:
                continue
            start_slot = int(block.get("slot_index", 0))
            end_slot = start_slot + int(block.get("duration_slots", 1))
            if start_slot <= slot_index < end_slot:
                return block
        return None

    def is_work_slot(self, user: Dict[str, Any], day: date, slot_index: int) -> bool:
        if slot_index < 0 or slot_index >= SLOTS_PER_DAY:
            return False
        if slot_index >= self.capacity_for(user, day):
            return False
        return self.block_at(user["id"], day, slot_index) is None

    def add_block(self, user_id: str, day: date, slot_index: int, duration_slots: int, note: str = "") -> None:
        duration = clamp_int(duration_slots, 1, SLOTS_PER_DAY - slot_index, 1)
        self.blocks.append(
            {
                "id": new_id(),
                "user_id": user_id,
                "date": day.isoformat(),
                "slot_index": clamp_int(slot_index, 0, SLOTS_PER_DAY - 1, 0),
                "duration_slots": duration,
                "kind": "absence",
                "note": note,
            }
        )
        self.normalize()

    def remove_block_at(self, user_id: str, day: date, slot_index: int) -> bool:
        block = self.block_at(user_id, day, slot_index)
        if not block:
            return False
        self.blocks = [item for item in self.blocks if item.get("id") != block.get("id")]
        self.normalize()
        return True

    def schedule(self) -> ScheduleResult:
        start = parse_date(str(self.settings.get("planning_start", ""))) or today_monday()
        start = start - timedelta(days=start.weekday())
        weeks = clamp_int(self.settings.get("horizon_weeks"), 1, 52, 8)
        horizon_days = weeks * 7
        valid_users = [
            user
            for user in self.users
            if any(self.is_work_slot(user, start + timedelta(days=i), slot) for i in range(horizon_days) for slot in range(SLOTS_PER_DAY))
        ]

        occupied: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        assignments: List[Dict[str, Any]] = []
        unscheduled: List[Dict[str, Any]] = []
        summary: Dict[str, int] = {user["id"]: 0 for user in self.users}
        for row in self.assignments if isinstance(self.assignments, list) else []:
            project_id = str(row.get("project_id", ""))
            task_id = str(row.get("task_id", ""))
            task = self.find_task(project_id, task_id)
            user = self.find_user(str(row.get("user_id", "")))
            if not task or not user or task.get("status") in ("a_planifier", "termine"):
                continue
            if not self.assignment_is_still_available(row, user, occupied):
                task["status"] = "a_planifier"
                task["manual_start"] = {}
                continue
            assignments.append(row)
            for slot in range(int(row.get("slot_index", 0)), min(SLOTS_PER_DAY, int(row.get("slot_index", 0)) + int(row.get("duration_slots", 1)))):
                occupied[(user["id"], row["date"], slot)] = {"project_id": project_id, "task_id": task_id}
            summary[user["id"]] = summary.get(user["id"], 0) + int(row.get("duration_slots", 1))

        tasks = []
        for project in self.projects:
            for task in project.get("tasks", []):
                if task.get("status") != "a_planifier":
                    continue
                tasks.append({"project": project, "task": task})
        tasks.sort(key=self._schedule_sort_key)

        for item in tasks:
            project = item["project"]
            task = item["task"]
            duration_slots = clamp_int(task.get("duration_slots"), 1, 500, 1)
            manual_start = task.get("manual_start") if isinstance(task.get("manual_start"), dict) else {}
            fixed_user_id = str(manual_start.get("user_id") or task.get("assignee_id", ""))
            preferred_day = parse_date(str(manual_start.get("date", ""))) if manual_start else None
            preferred_slot = clamp_int(manual_start.get("slot_index", 0), 0, SLOTS_PER_DAY - 1, 0) if manual_start else 0
            candidates = [user for user in valid_users if not fixed_user_id or user["id"] == fixed_user_id]
            if not candidates:
                unscheduled.append(self._unscheduled_row(project, task, "Aucun utilisateur disponible"))
                continue

            best_user: Optional[Dict[str, Any]] = None
            best_slots: Optional[List[Tuple[date, int]]] = None
            for user in candidates:
                slots = self._find_slots_for_user(
                    user,
                    duration_slots,
                    start,
                    horizon_days,
                    occupied,
                    preferred_start=(preferred_day, preferred_slot) if preferred_day else None,
                )
                if not slots:
                    continue
                if best_slots is None or slots[-1] < best_slots[-1] or (slots[-1] == best_slots[-1] and summary[user["id"]] < summary.get(best_user["id"], 0)):  # type: ignore[index]
                    best_user = user
                    best_slots = slots

            if not best_user or not best_slots:
                unscheduled.append(self._unscheduled_row(project, task, "Pas assez de place dans l'horizon"))
                continue

            for day, slot in best_slots:
                occupied[(best_user["id"], day.isoformat(), slot)] = {"project_id": project["id"], "task_id": task["id"]}
            summary[best_user["id"]] = summary.get(best_user["id"], 0) + len(best_slots)
            assignments.extend(self._group_slots(project, task, best_user, best_slots))
            task["status"] = "planifie"

        assignments.sort(key=lambda row: (row["date"], row["slot_index"], row["user_name"], row["project_name"], row["task_name"]))
        self.assignments = assignments
        self.save()
        return ScheduleResult(assignments=assignments, unscheduled=unscheduled, summary=summary)

    def assignment_is_still_available(
        self,
        row: Dict[str, Any],
        user: Dict[str, Any],
        occupied: Dict[Tuple[str, str, int], Dict[str, Any]],
    ) -> bool:
        day = parse_date(str(row.get("date", "")))
        if not day:
            return False
        start_slot = int(row.get("slot_index", 0))
        duration = int(row.get("duration_slots", 1))
        for slot in range(start_slot, min(SLOTS_PER_DAY, start_slot + duration)):
            key = (user["id"], row["date"], slot)
            if key in occupied or not self.is_work_slot(user, day, slot):
                return False
        return True

    def reopen_user_assignments_from(self, user_id: str, day_key: str, slot_index: int, exclude: Optional[Tuple[str, str]] = None) -> int:
        reopened = 0
        seen: set[Tuple[str, str]] = set()
        for row in self.assignments if isinstance(self.assignments, list) else []:
            if row.get("user_id") != user_id:
                continue
            row_day = str(row.get("date", ""))
            row_slot = int(row.get("slot_index", 0))
            if row_day < day_key or (row_day == day_key and row_slot < slot_index):
                continue
            task_ref = (str(row.get("project_id", "")), str(row.get("task_id", "")))
            if exclude and task_ref == exclude:
                continue
            if task_ref in seen:
                continue
            task = self.find_task(task_ref[0], task_ref[1])
            if task and task.get("status") != "termine":
                task["status"] = "a_planifier"
                task["manual_start"] = {"date": row_day, "slot_index": row_slot, "user_id": user_id}
                seen.add(task_ref)
                reopened += 1
        return reopened

    @staticmethod
    def _schedule_sort_key(item: Dict[str, Any]) -> Tuple[Any, ...]:
        project = item["project"]
        task = item["task"]
        manual_start = task.get("manual_start") if isinstance(task.get("manual_start"), dict) else {}
        if manual_start:
            return (
                0,
                str(manual_start.get("date", "")),
                int(manual_start.get("slot_index", 0)),
                project["name"].lower(),
                task["name"].lower(),
            )
        return (1, -int(task.get("priority", 0)), project["name"].lower(), task["name"].lower())

    def _find_slots_for_user(
        self,
        user: Dict[str, Any],
        duration_slots: int,
        start: date,
        horizon_days: int,
        occupied: Dict[Tuple[str, str, int], Dict[str, Any]],
        preferred_start: Optional[Tuple[date, int]] = None,
    ) -> Optional[List[Tuple[date, int]]]:
        found: List[Tuple[date, int]] = []
        preferred_day, preferred_slot = preferred_start if preferred_start else (None, 0)
        end_offset = horizon_days
        if preferred_day:
            end_offset = max(end_offset, (preferred_day - start).days + horizon_days)
        for offset in range(max(0, end_offset)):
            day = start + timedelta(days=offset)
            if preferred_day and day < preferred_day:
                continue
            first_slot = preferred_slot if preferred_day and day == preferred_day else 0
            for slot in range(first_slot, SLOTS_PER_DAY):
                if not self.is_work_slot(user, day, slot):
                    continue
                key = (user["id"], day.isoformat(), slot)
                if key in occupied:
                    continue
                found.append((day, slot))
                if len(found) == duration_slots:
                    return found
        return None

    def _group_slots(
        self,
        project: Dict[str, Any],
        task: Dict[str, Any],
        user: Dict[str, Any],
        slots: List[Tuple[date, int]],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        current_day: Optional[date] = None
        current_start: Optional[int] = None
        current_count = 0
        previous_slot: Optional[int] = None

        def flush() -> None:
            nonlocal current_day, current_start, current_count
            if current_day is None or current_start is None or current_count <= 0:
                return
            rows.append(
                {
                    "id": new_id(),
                    "date": current_day.isoformat(),
                    "slot_index": current_start,
                    "duration_slots": current_count,
                    "user_id": user["id"],
                    "user_name": user["name"],
                    "project_id": project["id"],
                    "project_name": project["name"],
                    "task_id": task["id"],
                    "task_name": task["name"],
                    "priority": task.get("priority", 0),
                    "status": task.get("status", "a_planifier"),
                }
            )

        for day, slot in slots:
            if current_day == day and previous_slot is not None and slot == previous_slot + 1:
                current_count += 1
            else:
                flush()
                current_day = day
                current_start = slot
                current_count = 1
            previous_slot = slot
        flush()
        return rows

    @staticmethod
    def _unscheduled_row(project: Dict[str, Any], task: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {
            "project_name": project.get("name", ""),
            "task_name": task.get("name", ""),
            "duration_slots": task.get("duration_slots", 1),
            "priority": task.get("priority", 0),
            "reason": reason,
        }


class PlannerApp:
    def __init__(self) -> None:
        self.store = PlannerStore()
        self.store.load()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(APP_SIZE)
        self.root.minsize(1100, 700)

        self.status_var = tk.StringVar(value="Pret")
        self.filter_user_var = tk.StringVar(value="Tous")
        self.filter_project_var = tk.StringVar(value="Tous")
        self.start_var = tk.StringVar(value=str(self.store.settings.get("planning_start", today_monday().isoformat())))
        self.weeks_var = tk.StringVar(value=str(self.store.settings.get("horizon_weeks", 8)))
        self.dashboard_date_var = tk.StringVar(value=date.today().isoformat())
        self.dashboard_mode_var = tk.StringVar(value="Jour")
        self.selected_project_id: Optional[str] = None
        self.selected_slot: Optional[Tuple[str, str, int]] = None
        self.selected_task_ref: Optional[Tuple[str, str]] = None
        self.cut_task_ref: Optional[Dict[str, str]] = None
        self.dashboard_frame: Optional[ttk.Frame] = None
        self.dashboard_canvas: Optional[tk.Canvas] = None
        self.dashboard_buttons: Dict[Tuple[str, str, int], tk.Button] = {}

        self._build_ui()
        self.recalculate_schedule(silent=True)
        self.refresh_all()
        self.root.mainloop()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        top.columnconfigure(14, weight=1)

        ttk.Label(top, text="Debut").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(top, textvariable=self.start_var, width=12).grid(row=0, column=1, padx=3)
        ttk.Label(top, text="Semaines").grid(row=0, column=2, padx=(10, 4))
        ttk.Spinbox(top, from_=1, to=52, textvariable=self.weeks_var, width=5).grid(row=0, column=3, padx=3)
        ttk.Button(top, text="Planifier les taches a_planifier", command=self.recalculate_schedule).grid(row=0, column=4, padx=8)
        ttk.Button(top, text="Sauver", command=self.save_all).grid(row=0, column=5, padx=3)
        ttk.Button(top, text="Backup", command=self.backup).grid(row=0, column=6, padx=3)

        ttk.Label(top, text="Utilisateur").grid(row=0, column=8, padx=(18, 4))
        self.user_filter = ttk.Combobox(top, textvariable=self.filter_user_var, state="readonly", width=18)
        self.user_filter.grid(row=0, column=9, padx=3)
        self.user_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh_planning_views())
        ttk.Label(top, text="Etude").grid(row=0, column=10, padx=(10, 4))
        self.project_filter = ttk.Combobox(top, textvariable=self.filter_project_var, state="readonly", width=22)
        self.project_filter.grid(row=0, column=11, padx=3)
        self.project_filter.bind("<<ComboboxSelected>>", lambda _event: self.refresh_planning_views())

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        self.tab_planning = ttk.Frame(self.notebook)
        self.tab_users = ttk.Frame(self.notebook)
        self.tab_projects = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_planning, text="Planning")
        self.notebook.add(self.tab_users, text="Utilisateurs")
        self.notebook.add(self.tab_projects, text="Etudes et taches")
        self.notebook.add(self.tab_settings, text="Donnees")

        self._build_planning_tab()
        self._build_users_tab()
        self._build_projects_tab()
        self._build_settings_tab()
        self.root.bind("<Control-x>", lambda _event: self.cut_selected_slot())
        self.root.bind("<Control-v>", lambda _event: self.paste_to_selected_slot())

        ttk.Label(self.root, textvariable=self.status_var, anchor="w").grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))

    def _build_planning_tab(self) -> None:
        self.tab_planning.columnconfigure(0, weight=1)
        self.tab_planning.rowconfigure(1, weight=3)
        self.tab_planning.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(self.tab_planning)
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="<", width=3, command=lambda: self.shift_dashboard_date(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Entry(toolbar, textvariable=self.dashboard_date_var, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text=">", width=3, command=lambda: self.shift_dashboard_date(1)).pack(side=tk.LEFT, padx=2)
        ttk.Combobox(toolbar, textvariable=self.dashboard_mode_var, values=["Jour", "Semaine"], state="readonly", width=9).pack(side=tk.LEFT, padx=8)
        ttk.Button(toolbar, text="Afficher", command=self.refresh_dashboard).pack(side=tk.LEFT, padx=3)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="Couper case", command=self.cut_selected_slot).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Coller ici", command=self.paste_to_selected_slot).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="+ Absence", command=self.add_absence_on_selected_slot).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Retirer absence", command=self.remove_absence_on_selected_slot).pack(side=tk.LEFT, padx=3)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="Marquer tache terminee", command=self.mark_selected_task_done).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Mettre en urgent", command=self.mark_selected_task_urgent).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Aller a la tache", command=self.focus_selected_task).pack(side=tk.LEFT, padx=3)
        ttk.Label(toolbar, text="Selection case -> Ctrl+X / Ctrl+V, rouge = absence").pack(side=tk.LEFT, padx=12)

        dashboard_outer = ttk.Frame(self.tab_planning)
        dashboard_outer.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        dashboard_outer.columnconfigure(0, weight=1)
        dashboard_outer.rowconfigure(0, weight=1)
        self.dashboard_canvas = tk.Canvas(dashboard_outer, background="#ffffff", highlightthickness=0)
        self.dashboard_canvas.grid(row=0, column=0, sticky="nsew")
        dash_y = ttk.Scrollbar(dashboard_outer, orient=tk.VERTICAL, command=self.dashboard_canvas.yview)
        dash_y.grid(row=0, column=1, sticky="ns")
        dash_x = ttk.Scrollbar(dashboard_outer, orient=tk.HORIZONTAL, command=self.dashboard_canvas.xview)
        dash_x.grid(row=1, column=0, sticky="ew")
        self.dashboard_canvas.configure(yscrollcommand=dash_y.set, xscrollcommand=dash_x.set)
        self.dashboard_frame = ttk.Frame(self.dashboard_canvas)
        self.dashboard_canvas.create_window((0, 0), window=self.dashboard_frame, anchor="nw")
        self.dashboard_frame.bind("<Configure>", lambda _event: self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all")))

        ttk.Label(self.tab_planning, text="Liste detaillee").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 4))
        columns = ("date", "time", "user", "project", "task", "duration", "priority", "status")
        self.schedule_tree = ttk.Treeview(self.tab_planning, columns=columns, show="headings")
        headers = {
            "date": "Date",
            "time": "Heure",
            "user": "Utilisateur",
            "project": "Etude",
            "task": "Tache",
            "duration": "Duree",
            "priority": "Priorite",
            "status": "Statut",
        }
        widths = {"date": 95, "time": 95, "user": 150, "project": 210, "task": 360, "duration": 70, "priority": 70, "status": 100}
        for col in columns:
            self.schedule_tree.heading(col, text=headers[col])
            self.schedule_tree.column(col, width=widths[col], anchor="w")
        self.schedule_tree.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        sb = ttk.Scrollbar(self.tab_planning, orient=tk.VERTICAL, command=self.schedule_tree.yview)
        sb.grid(row=3, column=1, sticky="ns", pady=(0, 8))
        self.schedule_tree.configure(yscrollcommand=sb.set)
        self.schedule_tree.bind("<<TreeviewSelect>>", lambda _event: self.select_assignment_from_tree())

        self.summary_var = tk.StringVar()
        ttk.Label(self.tab_planning, textvariable=self.summary_var, anchor="w").grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))

    def _build_users_tab(self) -> None:
        self.tab_users.columnconfigure(0, weight=1)
        self.tab_users.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.tab_users)
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="+ Utilisateur", command=self.add_user).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Modifier", command=self.edit_user).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer", command=self.delete_user).pack(side=tk.LEFT, padx=3)

        columns = ("name", "weekly", "special", "note")
        self.user_tree = ttk.Treeview(self.tab_users, columns=columns, show="headings")
        headers = {"name": "Nom", "weekly": "Capacite hebdo", "special": "Jours speciaux", "note": "Note"}
        widths = {"name": 180, "weekly": 400, "special": 260, "note": 300}
        for col in columns:
            self.user_tree.heading(col, text=headers[col])
            self.user_tree.column(col, width=widths[col], anchor="w")
        self.user_tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.user_tree.bind("<Double-1>", lambda _event: self.edit_user())

    def _build_projects_tab(self) -> None:
        self.tab_projects.columnconfigure(0, weight=1)
        self.tab_projects.columnconfigure(1, weight=2)
        self.tab_projects.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.tab_projects)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Button(toolbar, text="+ Etude", command=self.add_project).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Modifier etude", command=self.edit_project).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer etude", command=self.delete_project).pack(side=tk.LEFT, padx=3)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(toolbar, text="+ Tache", command=self.add_task).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Modifier tache", command=self.edit_task).pack(side=tk.LEFT, padx=3)
        ttk.Button(toolbar, text="Supprimer tache", command=self.delete_task).pack(side=tk.LEFT, padx=3)

        self.project_tree = ttk.Treeview(self.tab_projects, columns=("name", "tasks"), show="headings")
        self.project_tree.heading("name", text="Etude")
        self.project_tree.heading("tasks", text="Taches")
        self.project_tree.column("name", width=260, anchor="w")
        self.project_tree.column("tasks", width=70, anchor="center")
        self.project_tree.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        self.project_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_project_selected())
        self.project_tree.bind("<Double-1>", lambda _event: self.edit_project())

        columns = ("name", "duration", "priority", "assignee", "status", "note")
        self.task_tree = ttk.Treeview(self.tab_projects, columns=columns, show="headings")
        headers = {"name": "Tache", "duration": "Duree", "priority": "Priorite", "assignee": "Utilisateur", "status": "Statut", "note": "Note"}
        widths = {"name": 280, "duration": 80, "priority": 70, "assignee": 140, "status": 100, "note": 220}
        for col in columns:
            self.task_tree.heading(col, text=headers[col])
            self.task_tree.column(col, width=widths[col], anchor="w")
        self.task_tree.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))
        self.task_tree.bind("<Double-1>", lambda _event: self.edit_task())

    def _build_settings_tab(self) -> None:
        self.tab_settings.columnconfigure(1, weight=1)
        ttk.Label(self.tab_settings, text="Dossier de donnees").grid(row=0, column=0, sticky="w", padx=12, pady=(16, 6))
        ttk.Label(self.tab_settings, text=str(self.store.data_dir)).grid(row=0, column=1, sticky="w", padx=12, pady=(16, 6))
        ttk.Label(self.tab_settings, text="Fichiers").grid(row=1, column=0, sticky="nw", padx=12, pady=6)
        files = "\n".join(path.name for path in self.store.paths.values())
        ttk.Label(self.tab_settings, text=files).grid(row=1, column=1, sticky="w", padx=12, pady=6)
        ttk.Label(
            self.tab_settings,
            text="Les donnees sont rechargees au demarrage et sauvegardees apres chaque action.",
            wraplength=760,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=12)

    def refresh_all(self) -> None:
        self.store.normalize()
        self.refresh_filters()
        self.refresh_dashboard()
        self.refresh_schedule_tree()
        self.refresh_user_tree()
        self.refresh_project_tree()

    def refresh_filters(self) -> None:
        users = ["Tous"] + [user["name"] for user in self.store.users]
        projects = ["Tous"] + [project["name"] for project in self.store.projects]
        self.user_filter["values"] = users
        self.project_filter["values"] = projects
        if self.filter_user_var.get() not in users:
            self.filter_user_var.set("Tous")
        if self.filter_project_var.get() not in projects:
            self.filter_project_var.set("Tous")

    def refresh_planning_views(self) -> None:
        self.refresh_dashboard()
        self.refresh_schedule_tree()

    def refresh_schedule_tree(self) -> None:
        self.schedule_tree.delete(*self.schedule_tree.get_children())
        user_filter = self.filter_user_var.get()
        project_filter = self.filter_project_var.get()
        total_slots = 0
        for row in self.store.assignments:
            if user_filter != "Tous" and row.get("user_name") != user_filter:
                continue
            if project_filter != "Tous" and row.get("project_name") != project_filter:
                continue
            day = parse_date(row.get("date", ""))
            date_text = date_to_fr(day) if day else row.get("date", "")
            total_slots += int(row.get("duration_slots", 0))
            self.schedule_tree.insert(
                "",
                tk.END,
                iid=row["id"],
                values=(
                    date_text,
                    slot_label(int(row.get("slot_index", 0))),
                    row.get("user_name", ""),
                    row.get("project_name", ""),
                    row.get("task_name", ""),
                    duration_label(int(row.get("duration_slots", 1))),
                    row.get("priority", 0),
                    row.get("status", ""),
                ),
            )
        self.summary_var.set(f"Charge affichee: {duration_label(total_slots)} sur {len(self.store.assignments)} segment(s) planifie(s)")

    def refresh_dashboard(self) -> None:
        if self.dashboard_frame is None:
            return
        for child in self.dashboard_frame.winfo_children():
            child.destroy()
        self.dashboard_buttons.clear()

        selected_date = parse_date(self.dashboard_date_var.get()) or date.today()
        if self.dashboard_mode_var.get() == "Semaine":
            days = [selected_date - timedelta(days=selected_date.weekday()) + timedelta(days=i) for i in range(5)]
        else:
            days = [selected_date]
        self.dashboard_date_var.set(selected_date.isoformat())

        assignment_index = self.assignment_slot_index()
        user_filter = self.filter_user_var.get()
        visible_users = [user for user in self.store.users if user_filter == "Tous" or user["name"] == user_filter]
        row = 0

        for day in days:
            title = f"{DAYS[day.weekday()] if day.weekday() < 5 else day.strftime('%A')} {date_to_fr(day)}"
            title_label = ttk.Label(self.dashboard_frame, text=title, font=("Segoe UI", 10, "bold"))
            title_label.grid(row=row, column=0, sticky="w", padx=4, pady=(8, 3))
            for slot in range(SLOTS_PER_DAY):
                ttk.Label(self.dashboard_frame, text=slot_label(slot).split("-", 1)[0], anchor="center").grid(
                    row=row, column=slot + 1, sticky="ew", padx=1, pady=(8, 3)
                )
            row += 1

            if not visible_users:
                ttk.Label(self.dashboard_frame, text="Aucun utilisateur").grid(row=row, column=0, sticky="w", padx=4, pady=4)
                row += 1
                continue

            for user in visible_users:
                ttk.Label(self.dashboard_frame, text=user["name"], anchor="w", width=18).grid(row=row, column=0, sticky="nsew", padx=2, pady=1)
                for slot in range(SLOTS_PER_DAY):
                    key = (day.isoformat(), user["id"], slot)
                    row_data = assignment_index.get(key)
                    text, bg, fg = self.dashboard_cell_style(user, day, slot, row_data)
                    if row_data and self.selected_task_ref == (row_data.get("project_id"), row_data.get("task_id")):
                        bg = SELECTED_COLOR
                    if self.selected_slot == (user["id"], day.isoformat(), slot):
                        bg = SELECTED_COLOR
                    button = tk.Button(
                        self.dashboard_frame,
                        text=text,
                        width=13,
                        height=3,
                        wraplength=92,
                        justify="center",
                        relief="solid" if self.selected_slot == (user["id"], day.isoformat(), slot) else "groove",
                        borderwidth=2 if self.selected_slot == (user["id"], day.isoformat(), slot) else 1,
                        bg=bg,
                        fg=fg,
                        activebackground=SELECTED_COLOR,
                        command=lambda u=user["id"], d=day.isoformat(), s=slot: self.select_dashboard_slot(u, d, s),
                    )
                    button.grid(row=row, column=slot + 1, sticky="nsew", padx=1, pady=1)
                    self.dashboard_buttons[(user["id"], day.isoformat(), slot)] = button
                row += 1

    def assignment_slot_index(self) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
        index: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        for row in self.store.assignments:
            day_key = row.get("date", "")
            user_id = row.get("user_id", "")
            start_slot = int(row.get("slot_index", 0))
            duration = int(row.get("duration_slots", 1))
            for slot in range(start_slot, min(SLOTS_PER_DAY, start_slot + duration)):
                index[(day_key, user_id, slot)] = row
        return index

    def dashboard_cell_style(self, user: Dict[str, Any], day: date, slot: int, row_data: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
        project_filter = self.filter_project_var.get()
        block = self.store.block_at(user["id"], day, slot)
        if block:
            note = block.get("note", "")
            return (f"ABSENT\n{note}" if note else "ABSENT", ABSENCE_COLOR, "#7f1d1d")
        if self.store.capacity_for(user, day) == 0:
            return "ABSENT", ABSENCE_COLOR, "#7f1d1d"
        if not self.store.is_work_slot(user, day, slot):
            return "--", UNAVAILABLE_COLOR, "#6b7280"
        if not row_data:
            return "", FREE_COLOR, "#111827"
        if project_filter != "Tous" and row_data.get("project_name") != project_filter:
            return "...", UNAVAILABLE_COLOR, "#6b7280"
        text = f"{row_data.get('project_name', '')}\n{row_data.get('task_name', '')}"
        color = URGENT_COLOR if int(row_data.get("priority", 0)) >= 5 else TASK_COLOR
        return text, color, "#111827"

    def shift_dashboard_date(self, days: int) -> None:
        current = parse_date(self.dashboard_date_var.get()) or date.today()
        delta = 7 if self.dashboard_mode_var.get() == "Semaine" else days
        if days < 0:
            delta = -abs(delta)
        elif days > 0:
            delta = abs(delta)
        else:
            delta = 0
        self.dashboard_date_var.set((current + timedelta(days=delta)).isoformat())
        self.refresh_dashboard()

    def select_dashboard_slot(self, user_id: str, day_key: str, slot_index: int) -> None:
        self.selected_slot = (user_id, day_key, slot_index)
        user_name = self.store.user_name(user_id) or user_id
        assignment = self.assignment_at_slot(user_id, day_key, slot_index)
        if assignment:
            self.selected_task_ref = (assignment["project_id"], assignment["task_id"])
            self.set_status(f"Selection: {user_name} {day_key} {slot_label(slot_index)} - {assignment['project_name']} / {assignment['task_name']}")
            if assignment["id"] in self.schedule_tree.get_children(""):
                self.schedule_tree.selection_set(assignment["id"])
                self.schedule_tree.focus(assignment["id"])
        else:
            self.selected_task_ref = None
            self.set_status(f"Selection: {user_name} {day_key} {slot_label(slot_index)}")
            self.schedule_tree.selection_remove(self.schedule_tree.selection())
        self.refresh_dashboard()

    def select_assignment_from_tree(self) -> None:
        selection = self.schedule_tree.selection()
        if not selection:
            return
        assignment = next((row for row in self.store.assignments if row.get("id") == selection[0]), None)
        if not assignment:
            return
        self.selected_task_ref = (assignment["project_id"], assignment["task_id"])
        self.selected_slot = (assignment["user_id"], assignment["date"], int(assignment.get("slot_index", 0)))
        self.refresh_dashboard()

    def assignment_at_slot(self, user_id: str, day_key: str, slot_index: int) -> Optional[Dict[str, Any]]:
        return self.assignment_slot_index().get((day_key, user_id, slot_index))

    def cut_selected_slot(self) -> None:
        if not self.selected_slot:
            messagebox.showinfo("Couper", "Selectionne d'abord une case du dashboard.")
            return
        user_id, day_key, slot_index = self.selected_slot
        assignment = self.assignment_at_slot(user_id, day_key, slot_index)
        if not assignment:
            messagebox.showinfo("Couper", "Cette case ne contient pas de tache.")
            return
        self.cut_task_ref = {"project_id": assignment["project_id"], "task_id": assignment["task_id"]}
        self.set_status(f"Tache coupee: {assignment['project_name']} / {assignment['task_name']}. Selectionne une case cible puis Coller ici.")

    def paste_to_selected_slot(self) -> None:
        if not self.cut_task_ref:
            messagebox.showinfo("Coller", "Aucune tache coupee.")
            return
        if not self.selected_slot:
            messagebox.showinfo("Coller", "Selectionne une case cible.")
            return
        user_id, day_key, slot_index = self.selected_slot
        day = parse_date(day_key)
        user = self.store.find_user(user_id)
        if not day or not user:
            messagebox.showerror("Coller", "Case cible invalide.")
            return
        if not self.store.is_work_slot(user, day, slot_index):
            if not messagebox.askyesno("Coller", "Cette case est marquee indisponible. Coller quand meme cherchera le prochain creneau disponible apres cette case."):
                return
        task = self.store.find_task(self.cut_task_ref["project_id"], self.cut_task_ref["task_id"])
        if not task:
            messagebox.showerror("Coller", "La tache coupee n'existe plus.")
            self.cut_task_ref = None
            return
        self.store.reopen_user_assignments_from(user_id, day_key, slot_index, exclude=(self.cut_task_ref["project_id"], self.cut_task_ref["task_id"]))
        task["manual_start"] = {"date": day_key, "slot_index": slot_index, "user_id": user_id}
        task["assignee_id"] = user_id
        task["status"] = "a_planifier"
        self.cut_task_ref = None
        self.after_data_change("Tache collee et planning decale")

    def add_absence_on_selected_slot(self) -> None:
        if not self.selected_slot:
            messagebox.showinfo("Absence", "Selectionne une case de depart.")
            return
        user_id, day_key, slot_index = self.selected_slot
        day = parse_date(day_key)
        if not day:
            messagebox.showerror("Absence", "Date invalide.")
            return
        user_name = self.store.user_name(user_id) or user_id
        dialog = self.dialog("Ajouter absence", "380x220")
        dialog.columnconfigure(1, weight=1)
        ttk.Label(dialog, text="Utilisateur").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        ttk.Label(dialog, text=user_name).grid(row=0, column=1, sticky="w", padx=12, pady=8)
        ttk.Label(dialog, text="Debut").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        ttk.Label(dialog, text=f"{day_key} {slot_label(slot_index)}").grid(row=1, column=1, sticky="w", padx=12, pady=8)
        ttk.Label(dialog, text="Duree creneaux").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        duration_var = tk.StringVar(value="1")
        ttk.Spinbox(dialog, from_=1, to=SLOTS_PER_DAY - slot_index, textvariable=duration_var, width=6).grid(row=2, column=1, sticky="w", padx=12, pady=8)
        ttk.Label(dialog, text="Note").grid(row=3, column=0, sticky="w", padx=12, pady=8)
        note_var = tk.StringVar(value="")
        ttk.Entry(dialog, textvariable=note_var).grid(row=3, column=1, sticky="ew", padx=12, pady=8)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=14)

        def save() -> None:
            duration = clamp_int(duration_var.get(), 1, SLOTS_PER_DAY - slot_index, 1)
            self.store.add_block(user_id, day, slot_index, duration, note_var.get().strip())
            self.store.reopen_user_assignments_from(user_id, day_key, slot_index)
            self.after_data_change("Absence ajoutee et planning decale")
            dialog.destroy()

        ttk.Button(buttons, text="Valider", command=save).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def remove_absence_on_selected_slot(self) -> None:
        if not self.selected_slot:
            messagebox.showinfo("Absence", "Selectionne une case avec absence.")
            return
        user_id, day_key, slot_index = self.selected_slot
        day = parse_date(day_key)
        if not day:
            return
        if not self.store.remove_block_at(user_id, day, slot_index):
            messagebox.showinfo("Absence", "Aucune absence sur cette case.")
            return
        self.after_data_change("Absence retiree et planning recalcule")

    def refresh_user_tree(self) -> None:
        self.user_tree.delete(*self.user_tree.get_children())
        for user in self.store.users:
            weekly = ", ".join(f"{DAYS[i]} {duration_label(cap)}" for i, cap in enumerate(user.get("weekly_capacity", [])[:5]))
            special_count = len(user.get("special_days", {}))
            self.user_tree.insert("", tk.END, iid=user["id"], values=(user["name"], weekly, f"{special_count} jour(s)", user.get("note", "")))

    def refresh_project_tree(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        for project in self.store.projects:
            self.project_tree.insert("", tk.END, iid=project["id"], values=(project["name"], len(project.get("tasks", []))))
        if self.selected_project_id and self.selected_project_id in self.project_tree.get_children(""):
            self.project_tree.selection_set(self.selected_project_id)
        elif self.store.projects:
            self.selected_project_id = self.store.projects[0]["id"]
            self.project_tree.selection_set(self.selected_project_id)
        self.refresh_task_tree()

    def refresh_task_tree(self) -> None:
        self.task_tree.delete(*self.task_tree.get_children())
        project = self.store.find_project(self.selected_project_id or "")
        if not project:
            return
        for task in project.get("tasks", []):
            assignee = self.store.user_name(task.get("assignee_id", "")) or "Auto"
            self.task_tree.insert(
                "",
                tk.END,
                iid=task["id"],
                values=(
                    task["name"],
                    duration_label(task.get("duration_slots", 1)),
                    task.get("priority", 0),
                    assignee,
                    task.get("status", ""),
                    task.get("note", ""),
                ),
            )

    def save_all(self) -> None:
        start = parse_date(self.start_var.get())
        if not start:
            messagebox.showerror("Date invalide", "Le debut doit etre au format YYYY-MM-DD.")
            return
        self.store.settings["planning_start"] = (start - timedelta(days=start.weekday())).isoformat()
        self.store.settings["horizon_weeks"] = clamp_int(self.weeks_var.get(), 1, 52, 8)
        self.start_var.set(self.store.settings["planning_start"])
        self.weeks_var.set(str(self.store.settings["horizon_weeks"]))
        self.store.normalize()
        self.store.save()
        self.set_status("Donnees sauvegardees")

    def recalculate_schedule(self, silent: bool = False) -> None:
        self.save_all()
        result = self.store.schedule()
        self.refresh_all()
        if result.unscheduled and not silent:
            details = "\n".join(f"- {row['project_name']} / {row['task_name']}: {row['reason']}" for row in result.unscheduled[:12])
            more = "" if len(result.unscheduled) <= 12 else f"\n... et {len(result.unscheduled) - 12} autre(s)"
            messagebox.showwarning("Taches non planifiees", details + more)
        self.set_status(f"Planification terminee: {len(result.assignments)} segment(s) au total, {len(result.unscheduled)} tache(s) non placee(s)")

    def backup(self) -> None:
        target = self.store.backup()
        self.set_status(f"Backup cree: {target}")
        messagebox.showinfo("Backup", f"Backup cree dans:\n{target}")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def selected_user(self) -> Optional[Dict[str, Any]]:
        selection = self.user_tree.selection()
        return self.store.find_user(selection[0]) if selection else None

    def selected_project(self) -> Optional[Dict[str, Any]]:
        selection = self.project_tree.selection()
        if selection:
            self.selected_project_id = selection[0]
        return self.store.find_project(self.selected_project_id or "")

    def selected_task(self) -> Optional[Dict[str, Any]]:
        project = self.selected_project()
        selection = self.task_tree.selection()
        if not project or not selection:
            return None
        return self.store.find_task(project["id"], selection[0])

    def on_project_selected(self) -> None:
        selection = self.project_tree.selection()
        self.selected_project_id = selection[0] if selection else None
        self.refresh_task_tree()

    def add_user(self) -> None:
        self.open_user_dialog()

    def edit_user(self) -> None:
        user = self.selected_user()
        if not user:
            messagebox.showinfo("Utilisateur", "Selectionne un utilisateur.")
            return
        self.open_user_dialog(user)

    def open_user_dialog(self, user: Optional[Dict[str, Any]] = None) -> None:
        dialog = self.dialog("Utilisateur", "560x560")
        dialog.columnconfigure(1, weight=1)
        ttk.Label(dialog, text="Nom").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        name_var = tk.StringVar(value=user.get("name", "") if user else "")
        ttk.Entry(dialog, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=12, pady=8)

        weekly_vars = []
        ttk.Label(dialog, text="Capacite par jour").grid(row=1, column=0, sticky="nw", padx=12, pady=8)
        weekly_frame = ttk.Frame(dialog)
        weekly_frame.grid(row=1, column=1, sticky="ew", padx=12, pady=8)
        weekly = user.get("weekly_capacity", [SLOTS_PER_DAY] * 5) if user else [SLOTS_PER_DAY] * 5
        for i, day_name in enumerate(DAYS):
            var = tk.StringVar(value=str(weekly[i]))
            weekly_vars.append(var)
            ttk.Label(weekly_frame, text=day_name).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Spinbox(weekly_frame, from_=0, to=SLOTS_PER_DAY, textvariable=var, width=5).grid(row=i, column=1, sticky="w", padx=8, pady=2)
            ttk.Label(weekly_frame, text=f"creneaux ({duration_label(clamp_int(var.get(), 0, SLOTS_PER_DAY, SLOTS_PER_DAY))})").grid(row=i, column=2, sticky="w", pady=2)

        ttk.Label(dialog, text="Jours speciaux").grid(row=2, column=0, sticky="nw", padx=12, pady=8)
        special_frame = ttk.Frame(dialog)
        special_frame.grid(row=2, column=1, sticky="nsew", padx=12, pady=8)
        special_list = tk.Listbox(special_frame, height=8)
        special_list.grid(row=0, column=0, columnspan=4, sticky="nsew")
        special_scroll = ttk.Scrollbar(special_frame, orient=tk.VERTICAL, command=special_list.yview)
        special_scroll.grid(row=0, column=4, sticky="ns")
        special_list.configure(yscrollcommand=special_scroll.set)
        special_days: Dict[str, int] = dict(user.get("special_days", {})) if user else {}

        def redraw_special() -> None:
            special_list.delete(0, tk.END)
            for day_key, slots in sorted(special_days.items()):
                special_list.insert(tk.END, f"{day_key} = {slots} creneau(x) ({duration_label(slots)})")

        date_var = tk.StringVar(value=date.today().isoformat())
        slots_var = tk.StringVar(value="0")
        ttk.Entry(special_frame, textvariable=date_var, width=12).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Spinbox(special_frame, from_=0, to=SLOTS_PER_DAY, textvariable=slots_var, width=5).grid(row=1, column=1, sticky="w", padx=6, pady=6)

        def add_special() -> None:
            parsed = parse_date(date_var.get())
            if not parsed:
                messagebox.showerror("Date invalide", "Format attendu: YYYY-MM-DD.")
                return
            special_days[parsed.isoformat()] = clamp_int(slots_var.get(), 0, SLOTS_PER_DAY, 0)
            redraw_special()

        def remove_special() -> None:
            selection = special_list.curselection()
            if not selection:
                return
            key = special_list.get(selection[0]).split(" = ", 1)[0]
            special_days.pop(key, None)
            redraw_special()

        ttk.Button(special_frame, text="Ajouter", command=add_special).grid(row=1, column=2, padx=3, pady=6)
        ttk.Button(special_frame, text="Supprimer", command=remove_special).grid(row=1, column=3, padx=3, pady=6)
        redraw_special()

        ttk.Label(dialog, text="Note").grid(row=3, column=0, sticky="nw", padx=12, pady=8)
        note_var = tk.StringVar(value=user.get("note", "") if user else "")
        ttk.Entry(dialog, textvariable=note_var).grid(row=3, column=1, sticky="ew", padx=12, pady=8)

        buttons = ttk.Frame(dialog)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=16)

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Utilisateur", "Le nom est obligatoire.")
                return
            duplicate = next((item for item in self.store.users if item["name"].lower() == name.lower() and item is not user), None)
            if duplicate:
                messagebox.showerror("Utilisateur", "Ce nom existe deja.")
                return
            target = user or {"id": new_id()}
            target.update(
                {
                    "name": name,
                    "weekly_capacity": [clamp_int(var.get(), 0, SLOTS_PER_DAY, SLOTS_PER_DAY) for var in weekly_vars],
                    "special_days": dict(sorted(special_days.items())),
                    "note": note_var.get().strip(),
                }
            )
            if user is None:
                self.store.users.append(target)
            self.after_data_change("Utilisateur sauvegarde")
            dialog.destroy()

        ttk.Button(buttons, text="Valider", command=save).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def delete_user(self) -> None:
        user = self.selected_user()
        if not user:
            messagebox.showinfo("Utilisateur", "Selectionne un utilisateur.")
            return
        if not messagebox.askyesno("Supprimer", f"Supprimer {user['name']} ?"):
            return
        self.store.users = [item for item in self.store.users if item["id"] != user["id"]]
        for project in self.store.projects:
            for task in project.get("tasks", []):
                if task.get("assignee_id") == user["id"]:
                    task["assignee_id"] = ""
        self.after_data_change("Utilisateur supprime")

    def add_project(self) -> None:
        self.open_project_dialog()

    def edit_project(self) -> None:
        project = self.selected_project()
        if not project:
            messagebox.showinfo("Etude", "Selectionne une etude.")
            return
        self.open_project_dialog(project)

    def open_project_dialog(self, project: Optional[Dict[str, Any]] = None) -> None:
        dialog = self.dialog("Etude", "420x180")
        dialog.columnconfigure(1, weight=1)
        ttk.Label(dialog, text="Nom").grid(row=0, column=0, sticky="w", padx=12, pady=12)
        name_var = tk.StringVar(value=project.get("name", "") if project else "")
        ttk.Entry(dialog, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=12, pady=12)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=12)

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Etude", "Le nom est obligatoire.")
                return
            duplicate = next((item for item in self.store.projects if item["name"].lower() == name.lower() and item is not project), None)
            if duplicate:
                messagebox.showerror("Etude", "Cette etude existe deja.")
                return
            target = project or {"id": new_id(), "tasks": [], "color": "#dbeafe"}
            target["name"] = name
            if project is None:
                self.store.projects.append(target)
                self.selected_project_id = target["id"]
            self.after_data_change("Etude sauvegardee")
            dialog.destroy()

        ttk.Button(buttons, text="Valider", command=save).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def delete_project(self) -> None:
        project = self.selected_project()
        if not project:
            messagebox.showinfo("Etude", "Selectionne une etude.")
            return
        if not messagebox.askyesno("Supprimer", f"Supprimer l'etude {project['name']} et ses taches ?"):
            return
        self.store.projects = [item for item in self.store.projects if item["id"] != project["id"]]
        self.selected_project_id = None
        self.after_data_change("Etude supprimee")

    def add_task(self) -> None:
        project = self.selected_project()
        if not project:
            messagebox.showinfo("Tache", "Cree ou selectionne une etude.")
            return
        self.open_task_dialog(project)

    def edit_task(self) -> None:
        project = self.selected_project()
        task = self.selected_task()
        if not project or not task:
            messagebox.showinfo("Tache", "Selectionne une tache.")
            return
        self.open_task_dialog(project, task)

    def open_task_dialog(self, project: Dict[str, Any], task: Optional[Dict[str, Any]] = None) -> None:
        dialog = self.dialog("Tache", "520x360")
        dialog.columnconfigure(1, weight=1)
        ttk.Label(dialog, text="Nom").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        name_var = tk.StringVar(value=task.get("name", "") if task else "")
        ttk.Entry(dialog, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(dialog, text="Duree (creneaux de 30 min)").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        duration_var = tk.StringVar(value=str(task.get("duration_slots", 1)) if task else "1")
        ttk.Spinbox(dialog, from_=1, to=500, textvariable=duration_var, width=8).grid(row=1, column=1, sticky="w", padx=12, pady=8)

        ttk.Label(dialog, text="Priorite").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        priority_var = tk.StringVar(value=str(task.get("priority", 2)) if task else "2")
        ttk.Spinbox(dialog, from_=0, to=5, textvariable=priority_var, width=8).grid(row=2, column=1, sticky="w", padx=12, pady=8)

        ttk.Label(dialog, text="Utilisateur").grid(row=3, column=0, sticky="w", padx=12, pady=8)
        user_options = ["Auto"] + [user["name"] for user in self.store.users]
        current_user = self.store.user_name(task.get("assignee_id", "")) if task else "Auto"
        assignee_var = tk.StringVar(value=current_user or "Auto")
        ttk.Combobox(dialog, textvariable=assignee_var, values=user_options, state="readonly").grid(row=3, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(dialog, text="Statut").grid(row=4, column=0, sticky="w", padx=12, pady=8)
        status_var = tk.StringVar(value=task.get("status", "a_planifier") if task else "a_planifier")
        ttk.Combobox(dialog, textvariable=status_var, values=STATUSES, state="readonly").grid(row=4, column=1, sticky="ew", padx=12, pady=8)

        ttk.Label(dialog, text="Note").grid(row=5, column=0, sticky="w", padx=12, pady=8)
        note_var = tk.StringVar(value=task.get("note", "") if task else "")
        ttk.Entry(dialog, textvariable=note_var).grid(row=5, column=1, sticky="ew", padx=12, pady=8)

        buttons = ttk.Frame(dialog)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=16)

        def save() -> None:
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Tache", "Le nom est obligatoire.")
                return
            assignee_id = ""
            if assignee_var.get() != "Auto":
                assignee = next((user for user in self.store.users if user["name"] == assignee_var.get()), None)
                assignee_id = assignee["id"] if assignee else ""
            target = task or {"id": new_id()}
            target.update(
                {
                    "name": name,
                    "duration_slots": clamp_int(duration_var.get(), 1, 500, 1),
                    "priority": clamp_int(priority_var.get(), 0, 5, 2),
                    "assignee_id": assignee_id,
                    "status": status_var.get(),
                    "note": note_var.get().strip(),
                }
            )
            if task is None:
                project.setdefault("tasks", []).append(target)
            self.after_data_change("Tache sauvegardee")
            dialog.destroy()

        ttk.Button(buttons, text="Valider", command=save).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def delete_task(self) -> None:
        project = self.selected_project()
        task = self.selected_task()
        if not project or not task:
            messagebox.showinfo("Tache", "Selectionne une tache.")
            return
        if not messagebox.askyesno("Supprimer", f"Supprimer la tache {task['name']} ?"):
            return
        project["tasks"] = [item for item in project.get("tasks", []) if item["id"] != task["id"]]
        self.after_data_change("Tache supprimee")

    def selected_assignment(self) -> Optional[Dict[str, Any]]:
        selection = self.schedule_tree.selection()
        if selection:
            return next((row for row in self.store.assignments if row.get("id") == selection[0]), None)
        if self.selected_slot:
            user_id, day_key, slot_index = self.selected_slot
            return self.assignment_at_slot(user_id, day_key, slot_index)
        return None

    def mark_selected_task_done(self) -> None:
        row = self.selected_assignment()
        if not row:
            messagebox.showinfo("Planning", "Selectionne une ligne du planning.")
            return
        task = self.store.find_task(row["project_id"], row["task_id"])
        if task:
            task["status"] = "termine"
            self.after_data_change("Tache terminee")

    def mark_selected_task_urgent(self) -> None:
        row = self.selected_assignment()
        if not row:
            messagebox.showinfo("Planning", "Selectionne une ligne du planning.")
            return
        task = self.store.find_task(row["project_id"], row["task_id"])
        if task:
            task["priority"] = 5
            task["status"] = "a_planifier"
            task["manual_start"] = {}
            self.after_data_change("Tache mise en urgent")

    def focus_selected_task(self) -> None:
        row = self.selected_assignment()
        if not row:
            messagebox.showinfo("Planning", "Selectionne une ligne du planning.")
            return
        self.notebook.select(self.tab_projects)
        self.selected_project_id = row["project_id"]
        self.refresh_project_tree()
        self.project_tree.selection_set(row["project_id"])
        self.task_tree.selection_set(row["task_id"])
        self.task_tree.focus(row["task_id"])

    def after_data_change(self, status: str) -> None:
        self.store.normalize()
        self.store.save()
        self.recalculate_schedule(silent=True)
        self.refresh_all()
        self.set_status(status)

    def dialog(self, title: str, geometry: str) -> tk.Toplevel:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry(geometry)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.focus_force()
        return dialog


if __name__ == "__main__":
    PlannerApp()
