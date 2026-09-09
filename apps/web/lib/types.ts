export interface User {
  id: string;
  email: string;
  name: string;
  timezone: string;
  units: "metric" | "imperial";
}

export interface Profile {
  height_cm: number | null;
  birth_year: number | null;
  sex: string | null;
  activity_level: string | null;
  dietary: Record<string, unknown>;
  onboarding_completed: boolean;
}

export interface Goal {
  id: string;
  type: string;
  title: string;
  status: string;
  priority: string;
  start_value: number | null;
  target_value: number | null;
  unit: string | null;
  start_date: string | null;
  target_date: string | null;
  created_at: string;
}

export interface Target {
  id: string;
  key: string;
  value: number;
  unit: string;
  period: string;
  mode: string;
  active: boolean;
}

export interface Food {
  id: string;
  name: string;
  brand: string | null;
  serving_size: number;
  serving_unit: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  source: string;
  barcode?: string | null; // TRACK A
}

export interface FoodLogItem {
  food_id: string | null;
  name: string;
  quantity: number;
  unit: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  estimated?: boolean;
  unmatched?: boolean;
}

export interface FoodLog {
  id: string;
  date: string;
  meal_type: string;
  items: FoodLogItem[];
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  note: string | null;
  created_at: string;
}

export interface NutritionDay {
  date: string;
  calories: number;
  protein: number;
  carbs: number;
  fat: number;
  fiber: number;
  logs: FoodLog[];
  targets: { calories?: number; protein?: number };
}

export interface Recipe {
  id: string;
  name: string;
  description: string | null;
  servings: number;
  prep_minutes: number | null;
  cook_minutes: number | null;
  ingredients: FoodLogItem[];
  steps: string[];
  nutrition: { per_serving: { calories: number; protein: number; carbs: number; fat: number } };
  tags: string[];
  cuisine: string | null;
  created_at: string;
}

export interface Exercise {
  id: string;
  name: string;
  muscle_groups: string[];
  equipment: string | null;
  difficulty: string | null;
}

export interface WorkoutSet {
  weight?: number;
  reps?: number;
  rpe?: number;
  duration_s?: number;
  distance_m?: number;
}

export interface Workout {
  id: string;
  date: string;
  title: string;
  duration_min: number | null;
  exercises: { name: string; sets: WorkoutSet[] }[];
  total_volume: number;
  notes: string | null;
  created_at: string;
  new_prs?: NewPR[]; // TRACK D — only set on the log response
}

export interface WorkoutPlan {
  id: string;
  name: string;
  description: string | null;
  days: {
    name: string;
    exercises: { name: string; sets?: number; reps?: number; weight?: number }[];
  }[];
  active: boolean;
}

export interface PhotoMeta {
  id: string;
  category: string;
  content_type: string;
  size: number;
  notes: string | null;
  date: string | null;
  created_at: string;
}

export interface SleepLog {
  id: string;
  date: string;
  sleep_start: string;
  sleep_end: string;
  duration_min: number;
  quality: number | null;
}

export interface Measurement {
  id: string;
  type: string;
  value: number;
  unit: string;
  date: string;
  notes: string | null;
}

export interface Habit {
  id: string;
  name: string;
  frequency: string;
  target: number | null;
  unit: string | null;
  active: boolean;
}

export interface HabitProgress {
  habit_id: string;
  name: string;
  completed: number;
  window_days: number;
  adherence: number;
  streak: number;
  today_status: string | null;
}

export interface ScheduleEvent {
  id: string;
  type: string;
  title: string;
  start_at: string;
  end_at: string | null;
  recurring: boolean;
  status: string;
}

export interface WeightTrend {
  points: { date: string; value: number }[];
  moving_average: { date: string; value: number }[];
  weekly_rate: number | null;
}

export interface DailySummary {
  date: string;
  nutrition: { calories: number; protein: number; carbs: number; fat: number; fiber: number };
  water_ml: number;
  sleep_minutes: number | null;
  workout_count: number;
  workout_volume: number;
  steps: number;
  habits_completed: number;
  habits_total: number;
  weight: number | null;
  targets: Record<string, number>;
  schedule: ScheduleEvent[];
}

export interface RangeSummary {
  start: string;
  end: string;
  days: number;
  avg_calories: number | null;
  avg_protein: number | null;
  days_food_logged: number;
  avg_water_ml: number | null;
  avg_sleep_minutes: number | null;
  workout_count: number;
  workout_volume: number;
  targets: Record<string, number>;
  calorie_adherence: number | null;
  protein_adherence: number | null;
  habit_adherence: number | null;
  weight: WeightTrend;
  daily_calories: { date: string; calories: number; protein: number }[];
}

export interface ChatAction {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
  status: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  actions?: ChatAction[];
}

export interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

export interface AIProviderInfo {
  id: string;
  label: string;
  kind: "mock" | "openai_compatible" | "cli";
  detected: boolean;
  needs_key: boolean;
  default_base_url: string;
  default_model: string;
  hint: string;
}

export interface AISettings {
  provider?: string;
  model?: string;
  base_url?: string;
  has_api_key?: boolean;
  mode?: "local-only" | "hybrid" | "hosted";
}

export interface OnboardingProposal {
  profile: {
    dietary?: Record<string, unknown>; activity_level?: string;
    height_cm?: number | null; birth_year?: number | null; sex?: string | null;
  };
  weight_kg?: number | null;
  goals: { type: string; title: string; start_value?: number; target_value?: number; unit?: string }[];
  targets: { key: string; value: number; unit: string; period: string; source?: string; reason?: string }[];
  suggested_targets?: { key: string; value: number; unit: string; period: string; source?: string; reason?: string }[];
  events: { type: string; title: string; bydays?: number[]; hour?: number; end_hour?: number }[];
  workout_plan?: { name: string; days: { name: string; exercises: { name: string; sets?: number; reps?: number }[] }[] } | null;
  memories: { type: string; key: string; value: string }[];
}

// === TRACK C ===

export interface PlanVersion {
  id: string;
  version: number;
  snapshot: Record<string, unknown>;
  reason: string;
  actor: "user" | "ai";
  created_at: string;
}

export interface RecentPlanVersion extends PlanVersion {
  entity_type: string;
  entity_id: string;
}

export interface SearchResults {
  foods: { id: string; name: string; calories: number }[];
  recipes: { id: string; name: string }[];
  exercises: { id: string; name: string }[];
  conversations: { id: string; title: string }[];
}

export interface SemanticSearchResponse {
  results: { entity_type: string; entity_id: string; snippet: string; score: number }[];
  message?: string;
}

// === TRACK A ===

export type ImportKind = "measurements" | "food_logs" | "workouts";

export interface ImportRowError {
  row: number;
  message: string;
}

export interface ImportPreview {
  rows: Record<string, unknown>[];
  errors: ImportRowError[];
  total: number;
  valid: number;
}

export interface ImportResult {
  imported: number;
  skipped: number;
}

// === TRACK B ===

export interface Review {
  start: string;
  end: string;
  data: RangeSummary;
  narrative: string | null;
  generated_at: string;
}

export interface ChatStreamHandlers {
  onDelta?: (text: string) => void;
  onActions?: (actions: ChatAction[]) => void;
  onDone?: (conversationId: string, reply: string) => void;
}

// === TRACK D ===

export interface SavedMeal {
  id: string;
  name: string;
  items: FoodLogItem[];
  use_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface FrequentFood {
  food_id: string | null;
  name: string;
  calories: number;
  protein: number;
  uses: number;
}

export interface NewPR {
  exercise: string;
  kind: "weight" | "volume";
  value: number;
  previous: number | null;
}

export interface PRRecord {
  exercise: string;
  best_weight: number | null;
  reps_at_best: number | null;
  best_volume_set: number | null;
  date: string | null;
  is_recent: boolean;
}

export interface ActivityDay {
  date: string;
  workouts: number;
  habits_done: number;
  habits_total: number;
  logged_food: boolean;
  score: 0 | 1 | 2 | 3;
}

export interface StallFactor {
  label: string;
  value: number | null;
  verdict: "ok" | "low";
}

export interface StallInfo {
  applies: boolean;
  stalled: boolean;
  weekly_rate: number | null;
  weeks_tracked: number;
  factors: StallFactor[];
  suggestion: string;
}

export interface PantryItem {
  id: string;
  name: string;
  quantity: number;
  unit: string;
  expires_on: string | null;
  location: string;
  food_id: string | null;
  created_at: string;
}

export interface RecipeMatch {
  recipe_id: string;
  name: string;
  coverage: number;
  missing: string[];
}
