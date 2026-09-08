"""Idempotent seed of global (user_id=NULL) foods and exercises.

Nutrients are per 100 g/ml unless serving_unit says otherwise. Generic staples only —
never anything user-specific.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Exercise, Food

# name, serving_size, serving_unit, kcal, protein, carbs, fat, fiber
FOODS: list[tuple[str, float, str, float, float, float, float, float]] = [
    ("White rice (cooked)", 100, "g", 130, 2.7, 28, 0.3, 0.4),
    ("Brown rice (cooked)", 100, "g", 112, 2.6, 23, 0.9, 1.8),
    ("Dal (cooked lentils)", 100, "g", 116, 9, 20, 0.4, 7.9),
    ("Egg", 1, "piece", 78, 6.3, 0.6, 5.3, 0),
    ("Chicken breast (cooked)", 100, "g", 165, 31, 0, 3.6, 0),
    ("Chicken thigh (cooked)", 100, "g", 209, 26, 0, 10.9, 0),
    ("Salmon (cooked)", 100, "g", 208, 22, 0, 12, 0),
    ("Paneer", 100, "g", 265, 18, 3.6, 20, 0),
    ("Tofu", 100, "g", 76, 8, 1.9, 4.8, 0.3),
    ("Greek yogurt (plain)", 100, "g", 59, 10, 3.6, 0.4, 0),
    ("Milk (whole)", 100, "ml", 61, 3.2, 4.8, 3.3, 0),
    ("Oats (dry)", 100, "g", 389, 16.9, 66, 6.9, 10.6),
    ("Whole wheat bread", 1, "piece", 81, 4, 13.8, 1.1, 1.9),
    ("White bread (toast)", 1, "piece", 79, 2.7, 15, 1, 0.7),
    ("Banana", 1, "piece", 105, 1.3, 27, 0.4, 3.1),
    ("Apple", 1, "piece", 95, 0.5, 25, 0.3, 4.4),
    ("Potato (boiled)", 100, "g", 87, 1.9, 20, 0.1, 1.8),
    ("Sweet potato (baked)", 100, "g", 90, 2, 21, 0.1, 3.3),
    ("Mixed vegetables (cooked)", 100, "g", 65, 2.9, 13, 0.2, 4),
    ("Spinach (cooked)", 100, "g", 23, 3, 3.8, 0.3, 2.4),
    ("Olive oil", 10, "ml", 88, 0, 0, 10, 0),
    ("Ghee", 10, "g", 90, 0, 0, 10, 0),
    ("Peanut butter", 32, "g", 188, 8, 6.3, 16, 2.6),
    ("Almonds", 28, "g", 164, 6, 6.1, 14, 3.5),
    ("Whey protein powder", 30, "g", 120, 24, 3, 1.5, 1),
    ("Chickpeas (cooked)", 100, "g", 164, 8.9, 27, 2.6, 7.6),
    ("Quinoa (cooked)", 100, "g", 120, 4.4, 21, 1.9, 2.8),
    ("Roti / chapati", 1, "piece", 104, 3.1, 18, 2.8, 3.9),
    ("Curd / yogurt (plain)", 100, "g", 61, 3.5, 4.7, 3.3, 0),
    ("Avocado", 100, "g", 160, 2, 8.5, 14.7, 6.7),
    ("Orange", 1, "piece", 62, 1.2, 15.4, 0.2, 3.1),
    ("Pasta (cooked)", 100, "g", 158, 5.8, 31, 0.9, 1.8),
    ("Ground beef (cooked, 90% lean)", 100, "g", 217, 26, 0, 11.8, 0),
    ("Cottage cheese", 100, "g", 98, 11, 3.4, 4.3, 0),
    ("Honey", 21, "g", 64, 0, 17.3, 0, 0),
    ("Black coffee", 240, "ml", 2, 0.3, 0, 0, 0),
]

# name, muscle_groups, movement_pattern, equipment, difficulty
EXERCISES: list[tuple[str, list[str], str, str, str]] = [
    ("Barbell Back Squat", ["quads", "glutes"], "squat", "barbell", "intermediate"),
    ("Barbell Bench Press", ["chest", "triceps"], "push", "barbell", "intermediate"),
    ("Deadlift", ["back", "hamstrings", "glutes"], "hinge", "barbell", "intermediate"),
    ("Overhead Press", ["shoulders", "triceps"], "push", "barbell", "intermediate"),
    ("Barbell Row", ["back", "biceps"], "pull", "barbell", "intermediate"),
    ("Pull-Up", ["back", "biceps"], "pull", "bodyweight", "intermediate"),
    ("Push-Up", ["chest", "triceps"], "push", "bodyweight", "beginner"),
    ("Dumbbell Curl", ["biceps"], "pull", "dumbbell", "beginner"),
    ("Tricep Pushdown", ["triceps"], "push", "cable", "beginner"),
    ("Lat Pulldown", ["back", "biceps"], "pull", "cable", "beginner"),
    ("Leg Press", ["quads", "glutes"], "squat", "machine", "beginner"),
    ("Romanian Deadlift", ["hamstrings", "glutes"], "hinge", "barbell", "intermediate"),
    ("Dumbbell Shoulder Press", ["shoulders"], "push", "dumbbell", "beginner"),
    ("Incline Dumbbell Press", ["chest"], "push", "dumbbell", "intermediate"),
    ("Cable Fly", ["chest"], "push", "cable", "beginner"),
    ("Face Pull", ["rear delts", "upper back"], "pull", "cable", "beginner"),
    ("Hamstring Curl", ["hamstrings"], "pull", "machine", "beginner"),
    ("Calf Raise", ["calves"], "push", "machine", "beginner"),
    ("Plank", ["core"], "hold", "bodyweight", "beginner"),
    ("Hanging Leg Raise", ["core"], "pull", "bodyweight", "intermediate"),
    ("Walking", ["full body"], "cardio", "none", "beginner"),
    ("Running", ["full body"], "cardio", "none", "beginner"),
    ("Cycling", ["legs"], "cardio", "bike", "beginner"),
    ("Freestyle Swimming", ["full body"], "cardio", "pool", "intermediate"),
    ("Stretching / Mobility", ["full body"], "mobility", "none", "beginner"),
]


async def seed(db: AsyncSession) -> None:
    existing = await db.execute(select(Food).where(Food.user_id.is_(None)).limit(1))
    if existing.scalar_one_or_none() is None:
        for name, size, unit, cal, pro, carb, fat, fiber in FOODS:
            db.add(Food(user_id=None, name=name, serving_size=size, serving_unit=unit,
                        calories=cal, protein=pro, carbs=carb, fat=fat, fiber=fiber, source="seed"))
    existing_ex = await db.execute(select(Exercise).limit(1))
    if existing_ex.scalar_one_or_none() is None:
        for name, muscles, pattern, equipment, difficulty in EXERCISES:
            db.add(Exercise(name=name, muscle_groups=muscles, movement_pattern=pattern,
                            equipment=equipment, difficulty=difficulty))
    await db.commit()
