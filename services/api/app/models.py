import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, generic JSON elsewhere (SQLite for tests/dev).
JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    timezone: Mapped[str] = mapped_column(sa.String(64), default="UTC")
    units: Mapped[str] = mapped_column(sa.String(16), default="metric")  # metric | imperial


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), unique=True, index=True)
    height_cm: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    birth_year: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    activity_level: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    dietary: Mapped[dict] = mapped_column(JSON, default=dict)  # diet, allergies, dislikes, cuisines
    onboarding_completed: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class UserPreference(TimestampMixin, Base):
    __tablename__ = "user_preferences"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), unique=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # dashboard layout, theme, ai mode, notifications


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)  # sha256 of token
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class UserMemory(TimestampMixin, Base):
    __tablename__ = "user_memories"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(sa.String(32), index=True)  # fact|preference|behavior|inference
    key: Mapped[str] = mapped_column(sa.String(120), index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(sa.String(32), default="user")  # user|behavior|ai
    confidence: Mapped[float] = mapped_column(sa.Float, default=1.0)
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # candidate|active|confirmed|deprecated
    last_confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(sa.String(40), index=True)  # weight_loss|muscle_gain|...|custom
    title: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[str] = mapped_column(sa.String(20), default="active")  # active|paused|completed|archived
    priority: Mapped[str] = mapped_column(sa.String(20), default="primary")
    start_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    target_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    start_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Target(TimestampMixin, Base):
    __tablename__ = "targets"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(sa.String(60), index=True)  # calories|protein|water|steps|sleep_minutes|workouts|custom
    value: Mapped[float] = mapped_column(sa.Float)
    unit: Mapped[str] = mapped_column(sa.String(24))
    period: Mapped[str] = mapped_column(sa.String(16), default="daily")  # daily|weekly|monthly
    mode: Mapped[str] = mapped_column(sa.String(16), default="minimum")  # minimum|maximum|exact|range
    range_low: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    range_high: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    effective_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="user")  # user|ai|calculated
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)


class Food(TimestampMixin, Base):
    __tablename__ = "foods"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), nullable=True, index=True)  # null = global
    name: Mapped[str] = mapped_column(sa.String(200), index=True)
    brand: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    serving_size: Mapped[float] = mapped_column(sa.Float, default=100)
    serving_unit: Mapped[str] = mapped_column(sa.String(24), default="g")
    calories: Mapped[float] = mapped_column(sa.Float, default=0)  # per serving_size
    protein: Mapped[float] = mapped_column(sa.Float, default=0)
    carbs: Mapped[float] = mapped_column(sa.Float, default=0)
    fat: Mapped[float] = mapped_column(sa.Float, default=0)
    fiber: Mapped[float] = mapped_column(sa.Float, default=0)
    sugar: Mapped[float] = mapped_column(sa.Float, default=0)
    sodium: Mapped[float] = mapped_column(sa.Float, default=0)  # mg
    source: Mapped[str] = mapped_column(sa.String(40), default="custom")  # seed|custom|openfoodfacts|usda|ai_estimate
    barcode: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class FoodLog(Base):
    __tablename__ = "food_logs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)  # user-local date
    meal_type: Mapped[str] = mapped_column(sa.String(32), default="other")
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{food_id?,name,quantity,unit,calories,protein,carbs,fat,fiber,estimated?,confidence?,lower?,upper?}]
    calories: Mapped[float] = mapped_column(sa.Float, default=0)  # deterministic totals
    protein: Mapped[float] = mapped_column(sa.Float, default=0)
    carbs: Mapped[float] = mapped_column(sa.Float, default=0)
    fat: Mapped[float] = mapped_column(sa.Float, default=0)
    fiber: Mapped[float] = mapped_column(sa.Float, default=0)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="manual")  # manual|ai|photo|import
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipes"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(200), index=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    servings: Mapped[float] = mapped_column(sa.Float, default=1)
    prep_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    cook_minutes: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    ingredients: Mapped[list] = mapped_column(JSON, default=list)  # [{food_id?,name,quantity,unit,calories,protein,carbs,fat,fiber}]
    steps: Mapped[list] = mapped_column(JSON, default=list)  # ["..."]
    nutrition: Mapped[dict] = mapped_column(JSON, default=dict)  # per serving, computed + total
    tags: Mapped[list] = mapped_column(JSON, default=list)
    cuisine: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="user")
    schema_version: Mapped[str] = mapped_column(sa.String(20), default="recipe.v1")


class MealPlan(Base):
    __tablename__ = "meal_plans"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    meal_type: Mapped[str] = mapped_column(sa.String(32), default="other")
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, sa.ForeignKey("recipes.id"), nullable=True)
    name: Mapped[str] = mapped_column(sa.String(200), default="")
    servings: Mapped[float] = mapped_column(sa.Float, default=1)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Exercise(Base):
    __tablename__ = "exercises"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(200), unique=True, index=True)
    muscle_groups: Mapped[list] = mapped_column(JSON, default=list)
    movement_pattern: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    equipment: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    instructions: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)


class WorkoutPlan(TimestampMixin, Base):
    __tablename__ = "workout_plans"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    days: Mapped[list] = mapped_column(JSON, default=list)  # [{name, exercises:[{name, sets, reps, weight?, rest_s?, notes?}]}]
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    title: Mapped[str] = mapped_column(sa.String(200), default="Workout")
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_min: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    exercises: Mapped[list] = mapped_column(JSON, default=list)  # [{name, sets:[{weight,reps,rpe,duration_s,distance_m}]}]
    total_volume: Mapped[float] = mapped_column(sa.Float, default=0)  # kg, computed
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Activity(Base):
    __tablename__ = "activities"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(sa.String(40), index=True)  # walking|running|cycling|swimming|sport|custom
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    start_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_min: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    calories_est: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    intensity: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="manual")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # swimming: pool_length, laps, stroke, sets
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SleepLog(Base):
    __tablename__ = "sleep_logs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)  # local wake date
    sleep_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    sleep_end: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    duration_min: Mapped[int] = mapped_column(sa.Integer)
    quality: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # 1-5
    interruptions: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="manual")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class WaterLog(Base):
    __tablename__ = "water_logs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    amount_ml: Mapped[float] = mapped_column(sa.Float)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Habit(TimestampMixin, Base):
    __tablename__ = "habits"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(160))
    frequency: Mapped[str] = mapped_column(sa.String(16), default="daily")  # daily|weekly
    target: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    reminder_time: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, sa.ForeignKey("goals.id"), nullable=True)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)


class HabitLog(Base):
    __tablename__ = "habit_logs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    habit_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("habits.id"), index=True)
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="completed")  # completed|partial|skipped
    value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(sa.String(40), index=True)  # weight|body_fat|waist|custom...
    value: Mapped[float] = mapped_column(sa.Float)
    unit: Mapped[str] = mapped_column(sa.String(16), default="kg")
    date: Mapped[date] = mapped_column(sa.Date, index=True)
    measured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), default="manual")
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ScheduleEvent(TimestampMixin, Base):
    __tablename__ = "schedule_events"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(sa.String(32), default="custom")  # meal|workout|swimming|sleep|work|reminder|habit|custom
    title: Mapped[str] = mapped_column(sa.String(200))
    start_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(sa.String(64), default="UTC")
    recurrence: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {freq:weekly, bydays:[0,2,4]}
    status: Mapped[str] = mapped_column(sa.String(20), default="planned")  # planned|done|skipped|cancelled
    source: Mapped[str] = mapped_column(sa.String(32), default="user")
    linked_entity_type: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    linked_entity_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class AIConversation(TimestampMixin, Base):
    __tablename__ = "ai_conversations"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(sa.String(200), default="Conversation")


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("ai_conversations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(sa.String(16))  # user|assistant|tool
    content: Mapped[str] = mapped_column(sa.Text, default="")
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    token_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class AIAction(Base):
    __tablename__ = "ai_actions"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    tool: Mapped[str] = mapped_column(sa.String(60))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(24), default="executed")  # proposed|pending_confirmation|executed|failed|rejected|reverted
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    provider: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(sa.String(240))
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    priority: Mapped[str] = mapped_column(sa.String(16), default="medium")
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.5)
    status: Mapped[str] = mapped_column(sa.String(16), default="open")  # open|accepted|rejected|ignored
    actions: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(sa.String(32), default="ai")
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class Photo(TimestampMixin, Base):
    __tablename__ = "photos"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(sa.String(24), default="other")  # progress|meal|body|document|other
    storage_key: Mapped[str] = mapped_column(sa.String(300))
    content_type: Mapped[str] = mapped_column(sa.String(80))
    size: Mapped[int] = mapped_column(sa.Integer, default=0)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    event: Mapped[str] = mapped_column(sa.String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


# === TRACK C ===

class PlanVersion(Base):
    """Immutable snapshot of a goal/target/workout_plan row taken BEFORE a mutation.

    Enables revert: the snapshot is written back through the normal service path.
    """
    __tablename__ = "plan_versions"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(40), index=True)  # goal|target|workout_plan
    entity_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    version: Mapped[int] = mapped_column(sa.Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # full row, pre-change
    reason: Mapped[str] = mapped_column(sa.String(200), default="")
    actor: Mapped[str] = mapped_column(sa.String(16), default="user")  # user|ai
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class IntegrationEvent(Base):
    """Raw event ingested from a device/shortcut. unique(user, source, external_id)
    makes re-ingest idempotent; rows with NULL external_id are always accepted."""
    __tablename__ = "integration_events"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "source", "external_id", name="uq_integration_event"),
    )
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(sa.String(40), index=True)  # apple_health|shortcut|...
    external_id: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    metric: Mapped[str] = mapped_column(sa.String(40), index=True)  # steps|weight|water_ml|...
    value: Mapped[float] = mapped_column(sa.Float)
    unit: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Embedding(Base):
    """Cache of text embeddings for semantic search. vector is a plain JSON list of
    floats (portable to SQLite); cosine similarity is computed in Python."""
    __tablename__ = "embeddings"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_embedding_entity"),
    )
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(40))  # recipe|food|memory
    entity_id: Mapped[str] = mapped_column(sa.String(64))
    model: Mapped[str] = mapped_column(sa.String(120), default="")
    text_hash: Mapped[str] = mapped_column(sa.String(64), default="")  # re-embed when text changes
    vector: Mapped[list] = mapped_column(JSON, default=list)
# === TRACK B ===

class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(sa.String(60), index=True)  # generate_review|check_reminders|...
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(sa.String(16), default="pending", index=True)  # pending|running|done|failed
    run_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))  # weekly|monthly
    period_start: Mapped[date] = mapped_column(sa.Date)
    period_end: Mapped[date] = mapped_column(sa.Date)
    narrative: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # cached range/monthly summary
    generated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    __table_args__ = (sa.UniqueConstraint("user_id", "kind", "period_start"),)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, sa.ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(sa.Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSON, default=dict)  # {p256dh, auth}
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
