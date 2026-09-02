"""Loads one weekly file from Bronze into the Silver tables.

Two stages, called in order by the Azure Functions:
    load_bronze_to_log_event()       -> silver.log_event
    load_log_event_to_silver_tables() -> the typed Silver tables
"""

import os
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta


# Values outside these sets are rejected in validate_record().
APPOINTMENT_STATUSES = {
    "Staff Required",
    "No Staff Required",
    "Completed with Staff",
    "Completed without Staff",
    "Cancelled by Client",
    "Unable to Attend",
}

BOOKING_STATUSES = {"Staff Required", "No Staff Required"}
COMPLETED_STATUSES = {"Completed with Staff", "Completed without Staff"}

INCIDENT_TYPES = {
    "Negative Behaviour",
    "Self-Harm Concern",
    "Fall",
    "Assault",
    "Missing Person",
    "Other",
}

MOOD_SCORES = {
    "Very Low": 1,
    "Low": 2,
    "Okay": 3,
    "Good": 4,
    "Very Good": 5,
}

COMMUNICATION_SCORES = {
    "No response": 1,
    "Minimal": 2,
    "Normal": 3,
    "Expansive": 4,
}

# These are the seven residents used throughout the project data.
DEFAULT_VALID_RESIDENT_IDS = {
    "R01", "R02", "R03", "R04", "R05", "R06", "R07"
}


def clean_text(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    return " ".join(text.split())


def normalise_staff_name(value):
    text = clean_text(value)
    if not text:
        return None

    match = re.fullmatch(r"staff\s*0*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return f"Staff {int(match.group(1)):02d}"

    return text


def normalise_column_name(column_name):
    name = str(column_name).replace("\ufeff", "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def normalise_record(column_names, values):
    return {
        normalise_column_name(column_name): value
        for column_name, value in zip(column_names, values)
    }


def get_value(record, *column_names):
    for column_name in column_names:
        value = record.get(column_name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def to_boolean(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time.min)

    text = clean_text(value)
    formats = (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
    )

    for date_format in formats:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            pass

    raise ValueError(f"Invalid datetime: {text}")


def parse_range_start(value):
    text = clean_text(value)
    if not text:
        return None

    # Appointment bookings arrive as a range; only the start is stored here.
    match = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", text)
    if not match:
        raise ValueError(f"Invalid date/time range: {text}")

    return datetime.strptime(
        f"{match.group(1)} {match.group(2)}", "%d/%m/%Y %H:%M"
    )


def week_start(log_date):
    return log_date - timedelta(days=log_date.weekday())


def get_shift(log_datetime):
    hour = log_datetime.hour

    if 8 <= hour < 21:
        return log_datetime.date(), "Day"

    if hour < 8:
        return log_datetime.date() - timedelta(days=1), "Night"

    return log_datetime.date(), "Night"


def title_suffix(title, prefix):
    title = clean_text(title)
    if not title:
        return None
    if title.startswith(prefix):
        return clean_text(title[len(prefix) :])
    return title


def parse_allowed_values(setting_name):
    setting_value = os.getenv(setting_name, "")
    return {
        value.strip()
        for value in setting_value.split(",")
        if value.strip()
    }


def fetch_bronze_records(connection, source_file, bronze_table):
    # SQL parameters cannot be used for a table name, so restrict its format.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", bronze_table):
        raise ValueError("bronze_table must use the format schema.table")

    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT * FROM {bronze_table} WHERE source_file = ?",
            (source_file,),
        )
        column_names = [column[0] for column in cursor.description]
        return [normalise_record(column_names, row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def prepare_record(record, source_file):
    source_log_id = clean_text(get_value(record, "source_log_id", "id"))
    log_datetime = parse_datetime(get_value(record, "log_datetime", "time_logged"))
    log_date = log_datetime.date()
    shift_date, shift_type = get_shift(log_datetime)

    return {
        "source_log_id": source_log_id,
        "home": clean_text(get_value(record, "home")),
        "home_id": clean_text(get_value(record, "home_id")),
        "resident": clean_text(get_value(record, "resident")),
        "resident_id": clean_text(get_value(record, "resident_id")),
        "category": clean_text(get_value(record, "category")),
        "item": clean_text(get_value(record, "item")),
        "title": clean_text(get_value(record, "title")),
        "description_clean": clean_text(
            get_value(record, "description_clean", "description")
        ),
        "deleted": to_boolean(get_value(record, "deleted")),
        "log_datetime": log_datetime,
        "logged_by": normalise_staff_name(get_value(record, "logged_by")),
        "witnessed_by": normalise_staff_name(get_value(record, "witnessed_by")),
        "edited_by": normalise_staff_name(get_value(record, "edited_by")),
        "edited_at": (
            parse_datetime(get_value(record, "edited_at"))
            if get_value(record, "edited_at")
            else None
        ),
        "amount_1": clean_text(get_value(record, "amount_1")),
        "amount_2": clean_text(get_value(record, "amount_2")),
        "amount_one_key": clean_text(get_value(record, "amount_one_key")),
        "amount_two_key": clean_text(get_value(record, "amount_two_key")),
        "bookmark": to_boolean(get_value(record, "bookmark")),
        "log_date": log_date,
        "shift_date": shift_date,
        "shift_type": shift_type,
        "week_start_date": week_start(log_date),
        "source_file": source_file,
        "ingestion_timestamp": (
            parse_datetime(get_value(record, "ingestion_timestamp"))
            if get_value(record, "ingestion_timestamp")
            else datetime.utcnow()
        ),
    }


def validate_record(record, valid_resident_ids, valid_logged_by):
    errors = []

    for field_name in (
        "source_log_id",
        "resident_id",
        "category",
        "item",
        "log_datetime",
        "logged_by",
    ):
        if not record.get(field_name):
            errors.append(f"Missing {field_name}")

    if valid_resident_ids and record["resident_id"] not in valid_resident_ids:
        errors.append("Unknown resident_id")

    if valid_logged_by and record["logged_by"] not in valid_logged_by:
        errors.append("Unknown logged_by")

    if record["category"] == "Health Visit":
        if record["amount_one_key"] != "appointment_status":
            errors.append("Health Visit is missing appointment_status")
        elif record["amount_1"] not in APPOINTMENT_STATUSES:
            errors.append("Unknown appointment status")
        elif record["amount_1"] in BOOKING_STATUSES:
            if record["amount_two_key"] != "appointment_datetime":
                errors.append("Booking is missing appointment_datetime")
            else:
                try:
                    parse_range_start(record["amount_2"])
                except ValueError as error:
                    errors.append(str(error))

    if record["category"] == "Health Recordings" and record["item"] == "Mood":
        mood_label = title_suffix(record["title"], "Mood -")
        if mood_label not in MOOD_SCORES:
            errors.append("Unknown mood label")

    if record["category"] == "Activities" and record["item"] == "Communication":
        communication_label = title_suffix(record["title"], "Communication -")
        if communication_label not in COMMUNICATION_SCORES:
            errors.append("Unknown communication label")

    if record["category"] == "Incident" and record["item"] not in INCIDENT_TYPES:
        errors.append("Unknown incident type")

    return errors


def make_exception(record, reason, row_number):
    failed_field = "row"
    raw_value = None
    exception_code = "VALIDATION_FAILED"

    if reason.startswith("Missing "):
        failed_field = reason.replace("Missing ", "", 1)
        raw_value = record.get(failed_field)
        exception_code = "MISSING_REQUIRED_VALUE"
    elif reason == "Unknown resident_id":
        failed_field = "resident_id"
        raw_value = record.get("resident_id")
        exception_code = "UNKNOWN_RESIDENT"
    elif reason == "Unknown logged_by":
        failed_field = "logged_by"
        raw_value = record.get("logged_by")
        exception_code = "UNKNOWN_STAFF"
    elif reason == "Health Visit is missing appointment_status":
        failed_field = "amount_one_key"
        raw_value = record.get("amount_one_key")
        exception_code = "MISSING_APPOINTMENT_STATUS"
    elif reason == "Unknown appointment status":
        failed_field = "amount_1"
        raw_value = record.get("amount_1")
        exception_code = "UNMAPPED_APPOINTMENT_STATUS"
    elif reason == "Booking is missing appointment_datetime":
        failed_field = "amount_two_key"
        raw_value = record.get("amount_two_key")
        exception_code = "MISSING_APPOINTMENT_DATETIME"
    elif reason.startswith("Invalid date/time range"):
        failed_field = "amount_2"
        raw_value = record.get("amount_2")
        exception_code = "APPOINTMENT_DATETIME_PARSE_FAILED"
    elif reason == "Unknown mood label":
        failed_field = "title"
        raw_value = record.get("title")
        exception_code = "UNMAPPED_MOOD_VALUE"
    elif reason == "Unknown communication label":
        failed_field = "title"
        raw_value = record.get("title")
        exception_code = "UNMAPPED_COMMUNICATION_VALUE"
    elif reason == "Unknown incident type":
        failed_field = "item"
        raw_value = record.get("item")
        exception_code = "UNMAPPED_INCIDENT_TYPE"

    return {
        "row_number": row_number,
        "source_log_id": record.get("source_log_id"),
        "failed_field": failed_field,
        "raw_value": raw_value,
        "exception_code": exception_code,
        "exception_detail": reason,
    }


def insert_data_exceptions(
    cursor,
    pipeline_run_key,
    source_file,
    exceptions,
):
    if pipeline_run_key is None:
        return

    cursor.execute(
        "DELETE FROM audit.data_exception WHERE pipeline_run_key = ?",
        (pipeline_run_key,),
    )

    for exception in exceptions:
        cursor.execute(
            """
            INSERT INTO audit.data_exception (
                pipeline_run_key,
                source_file,
                source_log_id,
                failed_field,
                raw_value,
                exception_code,
                exception_detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                pipeline_run_key,
                source_file,
                exception.get("source_log_id"),
                exception["failed_field"],
                exception.get("raw_value"),
                exception["exception_code"],
                exception["exception_detail"],
            ),
        )


def table_has_column(cursor, schema_name, table_name, column_name):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
          AND COLUMN_NAME = ?;
        """,
        (schema_name, table_name, column_name),
    )
    return cursor.fetchone()[0] == 1


def update_pipeline_run(cursor, source_file, week_start_date):
    # ADF creates the run first; Silver fills in the cleaning details later.
    cursor.execute(
        """
        UPDATE audit.pipeline_run
        SET
            week_start_date = COALESCE(week_start_date, ?),
            cleaned_at = SYSUTCDATETIME(),
            run_status = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM audit.data_exception
                    WHERE pipeline_run_key = audit.pipeline_run.pipeline_run_key
                )
                THEN N'SucceededWithIssues'
                ELSE N'Succeeded'
            END
        OUTPUT INSERTED.pipeline_run_key
        WHERE pipeline_run_key = (
            SELECT MAX(pipeline_run_key)
            FROM audit.pipeline_run
            WHERE source_file = ?
        );
        """,
        (week_start_date, source_file),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def delete_previous_load(cursor, source_file):
    # Removing the old batch makes a rerun safe instead of duplicating it.
    for table_name in (
        "silver.activity",
        "silver.appointment",
        "silver.communication",
        "silver.incident",
        "silver.medication",
        "silver.mood",
        "silver.staff_shift",
        "silver.log_event",
    ):
        cursor.execute(
            f"DELETE FROM {table_name} WHERE source_file = ?",
            (source_file,),
        )


def delete_typed_silver_load(cursor, source_file):
    for table_name in (
        "silver.activity",
        "silver.appointment",
        "silver.communication",
        "silver.incident",
        "silver.medication",
        "silver.mood",
        "silver.staff_shift",
    ):
        cursor.execute(
            f"DELETE FROM {table_name} WHERE source_file = ?",
            (source_file,),
        )


def insert_log_event(cursor, record):
    cursor.execute(
        """
        INSERT INTO silver.log_event (
            source_log_id,
            home,
            home_id,
            resident,
            resident_id,
            category,
            item,
            title,
            description_clean,
            log_datetime,
            logged_by,
            witnessed_by,
            edited_by,
            edited_at,
            amount_1,
            amount_2,
            amount_one_key,
            amount_two_key,
            bookmark,
            log_date,
            shift_type,
            week_start_date,
            source_file,
            ingestion_timestamp
        )
        OUTPUT INSERTED.log_event_key
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            record["source_log_id"],
            record["home"],
            record["home_id"],
            record["resident"],
            record["resident_id"],
            record["category"],
            record["item"],
            record["title"],
            record["description_clean"],
            record["log_datetime"],
            record["logged_by"],
            record["witnessed_by"],
            record["edited_by"],
            record["edited_at"],
            record["amount_1"],
            record["amount_2"],
            record["amount_one_key"],
            record["amount_two_key"],
            record["bookmark"],
            record["log_date"],
            record["shift_type"],
            record["week_start_date"],
            record["source_file"],
            record["ingestion_timestamp"],
        ),
    )
    return cursor.fetchone()[0]


def insert_activity(cursor, record, log_event_key):
    if record["category"] != "Activities":
        return False

    is_housework = record["item"] == "House Work"
    is_resident_activity = record["item"] in {
        "Resident Activity",
        "Occupational Therapy",
    }

    if not is_housework and not is_resident_activity:
        return False

    if is_housework:
        activity_type = record["amount_2"] or record["title"]
        staff_involved = record["amount_1"] == "You"
    else:
        activity_type = record["title"] or record["item"]
        staff_involved = record["amount_1"] == "Yes"

    cursor.execute(
        """
        INSERT INTO silver.activity (
            log_event_key,
            resident_id,
            activity_type,
            activity_status,
            is_housework,
            staff_involved,
            log_datetime,
            log_date,
            week_start_date,
            logged_by,
            description_clean,
            source_file,
            transformed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
        """,
        (
            log_event_key,
            record["resident_id"],
            activity_type,
            "Completed",
            is_housework,
            staff_involved,
            record["log_datetime"],
            record["log_date"],
            record["week_start_date"],
            record["logged_by"],
            record["description_clean"],
            record["source_file"],
        ),
    )
    return True


def insert_appointment(cursor, record, log_event_key, has_end_column):
    # Bookings and outcomes stay as separate events rather than being matched.
    if record["category"] != "Health Visit":
        return False

    status = record["amount_1"]
    start_datetime = None
    end_datetime = None

    if status in BOOKING_STATUSES:
        start_datetime = parse_range_start(record["amount_2"])
        end_datetime = start_datetime + timedelta(minutes=90)

    supported_by_staff = None
    if status in {"Staff Required", "Completed with Staff"}:
        supported_by_staff = True
    elif status in {"No Staff Required", "Completed without Staff"}:
        supported_by_staff = False

    completed = status in COMPLETED_STATUSES

    if has_end_column:
        cursor.execute(
            """
            INSERT INTO silver.appointment (
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
                week_start_date,
                logged_by,
                description_clean,
                source_file,
                transformed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
            """,
            (
                log_event_key,
                record["resident_id"],
                record["title"] or record["item"],
                status,
                start_datetime,
                end_datetime,
                supported_by_staff,
                completed,
                record["log_datetime"],
                record["log_date"],
                record["week_start_date"],
                record["logged_by"],
                record["description_clean"],
                record["source_file"],
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO silver.appointment (
                log_event_key,
                resident_id,
                appointment_type,
                appointment_status,
                scheduled_datetime,
                supported_by_staff,
                completed,
                log_datetime,
                log_date,
                week_start_date,
                logged_by,
                description_clean,
                source_file,
                transformed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
            """,
            (
                log_event_key,
                record["resident_id"],
                record["title"] or record["item"],
                status,
                start_datetime,
                supported_by_staff,
                completed,
                record["log_datetime"],
                record["log_date"],
                record["week_start_date"],
                record["logged_by"],
                record["description_clean"],
                record["source_file"],
            ),
        )

    return True


def insert_communication(cursor, record, log_event_key):
    if not (
        record["category"] == "Activities"
        and record["item"] == "Communication"
    ):
        return False

    label = title_suffix(record["title"], "Communication -")
    score = COMMUNICATION_SCORES[label]

    cursor.execute(
        """
        INSERT INTO silver.communication (
            log_event_key,
            resident_id,
            communication_label,
            communication_score,
            log_datetime,
            log_date,
            week_start_date,
            shift_type,
            logged_by,
            description_clean,
            bookmark,
            source_file,
            transformed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
        """,
        (
            log_event_key,
            record["resident_id"],
            label,
            score,
            record["log_datetime"],
            record["log_date"],
            record["week_start_date"],
            record["shift_type"],
            record["logged_by"],
            record["description_clean"],
            record["bookmark"],
            record["source_file"],
        ),
    )
    return True


def insert_medication(cursor, record, log_event_key):
    if not (
        record["category"] == "Medication"
        and record["item"] == "Medication Round"
    ):
        return False

    medication_status = (
        record["amount_1"]
        if record["amount_one_key"] == "medication_outcome"
        else None
    )
    medication_round = (
        record["amount_2"]
        if record["amount_two_key"] == "medication_round"
        else None
    )

    cursor.execute(
        """
        INSERT INTO silver.medication (
            log_event_key,
            resident_id,
            medication_name,
            medication_round,
            medication_status,
            refusal_reason,
            log_datetime,
            log_date,
            week_start_date,
            shift_type,
            logged_by,
            description_clean,
            source_file,
            transformed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
        """,
        (
            log_event_key,
            record["resident_id"],
            None,
            medication_round,
            medication_status,
            None,
            record["log_datetime"],
            record["log_date"],
            record["week_start_date"],
            record["shift_type"],
            record["logged_by"],
            record["description_clean"],
            record["source_file"],
        ),
    )
    return True


def insert_mood(cursor, record, log_event_key):
    if not (
        record["category"] == "Health Recordings" and record["item"] == "Mood"
    ):
        return False

    label = title_suffix(record["title"], "Mood -")
    score = MOOD_SCORES[label]

    cursor.execute(
        """
        INSERT INTO silver.mood (
            log_event_key,
            resident_id,
            mood_label,
            mood_score,
            log_datetime,
            log_date,
            week_start_date,
            shift_type,
            logged_by,
            bookmark,
            source_file,
            transformed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
        """,
        (
            log_event_key,
            record["resident_id"],
            label,
            score,
            record["log_datetime"],
            record["log_date"],
            record["week_start_date"],
            record["shift_type"],
            record["logged_by"],
            record["bookmark"],
            record["source_file"],
        ),
    )
    return True


def insert_incident(cursor, record, log_event_key):
    if record["category"] != "Incident":
        return False

    detail_prefix = f'{record["item"]} -'
    incident_detail = title_suffix(record["title"], detail_prefix)

    cursor.execute(
        """
        INSERT INTO silver.incident (
            log_event_key,
            resident_id,
            incident_type,
            incident_detail,
            log_datetime,
            log_date,
            week_start_date,
            shift_type,
            logged_by,
            witnessed_by,
            description_clean,
            bookmark,
            source_file,
            transformed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
        """,
        (
            log_event_key,
            record["resident_id"],
            record["item"],
            incident_detail,
            record["log_datetime"],
            record["log_date"],
            record["week_start_date"],
            record["shift_type"],
            record["logged_by"],
            record["witnessed_by"],
            record["description_clean"],
            record["bookmark"],
            record["source_file"],
        ),
    )
    return True


def insert_staff_shifts(cursor, records, source_file):
    # Group staff logs into the shift in which they were recorded.
    shift_groups = defaultdict(list)

    for record in records:
        key = (
            record["logged_by"],
            record["shift_date"],
            record["shift_type"],
        )
        shift_groups[key].append(record["log_datetime"])

    for (staff_name, shift_date, shift_type), log_times in shift_groups.items():
        cursor.execute(
            """
            INSERT INTO silver.staff_shift (
                staff_name,
                shift_date,
                week_start_date,
                shift_type,
                first_log_datetime,
                last_log_datetime,
                log_count,
                source_file,
                transformed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
            """,
            (
                staff_name,
                shift_date,
                week_start(shift_date),
                shift_type,
                min(log_times),
                max(log_times),
                len(log_times),
                source_file,
            ),
        )

    return len(shift_groups)


def load_bronze_to_log_event(
    connection,
    source_file,
    bronze_table="bronze.care_logs",
    pipeline_run_key=None,
):
    # First Azure Function: Bronze to silver.log_event.
    source_file = clean_text(source_file)
    if not source_file:
        raise ValueError("source_file is required")

    bronze_records = fetch_bronze_records(connection, source_file, bronze_table)
    if not bronze_records:
        raise ValueError(f"No Bronze rows found for {source_file}")

    configured_resident_ids = parse_allowed_values("VALID_RESIDENT_IDS")
    valid_resident_ids = (
        DEFAULT_VALID_RESIDENT_IDS & configured_resident_ids
        if configured_resident_ids
        else DEFAULT_VALID_RESIDENT_IDS
    )
    valid_logged_by = {
        normalise_staff_name(value)
        for value in parse_allowed_values("VALID_LOGGED_BY")
    }

    clean_records = []
    exceptions = []
    seen_source_ids = set()
    deleted_count = 0
    duplicate_count = 0

    for row_number, bronze_record in enumerate(bronze_records, start=1):
        try:
            record = prepare_record(bronze_record, source_file)
        except (TypeError, ValueError) as error:
            normalised_record = normalise_record(
                bronze_record.keys(),
                bronze_record.values(),
            )
            exceptions.append(
                {
                    "row_number": row_number,
                    "source_log_id": clean_text(
                        get_value(normalised_record, "source_log_id", "id")
                    ),
                    "failed_field": "time_logged",
                    "raw_value": get_value(
                        normalised_record,
                        "time_logged",
                        "log_datetime",
                    ),
                    "exception_code": "LOG_TIMESTAMP_PARSE_FAILED",
                    "exception_detail": str(error),
                }
            )
            continue

        if record["deleted"]:
            deleted_count += 1
            continue

        if record["source_log_id"] in seen_source_ids:
            duplicate_count += 1
            continue

        errors = validate_record(record, valid_resident_ids, valid_logged_by)
        if errors:
            for error in errors:
                exceptions.append(make_exception(record, error, row_number))
            continue

        seen_source_ids.add(record["source_log_id"])
        clean_records.append(record)

    cursor = connection.cursor()
    log_event_count = 0

    try:
        # Typed rows use log_event_key, so they must be deleted before their
        # parent events are replaced during a rerun.
        delete_previous_load(cursor, source_file)

        for record in clean_records:
            insert_log_event(cursor, record)
            log_event_count += 1

        insert_data_exceptions(
            cursor,
            pipeline_run_key,
            source_file,
            exceptions,
        )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return {
        "status": "Succeeded",
        "source_file": source_file,
        "rows_received": len(bronze_records),
        "rows_deleted": deleted_count,
        "rows_duplicates": duplicate_count,
        "rows_rejected": len(exceptions),
        "silver_log_event_rows": log_event_count,
        "exceptions": exceptions,
    }


def fetch_log_event_records(connection, source_file):
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT
                log_event_key,
                source_log_id,
                home,
                home_id,
                resident,
                resident_id,
                category,
                item,
                title,
                description_clean,
                log_datetime,
                logged_by,
                witnessed_by,
                edited_by,
                edited_at,
                amount_1,
                amount_2,
                amount_one_key,
                amount_two_key,
                bookmark,
                ingestion_timestamp
            FROM silver.log_event
            WHERE source_file = ?
            ORDER BY log_event_key;
            """,
            (source_file,),
        )
        column_names = [column[0] for column in cursor.description]
        return [normalise_record(column_names, row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def load_log_event_to_silver_tables(connection, source_file):
    # Second Azure Function: silver.log_event to the typed Silver tables.
    source_file = clean_text(source_file)
    if not source_file:
        raise ValueError("source_file is required")

    stored_events = fetch_log_event_records(connection, source_file)
    if not stored_events:
        raise ValueError(f"No silver.log_event rows found for {source_file}")

    records = [prepare_record(event, source_file) for event in stored_events]
    week_start_dates = sorted(
        {record["week_start_date"] for record in records}
    )
    if len(week_start_dates) != 1:
        raise ValueError(
            f"Expected one week_start_date for {source_file}, "
            f"found {week_start_dates}"
        )
    loaded_week_start_date = week_start_dates[0]

    cursor = connection.cursor()
    pipeline_run_key = None
    counts = {
        "activity": 0,
        "appointment": 0,
        "communication": 0,
        "incident": 0,
        "medication": 0,
        "mood": 0,
        "staff_shift": 0,
    }

    try:
        has_end_column = table_has_column(
            cursor,
            "silver",
            "appointment",
            "scheduled_end_datetime",
        )

        delete_typed_silver_load(cursor, source_file)

        for stored_event, record in zip(stored_events, records):
            log_event_key = stored_event["log_event_key"]

            counts["activity"] += int(
                insert_activity(cursor, record, log_event_key)
            )
            counts["appointment"] += int(
                insert_appointment(cursor, record, log_event_key, has_end_column)
            )
            counts["communication"] += int(
                insert_communication(cursor, record, log_event_key)
            )
            counts["incident"] += int(
                insert_incident(cursor, record, log_event_key)
            )
            counts["medication"] += int(
                insert_medication(cursor, record, log_event_key)
            )
            counts["mood"] += int(insert_mood(cursor, record, log_event_key))

        counts["staff_shift"] = insert_staff_shifts(
            cursor,
            records,
            source_file,
        )

        # Do this last so a failed load is not recorded as cleaned.
        pipeline_run_key = update_pipeline_run(
            cursor,
            source_file,
            loaded_week_start_date,
        )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    result = {
        "status": "Succeeded",
        "source_file": source_file,
        "week_start_date": loaded_week_start_date.isoformat(),
        "pipeline_run_key": pipeline_run_key,
        "silver_log_event_rows_read": len(stored_events),
        "silver_table_rows": counts,
        "appointment_end_time_loaded": has_end_column,
    }

    if not has_end_column:
        result["warning"] = (
            "silver.appointment has no scheduled_end_datetime column. "
            "Appointment starts were loaded, but calculated end times were not stored."
        )

    return result


def load_silver_tables(connection, source_file, bronze_table="bronze.care_logs"):
    log_event_result = load_bronze_to_log_event(
        connection,
        source_file,
        bronze_table,
    )
    table_result = load_log_event_to_silver_tables(connection, source_file)

    return {
        **log_event_result,
        "silver_rows": {
            "log_event": log_event_result["silver_log_event_rows"],
            **table_result["silver_table_rows"],
        },
        "appointment_end_time_loaded": table_result[
            "appointment_end_time_loaded"
        ],
    }
