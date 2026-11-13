from collections import defaultdict
from datetime import timedelta
from math import sqrt

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from database.db import db
from database.models import DemandPlan


DIMENSIONS = {
    "role": "role_id",
    "project": "project_id",
    "skill": "skill_id",
}


def forecast_demand(dimension="role", horizon=8, session=None, seed=20261022):
    """Backtest a moving average and random forest, then forecast future weekly demand."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension must be one of {', '.join(DIMENSIONS)}")
    if horizon <= 0:
        raise ValueError("horizon must be a positive number of weeks")
    session = session or db.session
    records = (
        session.query(DemandPlan)
        .filter(DemandPlan.demand_type == "planned")
        .order_by(DemandPlan.period_start)
        .all()
    )
    if not records:
        return {
            "dimension": dimension,
            "metrics": {},
            "series": [],
            "note": "No synthetic demand is available for forecasting.",
        }

    dimension_field = DIMENSIONS[dimension]
    demand = defaultdict(float)
    identities = {}
    dates = sorted({record.period_start for record in records})
    first_date, last_date = dates[0], dates[-1]
    week_dates = []
    current = first_date
    while current <= last_date:
        week_dates.append(current)
        current += timedelta(days=7)

    for record in records:
        key = getattr(record, dimension_field)
        demand[(key, record.period_start)] += record.required_hours
        identities[key] = record
    keys = sorted(identities)
    group_index = {key: index for index, key in enumerate(keys)}
    panel = []
    for key in keys:
        record = identities[key]
        for week_index, week_date in enumerate(week_dates):
            week_number = week_date.isocalendar().week
            panel.append(
                {
                    "key": key,
                    "date": week_date,
                    "week_index": week_index,
                    "target": demand[(key, week_date)],
                    "group_index": group_index[key],
                    "role_index": int(record.role_id.rsplit("-", 1)[-1]),
                    "skill_index": int(record.skill_id.rsplit("-", 1)[-1]),
                    "project_index": int(record.project_id.rsplit("-", 1)[-1]),
                    "month": week_date.month,
                    "week_sin": float(np.sin(2 * np.pi * week_number / 52)),
                    "week_cos": float(np.cos(2 * np.pi * week_number / 52)),
                }
            )
    frame = pd.DataFrame(panel)
    unique_dates = sorted(frame["date"].unique())
    split = max(1, min(len(unique_dates) - 1, int(len(unique_dates) * 0.8)))
    cutoff_index = unique_dates[split] if split < len(unique_dates) else unique_dates[-1]
    train = frame[frame["date"] < cutoff_index]
    test = frame[frame["date"] >= cutoff_index]
    if train.empty or test.empty:
        raise ValueError("At least two weekly periods are required for time-based evaluation.")

    feature_columns = [
        "week_index",
        "group_index",
        "role_index",
        "skill_index",
        "project_index",
        "month",
        "week_sin",
        "week_cos",
    ]
    model = RandomForestRegressor(
        n_estimators=40,
        min_samples_leaf=2,
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(train[feature_columns], train["target"])
    test_rows = test.sort_values(["date", "key"])
    test_predictions = np.maximum(0, model.predict(test_rows[feature_columns]))

    grouped = frame.groupby("key", sort=True)
    history_by_key = {
        key: list(group.sort_values("date")["target"].iloc[:split].astype(float))
        for key, group in grouped
    }
    moving_predictions = []
    for row in test_rows.itertuples():
        history = history_by_key[row.key]
        moving_predictions.append(float(np.mean(history[-4:])) if history else 0.0)
        history.append(float(row.target))

    y_test = test_rows["target"].to_numpy(dtype=float)

    def metric_set(predictions):
        errors = y_test - np.asarray(predictions, dtype=float)
        absolute_error = np.abs(errors)
        denominator = float(np.abs(y_test).sum())
        wape = float(absolute_error.sum() / denominator * 100) if denominator else 0.0
        return {
            "mae": round(float(absolute_error.mean()), 3),
            "rmse": round(float(sqrt(np.square(errors).mean())), 3),
            "wape_pct": round(wape, 3),
        }

    baseline_metrics = metric_set(moving_predictions)
    random_forest_metrics = metric_set(test_predictions)
    metrics = {
        "test_period_start": cutoff_index.isoformat(),
        "baseline_moving_average": baseline_metrics,
        "random_forest": random_forest_metrics,
        "lower_mae_model": (
            "moving_average"
            if baseline_metrics["mae"] < random_forest_metrics["mae"]
            else "random_forest"
            if random_forest_metrics["mae"] < baseline_metrics["mae"]
            else "tie"
        ),
        "wape_zero_demand_rule": "Returns 0 when total test demand and error are both zero.",
    }

    latest_week_index = int(frame["week_index"].max())
    future_rows = []
    future_features = []
    for key in keys:
        history = list(
            frame[frame["key"] == key]
            .sort_values("date")["target"]
            .astype(float)
        )
        identity = identities[key]
        for offset in range(1, horizon + 1):
            week_date = last_date + timedelta(days=7 * offset)
            week_number = week_date.isocalendar().week
            features = pd.DataFrame(
                [
                    {
                        "week_index": latest_week_index + offset,
                        "group_index": group_index[key],
                        "role_index": int(identity.role_id.rsplit("-", 1)[-1]),
                        "skill_index": int(identity.skill_id.rsplit("-", 1)[-1]),
                        "project_index": int(identity.project_id.rsplit("-", 1)[-1]),
                        "month": week_date.month,
                        "week_sin": float(np.sin(2 * np.pi * week_number / 52)),
                        "week_cos": float(np.cos(2 * np.pi * week_number / 52)),
                    }
                ]
            )
            future_features.append(features.iloc[0].to_dict())
            moving_average = float(np.mean(history[-4:])) if history else 0.0
            future_rows.append(
                {
                    "dimension": dimension,
                    "key": key,
                    "period_start": week_date.isoformat(),
                    "synthetic_historical_demand": None,
                    "actual_observed_demand": None,
                    "moving_average_forecast": round(moving_average, 2),
                    "record_type": "predicted_future",
                }
            )
            history.append(moving_average)

    future_predictions = np.maximum(
        0, model.predict(pd.DataFrame(future_features)[feature_columns])
    )
    for row, forest in zip(future_rows, future_predictions):
        row["random_forest_forecast"] = round(float(forest), 2)

    history_rows = [
        {
            "dimension": dimension,
            "key": row.key,
            "period_start": row.date.isoformat(),
            "synthetic_historical_demand": round(float(row.target), 2),
            "actual_observed_demand": None,
            "moving_average_forecast": None,
            "random_forest_forecast": None,
            "record_type": "synthetic_historical",
        }
        for row in frame.itertuples()
    ]
    backtest_rows = []
    for row, baseline, forest in zip(test_rows.itertuples(), moving_predictions, test_predictions):
        backtest_rows.append(
            {
                "dimension": dimension,
                "key": row.key,
                "period_start": row.date.isoformat(),
                "synthetic_historical_demand": round(float(row.target), 2),
                "actual_observed_demand": None,
                "moving_average_forecast": round(float(baseline), 2),
                "random_forest_forecast": round(float(forest), 2),
                "record_type": "backtest",
            }
        )
    return {
        "dimension": dimension,
        "metrics": metrics,
        "series": history_rows + backtest_rows + future_rows,
        "note": (
            "Historical targets are synthetic planned demand, not actual observed demand. "
            "The model uses a chronological holdout; forward forecasts assume recent "
            "patterns persist and do not incorporate future project changes."
        ),
    }
