import type {
  ChatAction, Conversation, DailySummary, Food, FoodLog, Goal, Habit, HabitProgress,
  Measurement, NutritionDay, OnboardingProposal, Profile, RangeSummary, Recipe, ScheduleEvent,
  SleepLog, Target, User, WeightTrend, Workout,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// ---------- offline outbox for quick, low-risk mutations ----------
const OUTBOX_KEY = "healthos-outbox";
const QUEUEABLE = ["/water", "/habits/"];

interface OutboxItem {
  path: string;
  method: string;
  body: unknown;
  queuedAt: string;
}

function readOutbox(): OutboxItem[] {
  try {
    return JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]");
  } catch {
    return [];
  }
}

function writeOutbox(items: OutboxItem[]) {
  localStorage.setItem(OUTBOX_KEY, JSON.stringify(items.slice(-100)));
}

export function outboxSize(): number {
  return readOutbox().length;
}

export async function flushOutbox(): Promise<void> {
  const items = readOutbox();
  if (!items.length || !navigator.onLine) return;
  const remaining: OutboxItem[] = [];
  for (const item of items) {
    try {
      const res = await fetch(BASE + item.path, {
        method: item.method,
        headers: { "Content-Type": "application/json" },
        body: item.body === undefined ? undefined : JSON.stringify(item.body),
      });
      if (res.status === 401) {
        remaining.push(item);
        break; // not logged in; keep queue for later
      }
      // 2xx/4xx: drop (deterministic — server rejected or accepted)
    } catch {
      remaining.push(item); // still offline
    }
  }
  writeOutbox(remaining);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  if (method !== "GET" && typeof navigator !== "undefined" && !navigator.onLine) {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    if (QUEUEABLE.some((p) => path.startsWith(p))) {
      const items = readOutbox();
      items.push({ path, method, body, queuedAt: new Date().toISOString() });
      writeOutbox(items);
      return { queued: true } as T;
    }
    throw new ApiError(0, "You are offline. This action needs a connection.");
  }
  let res: Response;
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: isFormData
        ? { ...(init?.headers || {}) } // browser sets multipart boundary
        : { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Network error. Check your connection.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | undefined>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
};

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
const del = (path: string) => request<void>(path, { method: "DELETE" });

// ---------- typed API ----------

export const api = {
  // auth / user
  signup: (b: { email: string; password: string; name: string }) => post<User>("/auth/signup", b),
  login: (b: { email: string; password: string }) => post<User>("/auth/login", b),
  logout: () => post<void>("/auth/logout", {}),
  me: () => request<User>("/users/me"),
  updateMe: (b: Partial<Pick<User, "name" | "timezone" | "units">>) => patch<User>("/users/me", b),
  profile: () => request<Profile>("/users/me/profile"),
  updateProfile: (b: Partial<Profile>) => put<Profile>("/users/me/profile", b),
  preferences: () => request<{ data: Record<string, unknown> }>("/users/me/preferences"),
  updatePreferences: (data: Record<string, unknown>) => put("/users/me/preferences", { data }),
  memories: () =>
    request<{ id: string; type: string; key: string; value: { value?: unknown }; source: string; confidence: number }[]>(
      "/users/me/memories"
    ),
  deleteMemory: (id: string) => del(`/users/me/memories/${id}`),

  // goals / targets
  goals: (status?: string) => request<Goal[]>(`/goals${qs({ status })}`),
  createGoal: (b: Partial<Goal> & { title: string }) => post<Goal>("/goals", b),
  updateGoal: (id: string, b: Partial<Goal>) => patch<Goal>(`/goals/${id}`, b),
  deleteGoal: (id: string) => del(`/goals/${id}`),
  goalProgress: (id: string) =>
    request<{ progress: number | null; current: number | null }>(`/goals/${id}/progress`),
  targets: () => request<Target[]>("/targets"),
  createTarget: (b: { key: string; value: number; unit: string; period?: string; mode?: string }) =>
    post<Target>("/targets", b),
  deleteTarget: (id: string) => del(`/targets/${id}`),

  // nutrition
  searchFoods: (q: string, limit = 20) => request<Food[]>(`/foods/search${qs({ q, limit })}`),
  createFood: (b: Partial<Food> & { name: string; calories: number }) => post<Food>("/foods", b),
  logFood: (b: {
    date?: string;
    meal_type: string;
    note?: string;
    items: {
      food_id?: string; name: string; quantity: number; unit: string;
      calories?: number; protein?: number; carbs?: number; fat?: number; fiber?: number;
      estimated?: boolean; confidence?: number; lower_kcal?: number; upper_kcal?: number;
    }[];
  }) => post<FoodLog>("/food-logs", b),
  foodLogs: (day?: string) => request<FoodLog[]>(`/food-logs${qs({ day })}`),
  deleteFoodLog: (id: string) => del(`/food-logs/${id}`),
  dailyNutrition: (day?: string) => request<NutritionDay>(`/nutrition/daily${qs({ day })}`),

  // recipes
  recipes: (q = "") => request<Recipe[]>(`/recipes${qs({ q })}`),
  createRecipe: (b: unknown) => post<Recipe>("/recipes", b),
  deleteRecipe: (id: string) => del(`/recipes/${id}`),
  mealPlans: (start: string, end: string) =>
    request<{ id: string; date: string; meal_type: string; recipe_id: string | null; name: string; servings: number; notes: string | null }[]>(
      `/meal-plans${qs({ start, end })}`),
  createMealPlan: (b: { date: string; meal_type: string; recipe_id?: string; name: string; servings?: number }) =>
    post("/meal-plans", b),
  deleteMealPlan: (id: string) => del(`/meal-plans/${id}`),
  groceryList: (start: string, end: string) =>
    request<{ items: { name: string; quantity: number; unit: string }[] }>(`/grocery-list${qs({ start, end })}`),

  // fitness
  exercises: (q = "") => request<import("./types").Exercise[]>(`/exercises${qs({ q })}`),
  logWorkout: (b: {
    date?: string;
    title: string;
    duration_min?: number;
    exercises: { name: string; sets: object[] }[];
    notes?: string;
  }) => post<Workout>("/workout-sessions", b),
  workouts: (limit = 30) => request<Workout[]>(`/workout-sessions${qs({ limit })}`),
  deleteWorkout: (id: string) => del(`/workout-sessions/${id}`),
  logActivity: (b: Record<string, unknown>) => post("/activities", b),
  workoutPlans: () => request<import("./types").WorkoutPlan[]>("/workout-plans"),
  createWorkoutPlan: (b: { name: string; days: unknown[]; description?: string }) =>
    post<import("./types").WorkoutPlan>("/workout-plans", b),
  deleteWorkoutPlan: (id: string) => del(`/workout-plans/${id}`),

  // photos
  photos: (category?: string) => request<import("./types").PhotoMeta[]>(`/photos${qs({ category })}`),
  uploadPhoto: (file: File, category: string, notes?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<import("./types").PhotoMeta>(`/photos${qs({ category, notes })}`, {
      method: "POST", body: fd, headers: {},
    });
  },
  deletePhoto: (id: string) => del(`/photos/${id}`),
  analyzePhoto: (id: string) =>
    post<{ ok: boolean; items: { name: string; quantity: number; unit: string; calories_est: number; protein_est: number; confidence: number }[]; message?: string }>(
      `/photos/${id}/analyze`, {}),
  photoUrl: (id: string) => `/api/v1/photos/${id}/file`,

  // notifications / privacy
  notifications: () =>
    request<{ notifications: { kind: string; priority: string; title: string; reason: string; href: string }[]; count: number; quiet_hours_active: boolean }>(
      "/notifications"),
  exportData: () => request<Record<string, unknown>>("/users/me/export"),
  deleteAccount: () => del("/users/me"),

  // health
  logWater: (amount_ml: number) => post<{ id: string }>("/water", { amount_ml }),
  waterToday: () => request<{ total_ml: number; logs: { id: string; amount_ml: number }[] }>("/water"),
  deleteWater: (id: string) => del(`/water/${id}`),
  logSleep: (b: { sleep_start: string; sleep_end: string; quality?: number }) => post<SleepLog>("/sleep", b),
  sleepLogs: (days = 14) => request<SleepLog[]>(`/sleep${qs({ days })}`),
  recordMeasurement: (b: { type: string; value: number; unit?: string; date?: string }) =>
    post<Measurement>("/measurements", b),
  measurements: (type?: string, days = 90) =>
    request<Measurement[]>(`/measurements${qs({ type, days })}`),
  deleteMeasurement: (id: string) => del(`/measurements/${id}`),
  weightTrend: (days = 30) => request<WeightTrend>(`/measurements/trend/weight${qs({ days })}`),

  // habits
  habits: () => request<Habit[]>("/habits"),
  createHabit: (b: { name: string; frequency?: string; target?: number; unit?: string }) =>
    post<Habit>("/habits", b),
  deleteHabit: (id: string) => del(`/habits/${id}`),
  logHabit: (id: string, b: { status: string; date?: string }) =>
    post(`/habits/${id}/logs`, b),
  habitsProgress: (days = 7) => request<HabitProgress[]>(`/habits-progress${qs({ days })}`),

  // schedule
  schedule: (start: string, end?: string) => request<ScheduleEvent[]>(`/schedule${qs({ start, end })}`),
  createEvent: (b: Record<string, unknown>) => post("/schedule/events", b),
  updateEvent: (id: string, b: Record<string, unknown>) => patch(`/schedule/events/${id}`, b),
  deleteEvent: (id: string) => del(`/schedule/events/${id}`),

  // analytics
  dailySummary: (day?: string) => request<DailySummary>(`/analytics/daily${qs({ day })}`),
  rangeSummary: (days: number) => request<RangeSummary>(`/analytics/range${qs({ days })}`),

  // ai
  chat: (message: string, conversation_id?: string) =>
    post<{ conversation_id: string; reply: string; actions: ChatAction[] }>("/ai/chat", {
      message,
      conversation_id,
    }),
  conversations: () => request<Conversation[]>("/ai/conversations"),
  conversationMessages: (id: string) =>
    request<{ id: string; role: string; content: string }[]>(`/ai/conversations/${id}/messages`),
  recommendations: () =>
    request<{ id: string; title: string; reason: string | null; priority: string; confidence: number; actions: unknown[] }[]>(
      "/ai/recommendations"),
  updateRecommendation: (id: string, status: string) => patch(`/ai/recommendations/${id}`, { status }),
  parseOnboarding: (text: string) => post<OnboardingProposal>("/ai/onboarding/parse", { text }),
  commitOnboarding: (b: unknown) => post("/ai/onboarding/commit", b),
  aiProviders: () => request<{ providers: import("./types").AIProviderInfo[] }>("/ai/providers"),
  aiSettings: () => request<{ ai: import("./types").AISettings }>("/ai/settings"),
  updateAiSettings: (b: { provider?: string; model?: string; base_url?: string; api_key?: string; mode?: string }) =>
    put<{ ai: import("./types").AISettings }>("/ai/settings", b),
  testAiProvider: (b: { provider?: string; model?: string; base_url?: string; api_key?: string }) =>
    post<{ ok: boolean; latency_ms?: number; reply?: string; error?: string }>("/ai/test", b),
  aiModels: (providerId: string, baseUrl?: string) =>
    request<{ models: string[]; detected: boolean; source: string }>(
      `/ai/providers/${providerId}/models${qs({ base_url: baseUrl })}`),
};
