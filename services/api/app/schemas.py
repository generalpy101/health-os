from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

OptDate = date | None  # avoids field-name/type-name collision in class bodies

MEAL_TYPES = ["breakfast", "brunch", "lunch", "snack", "dinner", "dessert", "pre_workout", "post_workout", "other"]
GOAL_TYPES = [
    "weight_loss", "weight_gain", "maintenance", "muscle_gain", "strength", "endurance",
    "fitness", "sleep", "hydration", "habit", "nutrition", "body_measurement", "activity", "sport", "custom",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth / users ----------

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: UUID
    email: str
    name: str
    timezone: str
    units: str


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    units: Literal["metric", "imperial"] | None = None


class ProfileIn(BaseModel):
    height_cm: float | None = Field(default=None, gt=0, lt=300)
    birth_year: int | None = Field(default=None, gt=1900, lt=2100)
    sex: str | None = None
    activity_level: str | None = None
    dietary: dict[str, Any] | None = None
    onboarding_completed: bool | None = None


class ProfileOut(ORMModel):
    height_cm: float | None
    birth_year: int | None
    sex: str | None
    activity_level: str | None
    dietary: dict[str, Any]
    onboarding_completed: bool


class PreferencesIn(BaseModel):
    data: dict[str, Any]


# ---------- goals / targets ----------

class GoalIn(BaseModel):
    type: str = Field(default="custom", max_length=40)
    title: str = Field(min_length=1, max_length=200)
    priority: str = "primary"
    start_value: float | None = None
    target_value: float | None = None
    unit: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class GoalPatch(BaseModel):
    type: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    priority: str | None = None
    start_value: float | None = None
    target_value: float | None = None
    unit: str | None = None
    target_date: date | None = None
    meta: dict[str, Any] | None = None


class GoalOut(ORMModel):
    id: UUID
    type: str
    title: str
    status: str
    priority: str
    start_value: float | None
    target_value: float | None
    unit: str | None
    start_date: date | None
    target_date: date | None
    meta: dict[str, Any]
    created_at: datetime


class TargetIn(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    value: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=24)
    period: str = "daily"
    mode: str = "minimum"
    range_low: float | None = None
    range_high: float | None = None
    source: str = "user"
    reason: str | None = None


class TargetPatch(BaseModel):
    value: float | None = Field(default=None, gt=0)
    unit: str | None = None
    period: str | None = None
    mode: str | None = None
    active: bool | None = None
    reason: str | None = None


class TargetOut(ORMModel):
    id: UUID
    key: str
    value: float
    unit: str
    period: str
    mode: str
    source: str
    reason: str | None
    active: bool
    created_at: datetime


# ---------- nutrition ----------

class FoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = None
    serving_size: float = Field(default=100, gt=0)
    serving_unit: str = "g"
    calories: float = Field(ge=0)
    protein: float = Field(default=0, ge=0)
    carbs: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)
    fiber: float = Field(default=0, ge=0)
    sugar: float = Field(default=0, ge=0)
    sodium: float = Field(default=0, ge=0)
    source: str = "custom"
    barcode: str | None = None


class FoodOut(ORMModel):
    id: UUID
    user_id: UUID | None
    name: str
    brand: str | None
    serving_size: float
    serving_unit: str
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    source: str
    barcode: str | None = None  # TRACK A


class FoodLogItemIn(BaseModel):
    food_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0)
    unit: str = "g"
    # optional explicit nutrients (user correction / AI photo estimate with uncertainty)
    calories: float | None = Field(default=None, ge=0)
    protein: float | None = Field(default=None, ge=0)
    carbs: float | None = Field(default=None, ge=0)
    fat: float | None = Field(default=None, ge=0)
    fiber: float | None = Field(default=None, ge=0)
    estimated: bool | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    lower_kcal: float | None = Field(default=None, ge=0)
    upper_kcal: float | None = Field(default=None, ge=0)


class FoodLogItemOut(BaseModel):
    food_id: UUID | None = None
    name: str
    quantity: float
    unit: str
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    estimated: bool = False
    confidence: float | None = None


class FoodLogIn(BaseModel):
    date: OptDate = None
    meal_type: str = "other"
    items: list[FoodLogItemIn] = Field(min_length=1)
    note: str | None = None
    source: str = "manual"


class FoodLogOut(ORMModel):
    id: UUID
    date: date
    meal_type: str
    items: list[dict[str, Any]]
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    note: str | None
    source: str
    created_at: datetime


class NutritionDayOut(BaseModel):
    date: date
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    logs: list[FoodLogOut]
    targets: dict[str, float] = Field(default_factory=dict)


# ---------- recipes / meal plans ----------

class RecipeIngredientIn(BaseModel):
    food_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0)
    unit: str = "g"


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    servings: float = Field(default=1, gt=0)
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    cuisine: str | None = None
    difficulty: str | None = None


class RecipeOut(ORMModel):
    id: UUID
    name: str
    description: str | None
    servings: float
    prep_minutes: int | None
    cook_minutes: int | None
    ingredients: list[dict[str, Any]]
    steps: list[str]
    nutrition: dict[str, Any]
    tags: list[str]
    cuisine: str | None
    difficulty: str | None
    created_at: datetime


class MealPlanIn(BaseModel):
    date: date
    meal_type: str = "other"
    recipe_id: UUID | None = None
    name: str = Field(default="", max_length=200)
    servings: float = Field(default=1, gt=0)
    notes: str | None = None


class MealPlanOut(ORMModel):
    id: UUID
    date: date
    meal_type: str
    recipe_id: UUID | None
    name: str
    servings: float
    notes: str | None


# ---------- fitness ----------

class ExerciseOut(ORMModel):
    id: UUID
    name: str
    muscle_groups: list[str]
    movement_pattern: str | None
    equipment: str | None
    difficulty: str | None
    instructions: str | None


class SetIn(BaseModel):
    weight: float | None = Field(default=None, ge=0)
    reps: float | None = Field(default=None, ge=0)
    rpe: float | None = Field(default=None, ge=0, le=10)
    duration_s: float | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)


class ExerciseLogIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sets: list[SetIn] = Field(default_factory=list)


class WorkoutIn(BaseModel):
    date: OptDate = None
    title: str = Field(default="Workout", max_length=200)
    duration_min: int | None = Field(default=None, ge=0)
    exercises: list[ExerciseLogIn] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return v.strip() or "Workout"


class WorkoutOut(ORMModel):
    id: UUID
    date: date
    title: str
    duration_min: int | None
    exercises: list[dict[str, Any]]
    total_volume: float
    notes: str | None
    created_at: datetime


class WorkoutPlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    days: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = True


class WorkoutPlanOut(ORMModel):
    id: UUID
    name: str
    description: str | None
    days: list[dict[str, Any]]
    active: bool
    created_at: datetime


class ActivityIn(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    date: OptDate = None
    duration_min: float | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    calories_est: float | None = Field(default=None, ge=0)
    intensity: str | None = None
    notes: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ActivityOut(ORMModel):
    id: UUID
    type: str
    date: date
    duration_min: float | None
    distance_m: float | None
    steps: int | None
    calories_est: float | None
    intensity: str | None
    notes: str | None
    meta: dict[str, Any]


# ---------- health logs ----------

class SleepIn(BaseModel):
    date: OptDate = None
    sleep_start: datetime
    sleep_end: datetime
    quality: int | None = Field(default=None, ge=1, le=5)
    interruptions: int | None = Field(default=None, ge=0)
    notes: str | None = None


class SleepOut(ORMModel):
    id: UUID
    date: date
    sleep_start: datetime
    sleep_end: datetime
    duration_min: int
    quality: int | None
    notes: str | None


class WaterIn(BaseModel):
    amount_ml: float = Field(gt=0, le=5000)
    date: OptDate = None


class WaterOut(ORMModel):
    id: UUID
    date: date
    amount_ml: float
    created_at: datetime


class MeasurementIn(BaseModel):
    type: str = Field(default="weight", max_length=40)
    value: float = Field(gt=0)
    unit: str = Field(default="kg", max_length=16)
    date: OptDate = None
    notes: str | None = None


class MeasurementOut(ORMModel):
    id: UUID
    type: str
    value: float
    unit: str
    date: date
    source: str
    notes: str | None


# ---------- habits ----------

class HabitIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    frequency: str = "daily"
    target: float | None = None
    unit: str | None = None
    reminder_time: str | None = None
    goal_id: UUID | None = None


class HabitOut(ORMModel):
    id: UUID
    name: str
    frequency: str
    target: float | None
    unit: str | None
    reminder_time: str | None
    active: bool
    created_at: datetime


class HabitLogIn(BaseModel):
    date: OptDate = None
    status: str = "completed"
    value: float | None = None
    notes: str | None = None


class HabitLogOut(ORMModel):
    id: UUID
    habit_id: UUID
    date: date
    status: str
    value: float | None
    notes: str | None


# ---------- schedule ----------

class EventIn(BaseModel):
    type: str = Field(default="custom", max_length=32)
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime | None = None
    recurrence: dict[str, Any] | None = None
    linked_entity_type: str | None = None
    linked_entity_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class EventPatch(BaseModel):
    type: str | None = None
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    recurrence: dict[str, Any] | None = None
    status: str | None = None
    meta: dict[str, Any] | None = None


class EventOut(ORMModel):
    id: UUID
    type: str
    title: str
    start_at: datetime
    end_at: datetime | None
    timezone: str
    recurrence: dict[str, Any] | None
    status: str
    source: str
    meta: dict[str, Any]


# ---------- memories / AI ----------

class MemoryOut(ORMModel):
    id: UUID
    type: str
    key: str
    value: dict[str, Any]
    source: str
    confidence: float
    status: str
    created_at: datetime


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: UUID | None = None


class ActionOut(ORMModel):
    id: UUID
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    status: str
    created_at: datetime


class ChatOut(BaseModel):
    conversation_id: UUID
    reply: str
    actions: list[ActionOut] = Field(default_factory=list)


class MessageOut(ORMModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class ConversationOut(ORMModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class OnboardingParseIn(BaseModel):
    text: str = Field(min_length=3, max_length=8000)


class OnboardingCommitIn(BaseModel):
    profile: ProfileIn = Field(default_factory=ProfileIn)
    weight_kg: float | None = Field(default=None, gt=0, lt=500)  # recorded as first measurement
    goals: list[GoalIn] = Field(default_factory=list)
    targets: list[TargetIn] = Field(default_factory=list)
    events: list[EventIn] = Field(default_factory=list)
    habits: list[HabitIn] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    workout_plan: dict[str, Any] | None = None  # {name, days:[{name, exercises:[...]}]}
    replace: bool = False  # redo flow: archive current goals/targets/onboarding events first


# ---------- recommendations ----------

class RecommendationOut(ORMModel):
    id: UUID
    title: str
    reason: str | None
    priority: str
    confidence: float
    status: str
    actions: list[dict[str, Any]]
    source: str
    created_at: datetime


class RecommendationPatch(BaseModel):
    status: str  # accepted|rejected|ignored


# ---------- track c: integrations / ingest ----------

class IngestEventIn(BaseModel):
    metric: str = Field(min_length=1, max_length=40)
    value: float
    unit: str | None = Field(default=None, max_length=24)
    observed_at: datetime
    external_id: str | None = Field(default=None, max_length=120)


class IngestIn(BaseModel):
    source: str = Field(min_length=1, max_length=40)  # apple_health|shortcut|...
    events: list[IngestEventIn] = Field(default_factory=list, max_length=500)
# ---------- TRACK A: imports ----------

IMPORT_KINDS = ["measurements", "food_logs", "workouts"]


class ImportPreviewIn(BaseModel):
    kind: Literal["measurements", "food_logs", "workouts"]
    format: Literal["csv", "json"]
    text: str = Field(min_length=1, max_length=400_000)


class ImportRowError(BaseModel):
    row: int  # 1-based data row index
    message: str


class ImportPreviewOut(BaseModel):
    rows: list[dict[str, Any]]
    errors: list[ImportRowError]
    total: int
    valid: int


class ImportCommitIn(BaseModel):
    kind: Literal["measurements", "food_logs", "workouts"]
    rows: list[dict[str, Any]] = Field(max_length=2000)


class ImportCommitOut(BaseModel):
    imported: int
    skipped: int
