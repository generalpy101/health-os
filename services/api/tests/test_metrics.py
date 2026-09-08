from datetime import date, timedelta

from app.utils import metrics


def test_scale_nutrients_grams():
    food = {"serving_size": 100, "calories": 130, "protein": 2.7, "carbs": 28, "fat": 0.3, "fiber": 0.4}
    out = metrics.scale_nutrients(food, 200, "g")
    assert out["calories"] == 260
    assert out["protein"] == 5.4


def test_scale_nutrients_pieces():
    food = {"serving_size": 1, "calories": 78, "protein": 6.3, "carbs": 0.6, "fat": 5.3, "fiber": 0}
    out = metrics.scale_nutrients(food, 2, "piece")
    assert out["calories"] == 156
    assert out["protein"] == 12.6


def test_sum_items_rounds():
    items = [{"calories": 100.05, "protein": 5.05}, {"calories": 200.05, "protein": 10.05}]
    out = metrics.sum_items(items)
    assert out["calories"] == 300.1
    assert out["protein"] == 15.1


def test_recipe_nutrition_per_serving():
    out = metrics.recipe_nutrition_per_serving([{"calories": 400, "protein": 20}], 2)
    assert out["per_serving"] == {"calories": 200.0, "protein": 10.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
    assert out["total"]["calories"] == 400


def test_bmi():
    assert metrics.bmi(70, 175) == 22.9
    assert metrics.bmi(0, 175) is None


def test_bmr_and_tdee():
    bmr = metrics.bmr_mifflin(80, 180, 30, "male")
    assert bmr == 1780
    assert metrics.tdee(bmr, "moderate") == round(1780 * 1.55)


def test_moving_average_window():
    pts = [(date(2024, 1, 1) + timedelta(days=i), float(i)) for i in range(10)]
    ma = metrics.moving_average(pts, window=7)
    assert len(ma) == 10
    assert ma[0][1] == 0.0
    assert ma[-1][1] == round(sum(range(3, 10)) / 7, 2)


def test_linear_trend_direction():
    up = [(date(2024, 1, 1) + timedelta(days=i), 80.0 + i) for i in range(10)]
    assert metrics.linear_trend(up) == 1.0
    assert metrics.linear_trend([(date(2024, 1, 1), 80.0)]) is None


def test_workout_volume():
    exs = [{"sets": [{"weight": 60, "reps": 10}, {"weight": 60, "reps": 8}]},
           {"sets": [{"weight": 100, "reps": 5}]}]
    assert metrics.workout_volume(exs) == 60 * 10 + 60 * 8 + 100 * 5


def test_goal_progress_down_and_up():
    assert metrics.goal_progress("weight_loss", 82, 74, 78) == 0.5
    assert metrics.goal_progress("weight_gain", 60, 70, 65) == 0.5
    assert metrics.goal_progress("weight_loss", 82, 74, 90) == 0.0
    assert metrics.goal_progress("weight_loss", 82, 74, 74) == 1.0


def test_adherence_modes():
    assert metrics.adherence(140, 140, "minimum") == 1.0
    assert metrics.adherence(70, 140, "minimum") == 0.5
    assert metrics.adherence(2800, 2000, "maximum") < 1.0
