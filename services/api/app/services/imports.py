"""TRACK A: CSV/JSON import pipeline — parse text, validate rows, preview, commit.

Import rows are data coming over the wire: every field is validated here
(dates ISO, numbers > 0, unknown measurement types allowed as custom types).
Preview writes nothing; commit re-validates and writes through the existing
services so audit + deterministic totals stay intact.
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..schemas import (ExerciseLogIn, FoodLogIn, FoodLogItemIn, ImportCommitIn,
                       ImportPreviewIn, MeasurementIn, SetIn, WorkoutIn)
from . import fitness as fitness_service
from . import health as health_service
from . import nutrition as nutrition_service

MAX_ROWS = 2000

Row = dict[str, Any]
NormResult = tuple[Row | None, str | None]


# ---------- field helpers ----------

def _iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        try:
            v = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _text(value: Any, max_len: int = 200) -> str:
    return str(value).strip()[:max_len] if value is not None else ""


def _lower_keys(raw: Any) -> Any:
    if isinstance(raw, dict):
        return {str(k).strip().lower(): v for k, v in raw.items()}
    return raw


# ---------- row normalizers (raw wire dict -> normalized row | error) ----------

def _norm_measurement(raw: Row) -> NormResult:
    d = _iso_date(raw.get("date"))
    if d is None:
        return None, "missing or invalid date (use YYYY-MM-DD)"
    value = _number(raw.get("value"))
    if value is None:
        return None, "missing or invalid value"
    if value <= 0:
        return None, "value must be > 0"
    row: Row = {"date": d.isoformat(), "type": _text(raw.get("type"), 40) or "weight", "value": value}
    unit = _text(raw.get("unit"), 16)
    if unit:
        row["unit"] = unit
    return row, None


def _norm_food_log(raw: Row) -> NormResult:
    d = _iso_date(raw.get("date"))
    if d is None:
        return None, "missing or invalid date (use YYYY-MM-DD)"
    name = _text(raw.get("name"))
    if not name:
        return None, "missing name"
    row: Row = {"date": d.isoformat(), "name": name,
                "meal_type": _text(raw.get("meal_type"), 32) or "other"}
    quantity = raw.get("quantity")
    if quantity not in (None, ""):
        q = _number(quantity)
        if q is None or q <= 0:
            return None, "quantity must be a number > 0"
        row["quantity"] = q
        unit = _text(raw.get("unit"), 24)
        if unit:
            row["unit"] = unit
    for key in ("calories", "protein", "carbs", "fat"):
        v = raw.get(key)
        if v in (None, ""):
            continue
        n = _number(v)
        if n is None or n < 0:
            return None, f"{key} must be a number >= 0"
        row[key] = n
    return row, None


def _norm_workout(raw: Row) -> NormResult:
    d = _iso_date(raw.get("date"))
    if d is None:
        return None, "missing or invalid date (use YYYY-MM-DD)"
    exercise = _text(raw.get("exercise") or raw.get("name"))
    if not exercise:
        return None, "missing exercise"
    row: Row = {"date": d.isoformat(), "exercise": exercise}
    title = _text(raw.get("title"))
    if title:
        row["title"] = title
    sets = raw.get("sets")
    if sets not in (None, ""):
        s = _number(sets)
        if s is None or s <= 0 or not float(s).is_integer():
            return None, "sets must be a whole number > 0"
        row["sets"] = int(s)
    reps = raw.get("reps")
    if reps not in (None, ""):
        r = _number(reps)
        if r is None or r <= 0:
            return None, "reps must be a number > 0"
        row["reps"] = r
    weight = raw.get("weight")
    if weight not in (None, ""):
        w = _number(weight)
        if w is None or w < 0:
            return None, "weight must be a number >= 0"
        row["weight"] = w
    return row, None


_NORMALIZERS: dict[str, Callable[[Row], NormResult]] = {
    "measurements": _norm_measurement,
    "food_logs": _norm_food_log,
    "workouts": _norm_workout,
}


# ---------- parsing ----------

def _parse_rows(format_: str, text: str, kind: str) -> tuple[list[tuple[int, Any]], list[dict]]:
    """Split raw text into (1-based row index, raw row) pairs plus fatal/parse errors."""
    errors: list[dict] = []
    if format_ == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return [], [{"row": 0, "message": f"invalid JSON: {e.msg}"}]
        if isinstance(data, dict):  # tolerate {"rows": [...]} / {"food_logs": [...]}
            data = data.get("rows", data.get(kind))
        if not isinstance(data, list):
            return [], [{"row": 0, "message": "JSON must be a list of objects (or {\"rows\": [...]})"}]
        return [(i, _lower_keys(item)) for i, item in enumerate(data, 1)], errors

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or all(not (f or "").strip() for f in reader.fieldnames):
        return [], [{"row": 0, "message": "CSV needs a header row (e.g. date,value for measurements)"}]
    rows: list[tuple[int, Any]] = []
    for i, raw in enumerate(reader, 1):
        row = {_text(k).lower(): (v.strip() if isinstance(v, str) else v)
               for k, v in raw.items() if k is not None}
        if all(v in (None, "") for v in row.values()):
            continue  # whitespace-only line
        if raw.get(None):  # DictReader collects extra columns under the None key
            errors.append({"row": i, "message": "more columns than the header — check commas"})
        rows.append((i, row))
    return rows, errors


def preview(data: ImportPreviewIn) -> dict:
    raw_rows, errors = _parse_rows(data.format, data.text, data.kind)
    total = len(raw_rows)
    if total > MAX_ROWS:
        errors.append({"row": 0, "message": f"too many rows (max {MAX_ROWS})"})
        raw_rows = raw_rows[:MAX_ROWS]
    normalize = _NORMALIZERS[data.kind]
    rows: list[Row] = []
    for i, raw in raw_rows:
        if not isinstance(raw, dict):
            errors.append({"row": i, "message": "row must be an object"})
            continue
        row, err = normalize(raw)
        if err:
            errors.append({"row": i, "message": err})
        else:
            rows.append(row)
    errors.sort(key=lambda e: e["row"])
    return {"rows": rows, "errors": errors, "total": total, "valid": len(rows)}


# ---------- commit ----------

async def commit(db: AsyncSession, user: User, data: ImportCommitIn) -> dict:
    normalize = _NORMALIZERS[data.kind]
    valid: list[Row] = []
    skipped = 0
    for raw in data.rows[:MAX_ROWS]:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        row, err = normalize(_lower_keys(raw))
        if err:
            skipped += 1
        else:
            valid.append(row)
    if data.kind == "measurements":
        imported = await _commit_measurements(db, user, valid)
    elif data.kind == "food_logs":
        imported = await _commit_food_logs(db, user, valid)
    else:
        imported = await _commit_workouts(db, user, valid)
    return {"imported": imported, "skipped": skipped + (len(valid) - imported)}


async def _commit_measurements(db: AsyncSession, user: User, rows: list[Row]) -> int:
    imported = 0
    for row in rows:
        try:
            await health_service.record_measurement(db, user, MeasurementIn(
                type=row["type"], value=row["value"], unit=row.get("unit") or "kg",
                date=row["date"]), source="import")
            imported += 1
        except Exception:
            await db.rollback()
    return imported


def _group(rows: list[Row], keys: tuple[str, ...], default: str = "") -> dict[tuple, list[Row]]:
    groups: dict[tuple, list[Row]] = {}
    for row in rows:
        groups.setdefault(tuple(row.get(k) or default for k in keys), []).append(row)
    return groups


async def _commit_food_logs(db: AsyncSession, user: User, rows: list[Row]) -> int:
    imported = 0
    for (day, meal_type), members in _group(rows, ("date", "meal_type")).items():
        items = []
        for r in members:
            item: Row = {
                "name": r["name"],
                "quantity": r.get("quantity") or 1,
                "unit": r.get("unit") or ("g" if r.get("quantity") else "serving"),
            }
            for key in ("calories", "protein", "carbs", "fat"):
                if key in r:
                    item[key] = r[key]
            if "calories" in r:
                item["estimated"] = True  # explicit numbers override DB matches
            items.append(FoodLogItemIn(**item))
        try:
            await nutrition_service.log_food(
                db, user, FoodLogIn(date=day, meal_type=meal_type, items=items), source="import")
            imported += len(members)
        except Exception:
            await db.rollback()
    return imported


async def _commit_workouts(db: AsyncSession, user: User, rows: list[Row]) -> int:
    imported = 0
    for (day, title), members in _group(rows, ("date", "title"), "Workout").items():
        exercises = []
        for r in members:
            set_: dict[str, float] = {}
            if r.get("weight") is not None:
                set_["weight"] = r["weight"]
            if r.get("reps") is not None:
                set_["reps"] = r["reps"]
            sets = [SetIn(**set_) for _ in range(r.get("sets") or 1)] if set_ else []
            exercises.append(ExerciseLogIn(name=r["exercise"], sets=sets))
        try:
            await fitness_service.log_workout(
                db, user, WorkoutIn(date=day, title=title, exercises=exercises), source="import")
            imported += len(members)
        except Exception:
            await db.rollback()
    return imported
