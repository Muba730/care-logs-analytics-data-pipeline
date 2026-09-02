"""Loads one validated Silver file into the Gold reporting tables."""

from datetime import date, datetime, timedelta
from statistics import median

import pandas as pd


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


def fetch_dataframe(cursor, query, parameters=()):
    cursor.execute(query, parameters)
    column_names = [column[0] for column in cursor.description]
    return pd.DataFrame.from_records(cursor.fetchall(), columns=column_names)


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


def seed_date_dimension(cursor):
    rows = []
    current_date = CALENDAR_START

    while current_date <= CALENDAR_END:
        day_number = current_date.weekday() + 1
        week_start_date = current_date - timedelta(days=current_date.weekday())
        week_end_date = week_start_date + timedelta(days=6)

        reporting_week_number = None
        if REPORT_START <= current_date <= REPORT_END:
            reporting_week_number = (
                (current_date - REPORT_START).days // 7
            ) + 1

        rows.append(
            (
                make_date_key(current_date),
                current_date,
                current_date.strftime("%A"),
                day_number,
                day_number in {6, 7},
                week_start_date,
                week_end_date,
                current_date.isocalendar().week,
                reporting_week_number,
                current_date.month,
                current_date.strftime("%B"),
                ((current_date.month - 1) // 3) + 1,
                current_date.year,
            )
        )
        current_date += timedelta(days=1)

    cursor.executemany(
        """
        INSERT INTO gold.dim_date (
            date_key,
            full_date,
            day_name,
            day_of_week_number,
            is_weekend,
            week_start_date,
            week_end_date,
            iso_week_number,
            reporting_week_number,
            month_number,
            month_name,
            quarter_number,
            calendar_year
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM gold.dim_date
            WHERE full_date = ?
        );
        """,
        [row + (row[1],) for row in rows],
    )


def seed_resident_dimension(cursor):
    cursor.executemany(
        """
        INSERT INTO gold.dim_resident (
            resident_id,
            resident_name
        )
        SELECT ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM gold.dim_resident
            WHERE resident_id = ?
        );
        """,
        [row + (row[0],) for row in RESIDENTS],
    )


def seed_staff_dimension(cursor):
    cursor.executemany(
        """
        INSERT INTO gold.dim_staff (
            staff_id,
            staff_role,
            is_support_worker
        )
        SELECT ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM gold.dim_staff
            WHERE staff_id = ?
        );
        """,
        [row + (row[0],) for row in STAFF],
    )


def seed_log_type_dimension(cursor):
    rows = [
        (category, item, f"{category} - {item}", category, item)
        for category, item in CONTROLLED_LOG_TYPES
    ]

    cursor.executemany(
        """
        INSERT INTO gold.dim_log_type (
            category,
            item,
            log_type_name
        )
        SELECT ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM gold.dim_log_type
            WHERE category = ?
              AND item = ?
        );
        """,
        rows,
    )


def seed_dimensions(cursor):
    seed_date_dimension(cursor)
    seed_resident_dimension(cursor)
    seed_staff_dimension(cursor)
    seed_log_type_dimension(cursor)


def load_dimension_maps(cursor):
    date_frame = fetch_dataframe(
        cursor,
        "SELECT date_key, full_date FROM gold.dim_date;",
    )
    date_frame = normalise_dates(date_frame, date_columns=("full_date",))
    date_map = dict(zip(date_frame["full_date"], date_frame["date_key"]))

    resident_frame = fetch_dataframe(
        cursor,
        "SELECT resident_key, resident_id FROM gold.dim_resident;",
    )
    resident_map = dict(
        zip(resident_frame["resident_id"], resident_frame["resident_key"])
    )

    staff_frame = fetch_dataframe(
        cursor,
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

    log_type_frame = fetch_dataframe(
        cursor,
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


def load_silver_frames(cursor, source_file):
    frames = {}

    frames["log_event"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["activity"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["appointment"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["communication"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["incident"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["medication"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["mood"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
    )

    frames["staff_shift"] = fetch_dataframe(
        cursor,
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
        WHERE source_file = ?;
        """,
        (source_file,),
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


def delete_previous_gold_load(cursor, source_file):
    # Replacing one source-file batch makes reruns safe.
    for table_name in (
        "gold.agg_log_count_daily",
        "gold.fact_mood_daily",
        "gold.fact_communication",
        "gold.fact_medication",
        "gold.fact_appointment",
        "gold.fact_incident",
        "gold.fact_staff_shift",
        "gold.fact_staff_involvement",
        "gold.fact_flagged_log",
    ):
        cursor.execute(
            f"DELETE FROM {table_name} WHERE source_file = ?",
            (source_file,),
        )


def build_log_count_rows(events, maps, source_file):
    working = events.copy()
    working["bookmark_count"] = working["bookmark"].map(as_boolean).astype(int)

    grouped = (
        working.groupby(
            [
                "log_date",
                "resident_id",
                "logged_by",
                "category",
                "item",
                "shift_type",
            ],
            dropna=False,
        )
        .agg(
            log_count=("log_event_key", "size"),
            bookmarked_log_count=("bookmark_count", "sum"),
        )
        .reset_index()
    )

    rows = []
    for row in grouped.itertuples(index=False):
        rows.append(
            (
                required_key(maps["date"], row.log_date, "date"),
                required_key(
                    maps["resident"], row.resident_id, "resident"
                ),
                required_key(maps["staff"], row.logged_by, "staff"),
                required_key(
                    maps["log_type"],
                    (row.category, row.item),
                    "log type",
                ),
                row.shift_type,
                int(row.log_count),
                int(row.bookmarked_log_count),
                source_file,
            )
        )

    return rows


def build_mood_rows(mood, maps, source_file, week_start_date):
    score_groups = {}
    if not mood.empty:
        score_groups = (
            mood.groupby(["resident_id", "log_date"])["mood_score"]
            .apply(lambda values: [int(value) for value in values])
            .to_dict()
        )

    rows = []
    for resident_id, _ in RESIDENTS:
        for day_offset in range(7):
            log_date = week_start_date + timedelta(days=day_offset)
            scores = score_groups.get((resident_id, log_date), [])
            score_counts = {score: scores.count(score) for score in range(1, 6)}
            log_count = len(scores)
            missing_count = max(0, EXPECTED_DAILY_LOGS - log_count)
            average_score = round(sum(scores) / log_count, 2) if scores else None
            minimum_score = min(scores) if scores else None

            # This is the daily signal. Cross-day deterioration is calculated
            # later over the daily rows in Power BI.
            requires_review = score_counts[1] >= 1 or (
                score_counts[1] + score_counts[2] >= 2
            )

            rows.append(
                (
                    required_key(maps["date"], log_date, "date"),
                    required_key(
                        maps["resident"], resident_id, "resident"
                    ),
                    log_count,
                    EXPECTED_DAILY_LOGS,
                    missing_count,
                    score_counts[1],
                    score_counts[2],
                    score_counts[3],
                    score_counts[4],
                    score_counts[5],
                    average_score,
                    minimum_score,
                    requires_review,
                    source_file,
                )
            )

    return rows


def build_communication_rows(
    communication,
    maps,
    source_file,
    week_start_date,
):
    grouped = {}
    if not communication.empty:
        for (resident_id, log_date), group in communication.groupby(
            ["resident_id", "log_date"]
        ):
            scores = [int(value) for value in group["communication_score"]]
            grouped[(resident_id, log_date)] = {
                "scores": scores,
                "day_count": int((group["shift_type"] == "Day").sum()),
                "night_count": int((group["shift_type"] == "Night").sum()),
            }

    rows = []
    for resident_id, _ in RESIDENTS:
        for day_offset in range(7):
            log_date = week_start_date + timedelta(days=day_offset)
            values = grouped.get(
                (resident_id, log_date),
                {"scores": [], "day_count": 0, "night_count": 0},
            )
            scores = values["scores"]
            score_counts = {score: scores.count(score) for score in range(1, 5)}
            total_count = len(scores)
            missing_count = max(0, EXPECTED_DAILY_LOGS - total_count)
            average_score = (
                round(sum(scores) / total_count, 2) if scores else None
            )
            requires_review = total_count == 0 or (
                score_counts[1] + score_counts[2] >= 2
            )

            rows.append(
                (
                    required_key(maps["date"], log_date, "date"),
                    required_key(
                        maps["resident"], resident_id, "resident"
                    ),
                    values["day_count"],
                    values["night_count"],
                    total_count,
                    EXPECTED_DAILY_LOGS,
                    missing_count,
                    score_counts[1],
                    score_counts[2],
                    score_counts[3],
                    score_counts[4],
                    average_score,
                    requires_review,
                    source_file,
                )
            )

    return rows


def fetch_medication_history(cursor, current_week_start):
    history = fetch_dataframe(
        cursor,
        """
        SELECT
            resident.resident_id,
            calendar.full_date AS week_start_date,
            medication.accepted_dose_count
        FROM gold.fact_medication AS medication
        JOIN gold.dim_resident AS resident
          ON resident.resident_key = medication.resident_key
        JOIN gold.dim_date AS calendar
          ON calendar.date_key = medication.week_start_date_key
        WHERE calendar.full_date < ?
        ORDER BY
            resident.resident_id,
            calendar.full_date;
        """,
        (current_week_start,),
    )
    return normalise_dates(history, date_columns=("week_start_date",))


def build_medication_rows(
    medication,
    history,
    maps,
    source_file,
):
    if medication.empty:
        return []

    statuses = set(medication["medication_status"].dropna())
    unexpected_statuses = sorted(statuses - {"Accepted", "Refused"})
    if unexpected_statuses:
        raise ValueError(
            f"Unexpected medication statuses in Silver: {unexpected_statuses}"
        )
    if medication["medication_status"].isna().any():
        raise ValueError("A Silver medication row is missing medication_status")

    rows = []
    for (resident_id, week_start_date), group in medication.groupby(
        ["resident_id", "week_start_date"]
    ):
        total_count = len(group)
        accepted_count = int((group["medication_status"] == "Accepted").sum())
        refused_count = int((group["medication_status"] == "Refused").sum())
        prn_count = int(
            group["medication_round"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("PRN")
            .sum()
        )

        previous_values = []
        if not history.empty:
            resident_history = history[
                history["resident_id"] == resident_id
            ].sort_values("week_start_date")
            previous_values = [
                int(value)
                for value in resident_history["accepted_dose_count"].tail(
                    MEDICATION_BASELINE_MAX_WEEKS
                )
            ]

        has_baseline = len(previous_values) >= MEDICATION_BASELINE_MIN_WEEKS
        baseline_value = None
        percentage_of_baseline = None
        if has_baseline:
            baseline_value = round(float(median(previous_values)), 2)
            if baseline_value > 0:
                percentage_of_baseline = round(
                    accepted_count / baseline_value * 100,
                    2,
                )
            else:
                has_baseline = False
                baseline_value = None

        requires_review = refused_count > 0 or (
            has_baseline
            and percentage_of_baseline is not None
            and percentage_of_baseline < 70
        )

        rows.append(
            (
                required_key(
                    maps["date"], week_start_date, "week-start date"
                ),
                required_key(
                    maps["resident"], resident_id, "resident"
                ),
                total_count,
                accepted_count,
                refused_count,
                prn_count,
                has_baseline,
                baseline_value,
                percentage_of_baseline,
                requires_review,
                source_file,
            )
        )

    return rows


def build_appointment_rows(appointments, maps, source_file):
    if appointments.empty:
        return []

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

    return rows


def build_incident_rows(incidents, maps, source_file):
    rows = []

    for incident in incidents.itertuples(index=False):
        rows.append(
            (
                required_key(maps["date"], incident.log_date, "date"),
                required_key(
                    maps["resident"], incident.resident_id, "resident"
                ),
                required_key(maps["staff"], incident.logged_by, "staff"),
                clean_text(incident.incident_type),
                clean_text(incident.incident_detail),
                incident.log_datetime.to_pydatetime(),
                incident.shift_type,
                clean_text(incident.witnessed_by),
                clean_text(incident.description_clean),
                as_boolean(incident.bookmark),
                int(incident.log_event_key),
                source_file,
            )
        )

    return rows


def derive_shift_date(log_datetime, shift_type):
    log_date = log_datetime.date()
    if shift_type == "Night" and log_datetime.hour < 8:
        return log_date - timedelta(days=1)
    return log_date


def build_staff_shift_rows(staff_shifts, events, maps, source_file):
    working_events = events.copy()
    working_events["shift_date"] = working_events.apply(
        lambda row: derive_shift_date(
            row["log_datetime"],
            row["shift_type"],
        ),
        axis=1,
    )
    resident_counts = (
        working_events.groupby(
            ["logged_by", "shift_date", "shift_type"]
        )["resident_id"]
        .nunique()
        .to_dict()
    )

    rows = []
    for shift in staff_shifts.itertuples(index=False):
        if shift.staff_name not in maps["support_worker_ids"]:
            continue

        resident_count = int(
            resident_counts.get(
                (shift.staff_name, shift.shift_date, shift.shift_type),
                0,
            )
        )
        if resident_count < 1:
            raise ValueError(
                "Could not derive a resident count for staff shift "
                f"{shift.staff_name}, {shift.shift_date}, {shift.shift_type}"
            )

        rows.append(
            (
                required_key(maps["date"], shift.shift_date, "shift date"),
                required_key(maps["staff"], shift.staff_name, "staff"),
                shift.shift_type,
                shift.first_log_datetime.to_pydatetime(),
                shift.last_log_datetime.to_pydatetime(),
                int(shift.log_count),
                resident_count,
                source_file,
            )
        )

    return rows


def build_staff_involvement_rows(
    activities,
    appointments,
    maps,
    source_file,
):
    rows = []

    for activity in activities.itertuples(index=False):
        if not as_boolean(activity.staff_involved):
            continue
        if activity.logged_by not in maps["support_worker_ids"]:
            continue

        involvement_type = (
            "Cleaning Task"
            if as_boolean(activity.is_housework)
            else "Resident Activity"
        )

        rows.append(
            (
                required_key(maps["date"], activity.log_date, "date"),
                required_key(
                    maps["resident"], activity.resident_id, "resident"
                ),
                required_key(
                    maps["staff"], activity.logged_by, "staff"
                ),
                involvement_type,
                clean_text(activity.activity_type),
                int(activity.log_event_key),
                source_file,
            )
        )

    supported_outcomes = appointments[
        appointments["appointment_status"] == "Completed with Staff"
    ]
    for appointment in supported_outcomes.itertuples(index=False):
        if appointment.logged_by not in maps["support_worker_ids"]:
            continue

        rows.append(
            (
                required_key(maps["date"], appointment.log_date, "date"),
                required_key(
                    maps["resident"], appointment.resident_id, "resident"
                ),
                required_key(
                    maps["staff"], appointment.logged_by, "staff"
                ),
                "Appointment Escort",
                clean_text(appointment.appointment_type),
                int(appointment.log_event_key),
                source_file,
            )
        )

    return rows


def build_flagged_log_rows(events, maps, source_file):
    flagged_events = events[events["bookmark"].map(as_boolean)]
    rows = []

    for event in flagged_events.itertuples(index=False):
        rows.append(
            (
                required_key(maps["date"], event.log_date, "date"),
                required_key(
                    maps["resident"], event.resident_id, "resident"
                ),
                required_key(maps["staff"], event.logged_by, "staff"),
                required_key(
                    maps["log_type"],
                    (event.category, event.item),
                    "log type",
                ),
                int(event.log_event_key),
                event.log_datetime.to_pydatetime(),
                event.shift_type,
                clean_text(event.title),
                clean_text(event.description_clean),
                source_file,
            )
        )

    return rows


def insert_rows(cursor, insert_sql, rows):
    if rows:
        cursor.executemany(insert_sql, rows)
    return len(rows)


def insert_gold_facts(
    cursor,
    frames,
    maps,
    source_file,
    week_start_date,
):
    counts = {}

    log_count_rows = build_log_count_rows(
        frames["log_event"], maps, source_file
    )
    counts["agg_log_count_daily"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.agg_log_count_daily (
            date_key,
            resident_key,
            staff_key,
            log_type_key,
            shift_type,
            log_count,
            bookmarked_log_count,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        log_count_rows,
    )

    mood_rows = build_mood_rows(
        frames["mood"],
        maps,
        source_file,
        week_start_date,
    )
    counts["fact_mood_daily"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_mood_daily (
            date_key,
            resident_key,
            mood_log_count,
            expected_log_count,
            missing_log_count,
            very_low_count,
            low_count,
            okay_count,
            good_count,
            very_good_count,
            average_mood_score,
            minimum_mood_score,
            requires_review,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        mood_rows,
    )

    communication_rows = build_communication_rows(
        frames["communication"],
        maps,
        source_file,
        week_start_date,
    )
    counts["fact_communication"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_communication (
            date_key,
            resident_key,
            day_log_count,
            night_log_count,
            total_log_count,
            expected_log_count,
            missing_log_count,
            no_response_count,
            minimal_count,
            normal_count,
            expansive_count,
            average_communication,
            requires_review,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        communication_rows,
    )

    history = fetch_medication_history(cursor, week_start_date)
    medication_rows = build_medication_rows(
        frames["medication"],
        history,
        maps,
        source_file,
    )
    counts["fact_medication"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_medication (
            week_start_date_key,
            resident_key,
            total_dose_count,
            accepted_dose_count,
            refused_dose_count,
            prn_dose_count,
            has_baseline,
            baseline_median_doses,
            percentage_of_baseline,
            requires_review,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        medication_rows,
    )

    appointment_rows = build_appointment_rows(
        frames["appointment"], maps, source_file
    )
    counts["fact_appointment"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_appointment (
            appointment_date_key,
            resident_key,
            appointment_type,
            appointment_status,
            scheduled_start_datetime,
            scheduled_end_datetime,
            staff_required,
            completed,
            has_conflict,
            source_log_event_key,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        appointment_rows,
    )

    incident_rows = build_incident_rows(
        frames["incident"], maps, source_file
    )
    counts["fact_incident"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_incident (
            date_key,
            resident_key,
            staff_key,
            incident_type,
            incident_detail,
            incident_datetime,
            shift_type,
            witnessed_by,
            description_clean,
            bookmarked,
            source_log_event_key,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        incident_rows,
    )

    staff_shift_rows = build_staff_shift_rows(
        frames["staff_shift"],
        frames["log_event"],
        maps,
        source_file,
    )
    counts["fact_staff_shift"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_staff_shift (
            date_key,
            staff_key,
            shift_type,
            first_log_datetime,
            last_log_datetime,
            log_count,
            resident_count,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        staff_shift_rows,
    )

    involvement_rows = build_staff_involvement_rows(
        frames["activity"],
        frames["appointment"],
        maps,
        source_file,
    )
    counts["fact_staff_involvement"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_staff_involvement (
            date_key,
            resident_key,
            staff_key,
            involvement_type,
            involvement_detail,
            source_log_event_key,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        involvement_rows,
    )

    flagged_rows = build_flagged_log_rows(
        frames["log_event"], maps, source_file
    )
    counts["fact_flagged_log"] = insert_rows(
        cursor,
        """
        INSERT INTO gold.fact_flagged_log (
            date_key,
            resident_key,
            staff_key,
            log_type_key,
            source_log_event_key,
            logged_at,
            shift_type,
            title,
            description_clean,
            source_file
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        flagged_rows,
    )

    return counts


def get_dimension_counts(cursor):
    counts = {}
    for table_name in (
        "dim_date",
        "dim_resident",
        "dim_staff",
        "dim_log_type",
    ):
        cursor.execute(f"SELECT COUNT(*) FROM gold.{table_name};")
        counts[table_name] = int(cursor.fetchone()[0])
    return counts


def load_gold_tables(connection, source_file):
    source_file = clean_text(source_file)
    if not source_file:
        raise ValueError("source_file is required")

    cursor = connection.cursor()
    try:
        seed_dimensions(cursor)
        maps = load_dimension_maps(cursor)

        frames = load_silver_frames(cursor, source_file)
        week_start_date = validate_silver_source(frames, source_file)

        delete_previous_gold_load(cursor, source_file)
        gold_counts = insert_gold_facts(
            cursor,
            frames,
            maps,
            source_file,
            week_start_date,
        )

        dimension_counts = get_dimension_counts(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return {
        "status": "Succeeded",
        "source_file": source_file,
        "week_start_date": week_start_date.isoformat(),
        "dimension_rows": dimension_counts,
        "gold_rows": gold_counts,
    }
