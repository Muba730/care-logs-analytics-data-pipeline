"""Loads one validated Silver file into the Gold reporting tables."""

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import inspect, text


REPORT_START = date(2024, 12, 30)
REPORT_END = date(2025, 12, 28)
CALENDAR_START = REPORT_START - timedelta(days=1)
CALENDAR_END = date(2025, 12, 31)

EXPECTED_DAILY_LOGS = 3
MEDICATION_BASELINE_MIN_WEEKS = 4
MEDICATION_BASELINE_MAX_WEEKS = 12

BOOKING_STATUSES = {"Staff Required", "No Staff Required"}

RESIDENTS = (
    ("R01", "Resident 01"),
    ("R02", "Resident 02"),
    ("R03", "Resident 03"),
    ("R04", "Resident 04"),
    ("R05", "Resident 05"),
    ("R06", "Resident 06"),
    ("R07", "Resident 07"),
)

STAFF = (
    ("Manager 01", "Manager", False),
    ("Staff 01", "Support Worker", True),
    ("Staff 02", "Support Worker", True),
    ("Staff 03", "Support Worker", True),
    ("Staff 04", "Support Worker", True),
    ("Staff 05", "Support Worker", True),
)

# This is a controlled list, not a DISTINCT list generated automatically from
# Silver. If the application introduces a valid new Category/Item combination,
# add it here deliberately and rerun the file.
CONTROLLED_LOG_TYPES = (
    ("Activities", "Communication"),
    ("Activities", "House Work"),
    ("Activities", "Occupational Therapy"),
    ("Activities", "Resident Activity"),
    ("Food & Drink", "Evening Meal"),
    ("Food & Drink", "Lunch"),
    ("Handover", "Daily"),
    ("Handover", "General"),
    ("Handover", "General Handover"),
    ("Health Recordings", "Mood"),
    ("Health Recordings", "Symptoms"),
    ("Health Visit", "Health Professional"),
    # Verbal aggression, property damage, and thrown medication are
    # recorded as lower-level details beneath Negative Behaviour.
    ("Incident", "Negative Behaviour"),
    ("Incident", "Self-Harm Concern"),
    ("Incident", "Fall"),
    ("Incident", "Assault"),
    ("Incident", "Missing Person"),
    ("Incident", "Other"),
    ("Medication", "Medication Round"),
    ("Personal Care", "Evening Support"),
    ("Personal Care", "Morning Support"),
    ("Presence Check", "Evening Check"),
    ("Sleep", "Night Observation"),
)





FACT_COLUMNS = {
    "agg_log_count_daily": [
        "date_key",
        "resident_key",
        "staff_key",
        "log_type_key",
        "shift_type",
        "log_count",
        "bookmarked_log_count",
        "source_file"
    ],
    "fact_mood_daily": [
        "date_key",
        "resident_key",
        "mood_log_count",
        "expected_log_count",
        "missing_log_count",
        "very_low_count",
        "low_count",
        "okay_count",
        "good_count",
        "very_good_count",
        "average_mood_score",
        "minimum_mood_score",
        "requires_review",
        "source_file"
    ],
    "fact_communication": [
        "date_key",
        "resident_key",
        "day_log_count",
        "night_log_count",
        "total_log_count",
        "expected_log_count",
        "missing_log_count",
        "no_response_count",
        "minimal_count",
        "normal_count",
        "expansive_count",
        "average_communication",
        "requires_review",
        "source_file"
    ],
    "fact_medication": [
        "week_start_date_key",
        "resident_key",
        "total_dose_count",
        "accepted_dose_count",
        "refused_dose_count",
        "prn_dose_count",
        "has_baseline",
        "baseline_median_doses",
        "percentage_of_baseline",
        "requires_review",
        "source_file"
    ],
    "fact_appointment": [
        "appointment_date_key",
        "resident_key",
        "appointment_type",
        "appointment_status",
        "scheduled_start_datetime",
        "scheduled_end_datetime",
        "staff_required",
        "completed",
        "has_conflict",
        "source_log_event_key",
        "source_file"
    ],
    "fact_incident": [
        "date_key",
        "resident_key",
        "staff_key",
        "incident_type",
        "incident_detail",
        "incident_datetime",
        "shift_type",
        "witnessed_by",
        "description_clean",
        "bookmarked",
        "source_log_event_key",
        "source_file"
    ],
    "fact_staff_shift": [
        "date_key",
        "staff_key",
        "shift_type",
        "first_log_datetime",
        "last_log_datetime",
        "log_count",
        "resident_count",
        "source_file"
    ],
    "fact_staff_involvement": [
        "date_key",
        "resident_key",
        "staff_key",
        "involvement_type",
        "involvement_detail",
        "source_log_event_key",
        "source_file"
    ],
    "fact_flagged_log": [
        "date_key",
        "resident_key",
        "staff_key",
        "log_type_key",
        "source_log_event_key",
        "logged_at",
        "shift_type",
        "title",
        "description_clean",
        "source_file"
    ]
}


def clean_text(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None

    text = str(value).strip()
    return text or None


def as_boolean(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def as_database_value(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.to_pydatetime()
    if not isinstance(value, str) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def make_date_key(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, pd.Timestamp):
        value = value.date()
    return int(value.strftime("%Y%m%d"))


def normalise_dates(frame, date_columns=(), datetime_columns=()):
    for column_name in date_columns:
        if column_name in frame.columns:
            frame[column_name] = pd.to_datetime(
                frame[column_name], errors="raise"
            ).dt.date

    for column_name in datetime_columns:
        if column_name in frame.columns:
            frame[column_name] = pd.to_datetime(
                frame[column_name], errors="coerce"
            )

    return frame


def read_frame(connection, query, parameters=None):
    return pd.read_sql(text(query), connection, params=parameters or {})


def append_frame(connection, table_name, frame):
    """Append to an existing DDL-managed table, inside the caller's transaction."""
    if frame.empty:
        return 0
    if not inspect(connection).has_table(table_name, schema="gold"):
        raise ValueError(f"Create gold.{table_name} using the SQL DDL first")
    frame.to_sql(
        name=table_name,
        schema="gold",
        con=connection,
        if_exists="append",
        index=False,
        chunksize=500,
    )
    return len(frame)


def seed_missing_dimension(connection, table_name, frame, keys):
    existing = read_frame(
        connection, f"SELECT {', '.join(keys)} FROM gold.{table_name}"
    )
    if "full_date" in keys:
        existing = normalise_dates(existing, date_columns=("full_date",))
    missing = frame.merge(
        existing, on=keys, how="left", indicator=True, validate="one_to_one"
    )
    missing = missing.loc[missing["_merge"] == "left_only", frame.columns]
    append_frame(connection, table_name, missing)


def seed_dimensions(connection):
    dates = pd.Series(pd.date_range(CALENDAR_START, CALENDAR_END))
    week_starts = dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")
    reporting_week = ((dates - pd.Timestamp(REPORT_START)).dt.days // 7 + 1)
    reporting_week = reporting_week.where(
        dates.between(pd.Timestamp(REPORT_START), pd.Timestamp(REPORT_END))
    ).astype("Int64")
    date_frame = pd.DataFrame({
        "date_key": dates.dt.strftime("%Y%m%d").astype(int),
        "full_date": dates.dt.date,
        "day_name": dates.dt.day_name(),
        "day_of_week_number": dates.dt.dayofweek + 1,
        "is_weekend": dates.dt.dayofweek >= 5,
        "week_start_date": week_starts.dt.date,
        "week_end_date": (week_starts + pd.Timedelta(days=6)).dt.date,
        "iso_week_number": dates.dt.isocalendar().week,
        "reporting_week_number": reporting_week,
        "month_number": dates.dt.month,
        "month_name": dates.dt.month_name(),
        "quarter_number": dates.dt.quarter,
        "calendar_year": dates.dt.year,
    })
    resident_frame = pd.DataFrame(RESIDENTS, columns=["resident_id", "resident_name"])
    staff_frame = pd.DataFrame(
        STAFF, columns=["staff_id", "staff_role", "is_support_worker"]
    )
    log_types = pd.DataFrame(CONTROLLED_LOG_TYPES, columns=["category", "item"])
    log_types["log_type_name"] = log_types["category"] + " - " + log_types["item"]
    for table_name, frame, keys in (
        ("dim_date", date_frame, ["full_date"]),
        ("dim_resident", resident_frame, ["resident_id"]),
        ("dim_staff", staff_frame, ["staff_id"]),
        ("dim_log_type", log_types, ["category", "item"]),
    ):
        seed_missing_dimension(connection, table_name, frame, keys)


def load_dimension_maps(connection):
    date_frame = read_frame(
        connection,
        "SELECT date_key, full_date FROM gold.dim_date;",
    )
    date_frame = normalise_dates(date_frame, date_columns=("full_date",))
    date_map = dict(zip(date_frame["full_date"], date_frame["date_key"]))

    resident_frame = read_frame(
        connection,
        "SELECT resident_key, resident_id FROM gold.dim_resident;",
    )
    resident_map = dict(
        zip(resident_frame["resident_id"], resident_frame["resident_key"])
    )

    staff_frame = read_frame(
        connection,
        """
        SELECT staff_key, staff_id, is_support_worker
        FROM gold.dim_staff;
        """,
    )
    staff_map = dict(zip(staff_frame["staff_id"], staff_frame["staff_key"]))
    support_worker_ids = {
        row.staff_id
        for row in staff_frame.itertuples(index=False)
        if as_boolean(row.is_support_worker)
    }

    log_type_frame = read_frame(
        connection,
        """
        SELECT log_type_key, category, item
        FROM gold.dim_log_type;
        """,
    )
    log_type_map = {
        (row.category, row.item): row.log_type_key
        for row in log_type_frame.itertuples(index=False)
    }

    return {
        "date": date_map,
        "resident": resident_map,
        "staff": staff_map,
        "support_worker_ids": support_worker_ids,
        "log_type": log_type_map,
    }


def required_key(mapping, natural_key, dimension_name):
    if natural_key not in mapping:
        raise ValueError(
            f"No {dimension_name} key found for {natural_key!r}"
        )
    return int(mapping[natural_key])


def load_silver_frames(connection, source_file):
    frames = {}

    frames["log_event"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            category,
            item,
            title,
            description_clean,
            log_datetime,
            logged_by,
            bookmark,
            log_date,
            shift_type,
            week_start_date,
            source_file
        FROM silver.log_event
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["activity"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            activity_type,
            is_housework,
            staff_involved,
            log_datetime,
            log_date,
            logged_by,
            source_file
        FROM silver.activity
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["appointment"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            appointment_type,
            appointment_status,
            scheduled_datetime,
            scheduled_end_datetime,
            supported_by_staff,
            completed,
            log_datetime,
            log_date,
            logged_by,
            source_file
        FROM silver.appointment
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["communication"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            communication_label,
            communication_score,
            log_datetime,
            log_date,
            shift_type,
            logged_by,
            source_file
        FROM silver.communication
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["incident"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            incident_type,
            incident_detail,
            log_datetime,
            log_date,
            shift_type,
            logged_by,
            witnessed_by,
            description_clean,
            bookmark,
            source_file
        FROM silver.incident
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["medication"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            medication_round,
            medication_status,
            log_datetime,
            log_date,
            week_start_date,
            logged_by,
            source_file
        FROM silver.medication
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["mood"] = read_frame(
        connection,
        """
        SELECT
            log_event_key,
            resident_id,
            mood_label,
            mood_score,
            log_datetime,
            log_date,
            shift_type,
            logged_by,
            source_file
        FROM silver.mood
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["staff_shift"] = read_frame(
        connection,
        """
        SELECT
            staff_name,
            shift_date,
            shift_type,
            first_log_datetime,
            last_log_datetime,
            log_count,
            source_file
        FROM silver.staff_shift
        WHERE source_file = :source_file;
        """,
        {"source_file": source_file},
    )

    frames["log_event"] = normalise_dates(
        frames["log_event"],
        date_columns=("log_date", "week_start_date"),
        datetime_columns=("log_datetime",),
    )
    frames["activity"] = normalise_dates(
        frames["activity"],
        date_columns=("log_date",),
        datetime_columns=("log_datetime",),
    )
    frames["appointment"] = normalise_dates(
        frames["appointment"],
        date_columns=("log_date",),
        datetime_columns=(
            "scheduled_datetime",
            "scheduled_end_datetime",
            "log_datetime",
        ),
    )
    frames["communication"] = normalise_dates(
        frames["communication"],
        date_columns=("log_date",),
        datetime_columns=("log_datetime",),
    )
    frames["incident"] = normalise_dates(
        frames["incident"],
        date_columns=("log_date",),
        datetime_columns=("log_datetime",),
    )
    frames["medication"] = normalise_dates(
        frames["medication"],
        date_columns=("log_date", "week_start_date"),
        datetime_columns=("log_datetime",),
    )
    frames["mood"] = normalise_dates(
        frames["mood"],
        date_columns=("log_date",),
        datetime_columns=("log_datetime",),
    )
    frames["staff_shift"] = normalise_dates(
        frames["staff_shift"],
        date_columns=("shift_date",),
        datetime_columns=("first_log_datetime", "last_log_datetime"),
    )
    return frames


def validate_silver_source(frames, source_file):
    events = frames["log_event"]
    if events.empty:
        raise ValueError(f"No Silver rows found for {source_file}")

    allowed_residents = {resident_id for resident_id, _ in RESIDENTS}
    unexpected_residents = sorted(
        set(events["resident_id"].dropna()) - allowed_residents
    )
    if unexpected_residents:
        raise ValueError(
            f"Unexpected Silver resident IDs: {unexpected_residents}"
        )

    allowed_staff = {staff_id for staff_id, _, _ in STAFF}
    unexpected_staff = sorted(set(events["logged_by"].dropna()) - allowed_staff)
    if unexpected_staff:
        raise ValueError(f"Unexpected Silver staff IDs: {unexpected_staff}")

    allowed_log_types = set(CONTROLLED_LOG_TYPES)
    silver_log_types = set(
        zip(events["category"].tolist(), events["item"].tolist())
    )
    unexpected_log_types = sorted(silver_log_types - allowed_log_types)
    if unexpected_log_types:
        raise ValueError(
            "Add these controlled log types to CONTROLLED_LOG_TYPES before "
            f"loading Gold: {unexpected_log_types}"
        )

    expected_incident_keys = set(
        events.loc[
            events["category"] == "Incident",
            "log_event_key",
        ].tolist()
    )
    typed_incident_keys = set(frames["incident"]["log_event_key"].tolist())
    if typed_incident_keys != expected_incident_keys:
        missing_keys = sorted(expected_incident_keys - typed_incident_keys)
        orphan_keys = sorted(typed_incident_keys - expected_incident_keys)
        raise ValueError(
            "silver.incident is not aligned with silver.log_event. "
            f"Missing incident keys: {missing_keys}; orphan keys: {orphan_keys}"
        )

    week_starts = sorted(set(events["week_start_date"].dropna()))
    if len(week_starts) != 1:
        raise ValueError(
            f"Expected one week_start_date for {source_file}, found {week_starts}"
        )

    return week_starts[0]


def delete_previous_gold_load(connection, source_file):
    for table_name in FACT_COLUMNS:
        connection.execute(
            text(f"DELETE FROM gold.{table_name} WHERE source_file = :source_file"),
            {"source_file": source_file},
        )


def add_dimension_keys(frame, maps, date_column="log_date", staff_column=None,
                       log_type=False):
    frame = frame.copy()
    mappings = [(date_column, "date_key", maps["date"])]
    if "resident_id" in frame.columns:
        mappings.append(("resident_id", "resident_key", maps["resident"]))
    if staff_column is not None:
        mappings.append((staff_column, "staff_key", maps["staff"]))
    if log_type:
        frame["_log_type"] = list(zip(frame["category"], frame["item"]))
        mappings.append(("_log_type", "log_type_key", maps["log_type"]))
    for source_column, key_column, mapping in mappings:
        values = frame[source_column].map(mapping)
        if values.isna().any():
            missing = frame.loc[values.isna(), source_column].tolist()
            raise ValueError(f"No {key_column} found for {missing!r}")
        frame[key_column] = values.astype("int64")
    return frame


def fact_frame(frame, table_name, source_file):
    frame = frame.copy()
    frame["source_file"] = source_file
    return frame.loc[:, FACT_COLUMNS[table_name]]


def build_log_count_frame(events, maps, source_file):
    working = events.assign(
        bookmark_count=events["bookmark"].map(as_boolean).astype(int)
    )
    grouped = working.groupby(
        ["log_date", "resident_id", "logged_by", "category", "item", "shift_type"],
        dropna=False,
    ).agg(
        log_count=("log_event_key", "size"),
        bookmarked_log_count=("bookmark_count", "sum"),
    ).reset_index()
    grouped = add_dimension_keys(grouped, maps, staff_column="logged_by", log_type=True)
    return fact_frame(grouped, "agg_log_count_daily", source_file)


def daily_score_frame(frame, score_column, score_names, week_start_date):
    """Include all seven residents and all seven days, even when logs are absent."""
    working = frame.copy()
    working[score_column] = pd.to_numeric(working[score_column], errors="raise")
    aggregations = {
        "log_count": (score_column, "size"),
        "average_score": (score_column, "mean"),
        "minimum_score": (score_column, "min"),
    }
    for score, name in enumerate(score_names, start=1):
        working[name] = working[score_column].eq(score).astype(int)
        aggregations[name] = (name, "sum")
    count_columns = ["log_count", *score_names]
    if score_column == "communication_score":
        working["day_log_count"] = working["shift_type"].eq("Day").astype(int)
        working["night_log_count"] = working["shift_type"].eq("Night").astype(int)
        for name in ("day_log_count", "night_log_count"):
            aggregations[name] = (name, "sum")
            count_columns.append(name)
    grouped = working.groupby(["resident_id", "log_date"]).agg(**aggregations)
    grid = pd.MultiIndex.from_product(
        [[resident for resident, _ in RESIDENTS],
         pd.date_range(week_start_date, periods=7).date],
        names=["resident_id", "log_date"],
    )
    daily = grouped.reindex(grid).reset_index()
    daily[count_columns] = daily[count_columns].fillna(0).astype(int)
    daily["expected_log_count"] = EXPECTED_DAILY_LOGS
    daily["missing_log_count"] = (EXPECTED_DAILY_LOGS - daily["log_count"]).clip(lower=0)
    daily["average_score"] = daily["average_score"].round(2)
    return daily


def build_mood_frame(mood, maps, source_file, week_start_date):
    daily = daily_score_frame(
        mood, "mood_score",
        ["very_low_count", "low_count", "okay_count", "good_count", "very_good_count"],
        week_start_date,
    )
    daily["requires_review"] = daily["very_low_count"].ge(1) | (
        daily["very_low_count"] + daily["low_count"]
    ).ge(2)
    daily = daily.rename(columns={
        "log_count": "mood_log_count",
        "average_score": "average_mood_score",
        "minimum_score": "minimum_mood_score",
    })
    return fact_frame(add_dimension_keys(daily, maps), "fact_mood_daily", source_file)


def build_communication_frame(communication, maps, source_file, week_start_date):
    daily = daily_score_frame(
        communication, "communication_score",
        ["no_response_count", "minimal_count", "normal_count", "expansive_count"],
        week_start_date,
    )
    daily["requires_review"] = daily["log_count"].eq(0) | (
        daily["no_response_count"] + daily["minimal_count"]
    ).ge(2)
    daily = daily.rename(columns={
        "log_count": "total_log_count", "average_score": "average_communication"
    })
    return fact_frame(add_dimension_keys(daily, maps), "fact_communication", source_file)


def build_medication_frame(medication, maps, source_file):
    if medication.empty:
        return pd.DataFrame(columns=FACT_COLUMNS["fact_medication"])
    if not medication["medication_status"].isin(["Accepted", "Refused"]).all():
        raise ValueError("Silver medication_status must be Accepted or Refused")
    working = medication.assign(
        accepted=medication["medication_status"].eq("Accepted").astype(int),
        refused=medication["medication_status"].eq("Refused").astype(int),
        prn=medication["medication_round"].fillna("").astype(str).str.upper().eq("PRN").astype(int),
    )
    weekly = working.groupby(["resident_id", "week_start_date"]).agg(
        total_dose_count=("medication_status", "size"),
        accepted_dose_count=("accepted", "sum"),
        refused_dose_count=("refused", "sum"),
        prn_dose_count=("prn", "sum"),
    ).reset_index()
    weekly = add_dimension_keys(weekly, maps, date_column="week_start_date")
    weekly = weekly.rename(columns={"date_key": "week_start_date_key"})
    # These placeholders are refreshed with the full history before commit.
    weekly["has_baseline"] = False
    weekly["baseline_median_doses"] = None
    weekly["percentage_of_baseline"] = None
    weekly["requires_review"] = weekly["refused_dose_count"].gt(0)
    return fact_frame(weekly, "fact_medication", source_file)


def calculate_medication_baselines(history):
    """Use up to 12 earlier loaded weeks; never include the current/future week."""
    history = history.sort_values(
        ["resident_key", "week_start_date_key", "medication_key"]
    ).copy()
    # Aggregate same-week batches before rolling so one week is one observation.
    weekly = history.groupby(["resident_key", "week_start_date_key"], as_index=False).agg(
        accepted_dose_count=("accepted_dose_count", "sum")
    ).sort_values(["resident_key", "week_start_date_key"])
    weekly["baseline_median_doses"] = weekly.groupby("resident_key")[
        "accepted_dose_count"
    ].transform(
        lambda values: values.shift(1).rolling(
            MEDICATION_BASELINE_MAX_WEEKS,
            min_periods=MEDICATION_BASELINE_MIN_WEEKS,
        ).median()
    ).round(2)
    history = history.drop(columns=["baseline_median_doses"], errors="ignore").merge(
        weekly[["resident_key", "week_start_date_key", "baseline_median_doses"]],
        on=["resident_key", "week_start_date_key"],
        how="left",
        validate="many_to_one",
    )
    history["has_baseline"] = history["baseline_median_doses"].gt(0)
    history["baseline_median_doses"] = history["baseline_median_doses"].where(
        history["has_baseline"]
    )
    history["percentage_of_baseline"] = (
        history["accepted_dose_count"] / history["baseline_median_doses"] * 100
    ).round(2)
    history["requires_review"] = history["refused_dose_count"].gt(0) | (
        history["has_baseline"] & history["percentage_of_baseline"].lt(70)
    )
    return history


def refresh_medication_baselines(connection, from_week_key):
    history = read_frame(connection, """
        SELECT medication_key, week_start_date_key, resident_key,
               accepted_dose_count, refused_dose_count
        FROM gold.fact_medication
    """)
    if history.empty:
        return 0
    refreshed = calculate_medication_baselines(history)
    refreshed = refreshed.loc[
        refreshed["week_start_date_key"] >= from_week_key,
        ["medication_key", "has_baseline", "baseline_median_doses",
         "percentage_of_baseline", "requires_review"],
    ]
    if refreshed.empty:
        return 0
    # Update derived values only: preserve later facts' keys, counts and lineage.
    parameters = [
        {key: as_database_value(value) for key, value in row.items()}
        for row in refreshed.to_dict("records")
    ]
    connection.execute(text("""
        UPDATE gold.fact_medication
        SET has_baseline = :has_baseline,
            baseline_median_doses = :baseline_median_doses,
            percentage_of_baseline = :percentage_of_baseline,
            requires_review = :requires_review
        WHERE medication_key = :medication_key
    """), parameters)
    return len(parameters)


def build_appointment_frame(appointments, maps, source_file):
    if appointments.empty:
        return pd.DataFrame(columns=FACT_COLUMNS["fact_appointment"])

    appointment_records = []
    for appointment in appointments.itertuples(index=False):
        status = clean_text(appointment.appointment_status)
        start = (
            None
            if pd.isna(appointment.scheduled_datetime)
            else appointment.scheduled_datetime.to_pydatetime()
        )
        end = (
            None
            if pd.isna(appointment.scheduled_end_datetime)
            else appointment.scheduled_end_datetime.to_pydatetime()
        )

        if status in BOOKING_STATUSES:
            if start is None:
                raise ValueError(
                    "Appointment booking "
                    f"{appointment.log_event_key} has no start time"
                )
            if end is None:
                raise ValueError(
                    "Appointment booking "
                    f"{appointment.log_event_key} has no end time"
                )
            appointment_date = start.date()
        else:
            # Outcome rows remain independent events. They are dated using
            # the day on which the outcome was logged and are not matched to
            # an earlier booking.
            appointment_date = appointment.log_date

        staff_required = None
        if not pd.isna(appointment.supported_by_staff):
            staff_required = as_boolean(appointment.supported_by_staff)

        appointment_records.append(
            {
                "appointment_date": appointment_date,
                "resident_id": appointment.resident_id,
                "appointment_type": appointment.appointment_type,
                "appointment_status": status,
                "start": start,
                "end": end,
                "staff_required": staff_required,
                "completed": as_boolean(appointment.completed),
                "has_conflict": False,
                "source_log_event_key": int(appointment.log_event_key),
            }
        )

    # Conflict detection applies only to scheduled, staff-required bookings.
    # Outcome rows have no schedule and remain independent events.
    for first_index, first in enumerate(appointment_records):
        if not first["staff_required"] or first["start"] is None:
            continue

        for second_index in range(
            first_index + 1,
            len(appointment_records),
        ):
            second = appointment_records[second_index]
            if not second["staff_required"] or second["start"] is None:
                continue

            overlaps = first["start"] < second["end"] and (
                second["start"] < first["end"]
            )
            if overlaps:
                first["has_conflict"] = True
                second["has_conflict"] = True

    rows = []
    for record in appointment_records:
        rows.append(
            (
                required_key(
                    maps["date"], record["appointment_date"], "date"
                ),
                required_key(
                    maps["resident"], record["resident_id"], "resident"
                ),
                record["appointment_type"],
                record["appointment_status"],
                record["start"],
                record["end"],
                record["staff_required"],
                record["completed"],
                record["has_conflict"],
                record["source_log_event_key"],
                source_file,
            )
        )

    return pd.DataFrame(rows, columns=FACT_COLUMNS["fact_appointment"])


def build_incident_frame(incidents, maps, source_file):
    frame = add_dimension_keys(incidents, maps, staff_column="logged_by")
    frame = frame.rename(columns={
        "log_datetime": "incident_datetime", "log_event_key": "source_log_event_key",
        "bookmark": "bookmarked",
    })
    for column in ("incident_type", "incident_detail", "witnessed_by", "description_clean"):
        frame[column] = frame[column].map(clean_text)
    frame["bookmarked"] = frame["bookmarked"].map(as_boolean)
    return fact_frame(frame, "fact_incident", source_file)


def build_staff_shift_frame(staff_shifts, events, maps, source_file):
    working = events.copy()
    dates = working["log_datetime"].dt.normalize()
    early_night = working["shift_type"].eq("Night") & working["log_datetime"].dt.hour.lt(8)
    working["shift_date"] = (dates - pd.to_timedelta(early_night.astype(int), unit="D")).dt.date
    residents = working.groupby(["logged_by", "shift_date", "shift_type"])[
        "resident_id"
    ].nunique().rename("resident_count").reset_index().rename(
        columns={"logged_by": "staff_name"}
    )
    shifts = staff_shifts.loc[
        staff_shifts["staff_name"].isin(maps["support_worker_ids"])
    ].merge(
        residents, on=["staff_name", "shift_date", "shift_type"],
        how="left", validate="many_to_one",
    )
    if shifts["resident_count"].fillna(0).lt(1).any():
        raise ValueError("Could not derive a resident count for a staff shift")
    shifts["resident_count"] = shifts["resident_count"].astype(int)
    shifts = add_dimension_keys(shifts, maps, date_column="shift_date", staff_column="staff_name")
    return fact_frame(shifts, "fact_staff_shift", source_file)


def build_staff_involvement_frame(activities, appointments, maps, source_file):
    activities = activities.loc[
        activities["staff_involved"].map(as_boolean)
        & activities["logged_by"].isin(maps["support_worker_ids"])
    ].copy()
    activities["involvement_type"] = activities["is_housework"].map(as_boolean).map(
        {True: "Cleaning Task", False: "Resident Activity"}
    )
    activities["involvement_detail"] = activities["activity_type"].map(clean_text)
    appointments = appointments.loc[
        appointments["appointment_status"].eq("Completed with Staff")
        & appointments["logged_by"].isin(maps["support_worker_ids"])
    ].copy()
    appointments["involvement_type"] = "Appointment Escort"
    appointments["involvement_detail"] = appointments["appointment_type"].map(clean_text)
    columns = ["log_date", "resident_id", "logged_by", "log_event_key",
               "involvement_type", "involvement_detail"]
    combined = pd.concat([activities[columns], appointments[columns]], ignore_index=True)
    combined = add_dimension_keys(combined, maps, staff_column="logged_by")
    combined = combined.rename(columns={"log_event_key": "source_log_event_key"})
    return fact_frame(combined, "fact_staff_involvement", source_file)


def build_flagged_log_frame(events, maps, source_file):
    frame = events.loc[events["bookmark"].map(as_boolean)].copy()
    frame = add_dimension_keys(frame, maps, staff_column="logged_by", log_type=True)
    frame = frame.rename(columns={
        "log_event_key": "source_log_event_key", "log_datetime": "logged_at"
    })
    for column in ("title", "description_clean"):
        frame[column] = frame[column].map(clean_text)
    return fact_frame(frame, "fact_flagged_log", source_file)


def build_gold_frames(frames, maps, source_file, week_start_date):
    return {
        "agg_log_count_daily": build_log_count_frame(frames["log_event"], maps, source_file),
        "fact_mood_daily": build_mood_frame(frames["mood"], maps, source_file, week_start_date),
        "fact_communication": build_communication_frame(
            frames["communication"], maps, source_file, week_start_date
        ),
        "fact_medication": build_medication_frame(frames["medication"], maps, source_file),
        "fact_appointment": build_appointment_frame(frames["appointment"], maps, source_file),
        "fact_incident": build_incident_frame(frames["incident"], maps, source_file),
        "fact_staff_shift": build_staff_shift_frame(
            frames["staff_shift"], frames["log_event"], maps, source_file
        ),
        "fact_staff_involvement": build_staff_involvement_frame(
            frames["activity"], frames["appointment"], maps, source_file
        ),
        "fact_flagged_log": build_flagged_log_frame(frames["log_event"], maps, source_file),
    }


def load_gold_tables(engine, source_file):
    """Load one file atomically using a SQLAlchemy Engine."""
    source_file = clean_text(source_file)
    if not source_file:
        raise ValueError("source_file is required")

    with engine.begin() as connection:
        # Serialize Gold writers, including dimension seeding and baseline refresh.
        # Transaction ownership releases the lock on both commit and rollback.
        if connection.dialect.name == "mssql":
            connection.execute(text("""
                IF @@TRANCOUNT = 0 BEGIN TRANSACTION;
                DECLARE @result int;
                EXEC @result = sys.sp_getapplock
                    @Resource = N'care_logs_gold_load',
                    @LockMode = N'Exclusive',
                    @LockOwner = N'Transaction',
                    @LockTimeout = 60000;
                IF @result < 0
                    THROW 50001, 'Could not acquire the Gold load lock', 1;
            """))

        seed_dimensions(connection)
        maps = load_dimension_maps(connection)
        frames = load_silver_frames(connection, source_file)
        week_start_date = validate_silver_source(frames, source_file)
        gold_frames = build_gold_frames(frames, maps, source_file, week_start_date)

        previous = read_frame(connection, """
            SELECT MIN(week_start_date_key) AS first_week
            FROM gold.fact_medication WHERE source_file = :source_file
        """, {"source_file": source_file})
        from_week_key = make_date_key(week_start_date)
        if pd.notna(previous.iloc[0]["first_week"]):
            from_week_key = min(from_week_key, int(previous.iloc[0]["first_week"]))

        delete_previous_gold_load(connection, source_file)
        gold_counts = {
            table: append_frame(connection, table, frame)
            for table, frame in gold_frames.items()
        }
        refreshed_count = refresh_medication_baselines(connection, from_week_key)
        dimension_counts = {
            table: int(read_frame(
                connection, f"SELECT COUNT(*) AS row_count FROM gold.{table}"
            ).iloc[0]["row_count"])
            for table in ("dim_date", "dim_resident", "dim_staff", "dim_log_type")
        }

    return {
        "status": "Succeeded",
        "source_file": source_file,
        "week_start_date": week_start_date.isoformat(),
        "dimension_rows": dimension_counts,
        "gold_rows": gold_counts,
        "medication_baselines_refreshed": refreshed_count,
    }
