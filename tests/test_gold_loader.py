"""Gold business rules and real Pandas/SQLAlchemy persistence on SQLite.

SQLite tests exercise transactions and reruns without requiring Azure credentials.
The optional SQL Server smoke test uses the deployed DDL and rolls back its probe.
"""

from datetime import date, timedelta
import os
import importlib
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, text

from azure_functions import gold_loader as gold


@pytest.fixture
def maps():
    return {
        "date": {day.date(): int(day.strftime("%Y%m%d"))
                 for day in pd.date_range("2024-12-29", "2025-12-31")},
        "resident": {resident: i + 1 for i, (resident, _) in enumerate(gold.RESIDENTS)},
        "staff": {staff: i + 1 for i, (staff, _, _) in enumerate(gold.STAFF)},
        "support_worker_ids": {staff for staff, _, support in gold.STAFF if support},
        "log_type": {pair: i + 1 for i, pair in enumerate(gold.CONTROLLED_LOG_TYPES)},
    }


def silver_frames(week=date(2025, 1, 6), source="week.csv", accepted=3):
    stamp = pd.Timestamp(week) + pd.Timedelta(hours=10)
    event = {
        "log_event_key": 1, "resident_id": "R01", "category": "Health Recordings",
        "item": "Mood", "title": "Mood - Good", "description_clean": None,
        "log_datetime": stamp, "logged_by": "Staff 01", "bookmark": True,
        "log_date": week, "shift_type": "Day", "week_start_date": week,
        "source_file": source,
    }
    frames = {
        "log_event": pd.DataFrame([event]),
        "activity": pd.DataFrame(columns=[
            "log_event_key", "resident_id", "activity_type", "is_housework",
            "staff_involved", "log_datetime", "log_date", "logged_by", "source_file",
        ]),
        "appointment": pd.DataFrame(columns=[
            "log_event_key", "resident_id", "appointment_type", "appointment_status",
            "scheduled_datetime", "scheduled_end_datetime", "supported_by_staff",
            "completed", "log_datetime", "log_date", "logged_by", "source_file",
        ]),
        "communication": pd.DataFrame(columns=[
            "log_event_key", "resident_id", "communication_label", "communication_score",
            "log_datetime", "log_date", "shift_type", "logged_by", "source_file",
        ]),
        "incident": pd.DataFrame(columns=[
            "log_event_key", "resident_id", "incident_type", "incident_detail",
            "log_datetime", "log_date", "shift_type", "logged_by", "witnessed_by",
            "description_clean", "bookmark", "source_file",
        ]),
        "medication": pd.DataFrame([
            {**event, "log_event_key": 10 + i, "medication_round": "PRN" if i == 0 else "Morning",
             "medication_status": "Accepted"}
            for i in range(accepted)
        ], columns=["log_event_key", "resident_id", "medication_round", "medication_status",
                    "log_datetime", "log_date", "week_start_date", "logged_by", "source_file"]),
        "mood": pd.DataFrame([{**event, "mood_label": "Good", "mood_score": 4}]),
        "staff_shift": pd.DataFrame([{
            "staff_name": "Staff 01", "shift_date": week, "shift_type": "Day",
            "first_log_datetime": stamp, "last_log_datetime": stamp,
            "log_count": 1, "source_file": source,
        }]),
    }
    return frames


@pytest.fixture
def engine(tmp_path):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def attach_schemas(dbapi, _):
        dbapi.execute("ATTACH DATABASE ? AS gold", (str(tmp_path / "gold.db"),))
        dbapi.execute("ATTACH DATABASE ? AS silver", (str(tmp_path / "silver.db"),))

    with engine.begin() as connection:
        connection.execute(text("""CREATE TABLE gold.dim_date (
            date_key INTEGER PRIMARY KEY, full_date DATE UNIQUE NOT NULL,
            day_name TEXT, day_of_week_number INTEGER, is_weekend BOOLEAN,
            week_start_date DATE, week_end_date DATE, iso_week_number INTEGER,
            reporting_week_number INTEGER, month_number INTEGER, month_name TEXT,
            quarter_number INTEGER, calendar_year INTEGER)"""))
        connection.execute(text("""CREATE TABLE gold.dim_resident (
            resident_key INTEGER PRIMARY KEY AUTOINCREMENT,
            resident_id TEXT UNIQUE NOT NULL, resident_name TEXT)"""))
        connection.execute(text("""CREATE TABLE gold.dim_staff (
            staff_key INTEGER PRIMARY KEY AUTOINCREMENT, staff_id TEXT UNIQUE NOT NULL,
            staff_role TEXT, is_support_worker BOOLEAN)"""))
        connection.execute(text("""CREATE TABLE gold.dim_log_type (
            log_type_key INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, item TEXT,
            log_type_name TEXT, UNIQUE(category, item))"""))
        # SQLite accepts the same columns; SQL Server-specific constraints are
        # covered by the optional smoke test against the real DDL.
        for table, columns in gold.FACT_COLUMNS.items():
            key = "medication_key" if table == "fact_medication" else "row_key"
            definitions = [f"{key} INTEGER PRIMARY KEY AUTOINCREMENT"]
            for column in columns:
                numeric = column.endswith(("_key", "_count"))
                definitions.append(f"{column} {'INTEGER' if numeric else 'NUMERIC'}")
            if table == "fact_medication":
                definitions.append("UNIQUE(source_file, week_start_date_key, resident_key)")
                definitions.append("CHECK(accepted_dose_count + refused_dose_count = total_dose_count)")
            connection.execute(text(f"CREATE TABLE gold.{table} ({', '.join(definitions)})"))
    yield engine
    engine.dispose()


def install_silver(engine, frames):
    with engine.begin() as connection:
        for table, frame in frames.items():
            frame.to_sql(table, connection, schema="silver", if_exists="replace", index=False)


def medication_history(engine):
    with engine.connect() as connection:
        return pd.read_sql(text("SELECT * FROM gold.fact_medication ORDER BY week_start_date_key"), connection)


def test_daily_coverage_and_review_rules(maps):
    frames = silver_frames()
    frames["mood"] = pd.DataFrame([
        {"resident_id": "R01", "log_date": date(2025, 1, 6), "mood_score": score}
        for score in [1, 4, 5]
    ])
    mood = gold.build_mood_frame(frames["mood"], maps, "week.csv", date(2025, 1, 6))
    assert len(mood) == 49
    first = mood.iloc[0]
    assert first["mood_log_count"] == 3
    assert first["average_mood_score"] == 3.33
    assert first["minimum_mood_score"] == 1
    assert first["requires_review"]
    assert mood.iloc[1]["missing_log_count"] == 3
    assert pd.isna(mood.iloc[1]["average_mood_score"])
    assert not mood.iloc[1]["requires_review"]  # Preserve the original mood rule.
    communication = gold.build_communication_frame(
        frames["communication"], maps, "week.csv", date(2025, 1, 6)
    )
    assert len(communication) == 49
    assert communication["requires_review"].all()
    assert communication["missing_log_count"].eq(3).all()


def test_communication_counts_both_shifts(maps):
    frame = pd.DataFrame([
        {"resident_id": "R01", "log_date": date(2025, 1, 6),
         "communication_score": score, "shift_type": shift}
        for score, shift in [(1, "Day"), (2, "Night"), (4, "Day")]
    ])
    first = gold.build_communication_frame(frame, maps, "week.csv", date(2025, 1, 6)).iloc[0]
    assert (first["day_log_count"], first["night_log_count"], first["total_log_count"]) == (2, 1, 3)
    assert first["average_communication"] == 2.33
    assert first["requires_review"]


def test_unknown_dimension_value_fails(maps):
    frames = silver_frames()
    frames["log_event"]["logged_by"] = "Unknown"
    with pytest.raises(ValueError, match="staff_key"):
        gold.build_log_count_frame(frames["log_event"], maps, "week.csv")


def test_appointments_overlap_but_touching_times_do_not(maps):
    rows = []
    for i, (start, end) in enumerate([("10:00", "11:00"), ("10:30", "11:30"), ("11:30", "12:00")]):
        rows.append({
            "log_event_key": i + 1, "resident_id": "R01", "appointment_type": "GP",
            "appointment_status": "Staff Required", "supported_by_staff": True,
            "scheduled_datetime": pd.Timestamp(f"2025-01-06 {start}"),
            "scheduled_end_datetime": pd.Timestamp(f"2025-01-06 {end}"),
            "completed": False, "log_date": date(2025, 1, 6),
        })
    rows.append({**rows[0], "log_event_key": 4, "appointment_status": "Completed with Staff",
                 "scheduled_datetime": pd.NaT, "scheduled_end_datetime": pd.NaT, "completed": True})
    frame = gold.build_appointment_frame(pd.DataFrame(rows), maps, "week.csv")
    assert frame["has_conflict"].tolist() == [True, True, False, False]
    assert frame["completed"].tolist() == [False, False, False, True]
    rows[0]["scheduled_end_datetime"] = pd.NaT
    with pytest.raises(ValueError, match="no end time"):
        gold.build_appointment_frame(pd.DataFrame(rows), maps, "week.csv")


def test_early_morning_staff_shift_and_manager_exclusion(maps):
    frames = silver_frames()
    frames["log_event"]["log_datetime"] = pd.Timestamp("2025-01-07 02:00")
    frames["log_event"]["shift_type"] = "Night"
    frames["staff_shift"]["shift_type"] = "Night"
    manager = frames["staff_shift"].copy()
    manager["staff_name"] = "Manager 01"
    shifts = pd.concat([frames["staff_shift"], manager])
    frame = gold.build_staff_shift_frame(shifts, frames["log_event"], maps, "week.csv")
    assert len(frame) == 1
    assert frame.iloc[0]["date_key"] == 20250106
    assert frame.iloc[0]["resident_count"] == 1


def test_baseline_requires_four_prior_weeks_and_excludes_current():
    frame = pd.DataFrame([
        {"medication_key": i + 1, "resident_key": 1, "week_start_date_key": 20250101 + i,
         "accepted_dose_count": value, "refused_dose_count": 0}
        for i, value in enumerate([10, 20, 30, 40, 100])
    ])
    actual = gold.calculate_medication_baselines(frame)
    assert not actual.iloc[:4]["has_baseline"].any()
    assert actual.iloc[4]["baseline_median_doses"] == 25
    assert actual.iloc[4]["percentage_of_baseline"] == 400
    frame.loc[:3, "accepted_dose_count"] = 0
    actual = gold.calculate_medication_baselines(frame)
    assert not actual.iloc[-1]["has_baseline"]
    assert pd.isna(actual.iloc[-1]["percentage_of_baseline"])


def test_baseline_uses_only_last_twelve_weeks_and_separates_residents():
    frame = pd.DataFrame([
        {"medication_key": i + 1, "resident_key": 1, "week_start_date_key": i,
         "accepted_dose_count": value, "refused_dose_count": 0}
        for i, value in enumerate([1000] * 6 + [10] * 6 + [30] * 6 + [10])
    ])
    other = frame.copy()
    other["resident_key"] = 2
    other["medication_key"] += 100
    other["accepted_dose_count"] = 99
    actual = gold.calculate_medication_baselines(pd.concat([frame, other]))
    last = actual.loc[actual["resident_key"] == 1].iloc[-1]
    assert last["baseline_median_doses"] == 20
    assert last["percentage_of_baseline"] == 50
    assert last["requires_review"]


def test_full_load_rerun_keeps_counts_and_dimensions(engine):
    install_silver(engine, silver_frames())
    first = gold.load_gold_tables(engine, "week.csv")
    second = gold.load_gold_tables(engine, "week.csv")
    assert first == second
    assert second["gold_rows"]["fact_mood_daily"] == 49
    assert second["gold_rows"]["fact_communication"] == 49
    assert second["gold_rows"]["fact_medication"] == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM gold.fact_mood_daily")).scalar_one() == 49
        assert connection.execute(text("SELECT COUNT(*) FROM gold.dim_resident")).scalar_one() == 7
        assert connection.execute(text("SELECT COUNT(*) FROM gold.fact_flagged_log")).scalar_one() == 1


def test_failed_insert_rolls_back_deleted_and_inserted_rows(engine, monkeypatch):
    install_silver(engine, silver_frames(accepted=3))
    gold.load_gold_tables(engine, "week.csv")
    before = medication_history(engine)
    install_silver(engine, silver_frames(accepted=8))
    real_append = gold.append_frame

    def fail_late(connection, table, frame):
        if table == "fact_flagged_log":
            raise RuntimeError("simulated write failure")
        return real_append(connection, table, frame)

    monkeypatch.setattr(gold, "append_frame", fail_late)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        gold.load_gold_tables(engine, "week.csv")
    pd.testing.assert_frame_equal(medication_history(engine), before)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM gold.fact_mood_daily")).scalar_one() == 49


def test_old_week_reload_and_removal_refresh_later_baselines(engine):
    for i, doses in enumerate([10, 20, 30, 40, 50]):
        frames = silver_frames(date(2025, 1, 6) + timedelta(weeks=i), f"week{i}.csv", doses)
        install_silver(engine, frames)
        gold.load_gold_tables(engine, f"week{i}.csv")
    before = medication_history(engine)
    assert before.iloc[-1]["baseline_median_doses"] == 25
    later_key = before.iloc[-1]["medication_key"]
    install_silver(engine, silver_frames(date(2025, 1, 6), "week0.csv", 100))
    gold.load_gold_tables(engine, "week0.csv")
    updated = medication_history(engine)
    assert updated.iloc[-1]["baseline_median_doses"] == 35
    assert updated.iloc[-1]["percentage_of_baseline"] == 142.86
    assert updated.iloc[-1]["medication_key"] == later_key
    assert updated.iloc[-1]["accepted_dose_count"] == 50
    install_silver(engine, silver_frames(date(2025, 1, 6), "week0.csv", 0))
    gold.load_gold_tables(engine, "week0.csv")
    removed = medication_history(engine)
    assert len(removed) == 4
    assert not removed.iloc[-1]["has_baseline"]
    assert pd.isna(removed.iloc[-1]["baseline_median_doses"])


def test_missing_gold_table_is_not_created(engine):
    with engine.begin() as connection:
        with pytest.raises(ValueError, match="using the SQL DDL"):
            gold.append_frame(connection, "missing_table", pd.DataFrame({"value": [1]}))


def test_engine_uses_microsoft_driver_without_connecting():
    from azure_functions.database import create_sqlalchemy_engine
    engine = create_sqlalchemy_engine("Server=example.invalid;Database=unused")
    assert engine.dialect.name == "mssql"
    assert engine.dialect.driver == "mssqlpython"
    engine.dispose()


def test_detail_fact_mappings_and_staff_filters(maps):
    frames = silver_frames()
    event = frames["log_event"].iloc[0].to_dict()
    frames["activity"] = pd.DataFrame([
        {**event, "activity_type": "  Kitchen  ", "is_housework": True, "staff_involved": True},
        {**event, "log_event_key": 2, "activity_type": "Walk", "is_housework": False, "staff_involved": False},
        {**event, "log_event_key": 3, "activity_type": "Garden", "is_housework": False,
         "staff_involved": True, "logged_by": "Manager 01"},
    ])
    frames["appointment"] = pd.DataFrame([
        {**event, "log_event_key": 4, "appointment_type": "  GP  ",
         "appointment_status": "Completed with Staff"},
        {**event, "log_event_key": 5, "appointment_type": "GP",
         "appointment_status": "Staff Required"},
    ])
    involvement = gold.build_staff_involvement_frame(
        frames["activity"], frames["appointment"], maps, "week.csv"
    )
    assert involvement["involvement_type"].tolist() == ["Cleaning Task", "Appointment Escort"]
    assert involvement["involvement_detail"].tolist() == ["Kitchen", "GP"]
    assert involvement["source_log_event_key"].tolist() == [1, 4]
    incident = pd.DataFrame([{
        **event, "incident_type": "Fall", "incident_detail": None,
        "witnessed_by": "  Staff 02  ", "description_clean": "  Checked  ",
    }])
    result = gold.build_incident_frame(incident, maps, "week.csv").iloc[0]
    assert result["witnessed_by"] == "Staff 02"
    assert result["description_clean"] == "Checked"
    assert result["bookmarked"]
    assert result["source_log_event_key"] == 1
    assert pd.isna(result["incident_detail"])
    events = pd.concat([frames["log_event"], frames["log_event"].assign(bookmark=False)])
    counts = gold.build_log_count_frame(events, maps, "week.csv").iloc[0]
    assert counts["log_count"] == 2
    assert counts["bookmarked_log_count"] == 1
    assert len(gold.build_flagged_log_frame(events, maps, "week.csv")) == 1


def test_loading_missing_earlier_week_repairs_later_baseline(engine):
    for i, doses in enumerate([20, 30, 40, 50], start=1):
        install_silver(engine, silver_frames(date(2025, 1, 6) + timedelta(weeks=i), f"week{i}.csv", doses))
        gold.load_gold_tables(engine, f"week{i}.csv")
    assert not medication_history(engine).iloc[-1]["has_baseline"]
    install_silver(engine, silver_frames(date(2025, 1, 6), "week0.csv", 10))
    gold.load_gold_tables(engine, "week0.csv")
    assert medication_history(engine).iloc[-1]["baseline_median_doses"] == 25


def test_baseline_refresh_failure_rolls_back_whole_load(engine, monkeypatch):
    install_silver(engine, silver_frames(accepted=3))
    gold.load_gold_tables(engine, "week.csv")
    before = medication_history(engine)
    install_silver(engine, silver_frames(accepted=8))
    real_refresh = gold.refresh_medication_baselines

    def fail_after_refresh(connection, from_week_key):
        real_refresh(connection, from_week_key)
        raise RuntimeError("simulated refresh failure")

    monkeypatch.setattr(gold, "refresh_medication_baselines", fail_after_refresh)
    with pytest.raises(RuntimeError, match="simulated refresh failure"):
        gold.load_gold_tables(engine, "week.csv")
    pd.testing.assert_frame_equal(medication_history(engine), before)


@pytest.mark.parametrize("fail", [False, True])
def test_gold_http_route_uses_engine_and_cleans_up(monkeypatch, fail):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "azure_functions"))
    app = importlib.import_module("function_app")
    monkeypatch.setenv("SQL_CONNECTION_STRING", "Server=example.invalid")
    raw_connection, engine = Mock(), Mock()
    monkeypatch.setattr(app.mssql_python, "connect", Mock(return_value=raw_connection))
    monkeypatch.setattr(app, "create_sqlalchemy_engine", Mock(return_value=engine))
    monkeypatch.setattr(app, "get_latest_pipeline_run_key", Mock(return_value=7))
    loader = Mock(side_effect=RuntimeError("load failed")) if fail else Mock(return_value={"status": "Succeeded"})
    monkeypatch.setattr(app, "load_gold_tables", loader)
    request = app.func.HttpRequest(
        method="POST", url="https://example.invalid/load-silver-tables-to-gold",
        body=b'{"source_file": "week.csv"}',
    )
    handler = app.load_silver_tables_to_gold.build().get_user_function()
    response = handler(request)
    assert response.status_code == (500 if fail else 200)
    loader.assert_called_once_with(engine=engine, source_file="week.csv")
    raw_connection.close.assert_called_once()
    engine.dispose.assert_called_once()


@pytest.mark.skipif(not os.getenv("GOLD_TEST_SQL_CONNECTION_STRING"), reason="No SQL Server test database configured")
def test_sql_server_pandas_round_trip():
    """Use a disposable test database with the Gold DDL already applied."""
    from azure_functions.database import create_sqlalchemy_engine
    engine = create_sqlalchemy_engine(os.environ["GOLD_TEST_SQL_CONNECTION_STRING"])
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                gold.seed_dimensions(connection)
                maps = gold.load_dimension_maps(connection)
                frames = gold.build_gold_frames(silver_frames(), maps, "__gold_test__.csv", date(2025, 1, 6))
                gold.delete_previous_gold_load(connection, "__gold_test__.csv")
                for table, frame in frames.items():
                    assert gold.append_frame(connection, table, frame) == len(frame)
                gold.refresh_medication_baselines(connection, 20250106)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
