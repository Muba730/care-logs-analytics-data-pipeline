/*
    Care Home Data Engineering Project
    Gold Layer: Fact and Aggregate Tables

    Run the Gold dimension-table script before running this script.
    This script creates nine empty reporting tables.
    It does not insert, update or delete any Bronze or Silver data.
*/

SET NOCOUNT ON;


/*==============================================================
  1. Check that the four dimensions already exist
==============================================================*/

IF OBJECT_ID(N'gold.dim_date', N'U') IS NULL
   OR OBJECT_ID(N'gold.dim_resident', N'U') IS NULL
   OR OBJECT_ID(N'gold.dim_staff', N'U') IS NULL
   OR OBJECT_ID(N'gold.dim_log_type', N'U') IS NULL
BEGIN
    THROW 50001,
          'Create the four Gold dimension tables before the fact tables.',
          1;
END;


/*==============================================================
  2. Daily log-count aggregate

  Grain:
  One row per date, resident, staff member, log type and shift.

  Purpose:
  Counts documentation volume without storing every log again.
==============================================================*/

IF OBJECT_ID(N'gold.agg_log_count_daily', N'U') IS NULL
BEGIN
    CREATE TABLE gold.agg_log_count_daily (
        log_count_key        BIGINT        IDENTITY(1,1) NOT NULL,
        date_key             INT           NOT NULL,
        resident_key         INT           NOT NULL,
        staff_key            INT           NOT NULL,
        log_type_key         INT           NOT NULL,
        shift_type           NVARCHAR(10)  NOT NULL,
        log_count            INT           NOT NULL,
        bookmarked_log_count INT           NOT NULL DEFAULT (0),
        source_file          NVARCHAR(255) NOT NULL,
        created_at           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_agg_log_count_daily
            PRIMARY KEY (log_count_key),

        CONSTRAINT UQ_agg_log_count_daily_grain
            UNIQUE (
                source_file,
                date_key,
                resident_key,
                staff_key,
                log_type_key,
                shift_type
            ),

        CONSTRAINT CK_agg_log_count_daily_shift
            CHECK (shift_type IN (N'Day', N'Night')),

        CONSTRAINT CK_agg_log_count_daily_counts
            CHECK (
                log_count >= 0
                AND bookmarked_log_count >= 0
                AND bookmarked_log_count <= log_count
            ),

        CONSTRAINT FK_agg_log_count_daily_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_agg_log_count_daily_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key),

        CONSTRAINT FK_agg_log_count_daily_staff
            FOREIGN KEY (staff_key)
            REFERENCES gold.dim_staff(staff_key),

        CONSTRAINT FK_agg_log_count_daily_log_type
            FOREIGN KEY (log_type_key)
            REFERENCES gold.dim_log_type(log_type_key)
    );
END;


/*==============================================================
  3. Daily mood fact

  Grain:
  One row per resident per date, including dates with no mood logs.

  Purpose:
  Supports the mood heatmap, missing-log coverage and review flags.
==============================================================*/

IF OBJECT_ID(N'gold.fact_mood_daily', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_mood_daily (
        mood_daily_key       BIGINT        IDENTITY(1,1) NOT NULL,
        date_key             INT           NOT NULL,
        resident_key         INT           NOT NULL,
        mood_log_count       TINYINT       NOT NULL,
        expected_log_count   TINYINT       NOT NULL DEFAULT (3),
        missing_log_count    TINYINT       NOT NULL,
        very_low_count       TINYINT       NOT NULL DEFAULT (0),
        low_count            TINYINT       NOT NULL DEFAULT (0),
        okay_count           TINYINT       NOT NULL DEFAULT (0),
        good_count           TINYINT       NOT NULL DEFAULT (0),
        very_good_count      TINYINT       NOT NULL DEFAULT (0),
        average_mood_score   DECIMAL(4,2)  NULL,
        minimum_mood_score   TINYINT       NULL,
        requires_review      BIT           NOT NULL DEFAULT (0),
        source_file          NVARCHAR(255) NOT NULL,
        created_at           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_mood_daily
            PRIMARY KEY (mood_daily_key),

        CONSTRAINT UQ_fact_mood_daily_grain
            UNIQUE (source_file, date_key, resident_key),

        CONSTRAINT CK_fact_mood_daily_counts
            CHECK (
                mood_log_count >= 0
                AND expected_log_count = 3
                AND missing_log_count >= 0
                AND very_low_count
                    + low_count
                    + okay_count
                    + good_count
                    + very_good_count = mood_log_count
            ),

        CONSTRAINT CK_fact_mood_daily_average
            CHECK (
                average_mood_score IS NULL
                OR average_mood_score BETWEEN 1 AND 5
            ),

        CONSTRAINT CK_fact_mood_daily_minimum
            CHECK (
                minimum_mood_score IS NULL
                OR minimum_mood_score BETWEEN 1 AND 5
            ),

        CONSTRAINT FK_fact_mood_daily_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_mood_daily_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key)
    );
END;


/*==============================================================
  4. Daily communication fact

  Grain:
  One row per resident per date, including dates with no logs.

  Communication scores:
  1 = No response, 2 = Minimal, 3 = Normal, 4 = Expansive.
==============================================================*/

IF OBJECT_ID(N'gold.fact_communication', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_communication (
        communication_key      BIGINT        IDENTITY(1,1) NOT NULL,
        date_key               INT           NOT NULL,
        resident_key           INT           NOT NULL,
        day_log_count          TINYINT       NOT NULL,
        night_log_count        TINYINT       NOT NULL,
        total_log_count        TINYINT       NOT NULL,
        expected_log_count     TINYINT       NOT NULL DEFAULT (3),
        missing_log_count      TINYINT       NOT NULL,
        no_response_count      TINYINT       NOT NULL DEFAULT (0),
        minimal_count          TINYINT       NOT NULL DEFAULT (0),
        normal_count           TINYINT       NOT NULL DEFAULT (0),
        expansive_count        TINYINT       NOT NULL DEFAULT (0),
        average_communication  DECIMAL(4,2)  NULL,
        requires_review        BIT           NOT NULL DEFAULT (0),
        source_file            NVARCHAR(255) NOT NULL,
        created_at             DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_communication
            PRIMARY KEY (communication_key),

        CONSTRAINT UQ_fact_communication_grain
            UNIQUE (source_file, date_key, resident_key),

        CONSTRAINT CK_fact_communication_counts
            CHECK (
                day_log_count >= 0
                AND night_log_count >= 0
                AND total_log_count = day_log_count + night_log_count
                AND expected_log_count = 3
                AND missing_log_count >= 0
                AND no_response_count
                    + minimal_count
                    + normal_count
                    + expansive_count = total_log_count
            ),

        CONSTRAINT CK_fact_communication_average
            CHECK (
                average_communication IS NULL
                OR average_communication BETWEEN 1 AND 4
            ),

        CONSTRAINT FK_fact_communication_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_communication_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key)
    );
END;


/*==============================================================
  5. Weekly medication fact

  Grain:
  One row per resident per reporting week.

  Purpose:
  Compares weekly medication taken with the resident's own baseline.
==============================================================*/

IF OBJECT_ID(N'gold.fact_medication', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_medication (
        medication_key          BIGINT        IDENTITY(1,1) NOT NULL,
        week_start_date_key      INT           NOT NULL,
        resident_key            INT           NOT NULL,
        total_dose_count        INT           NOT NULL,
        accepted_dose_count     INT           NOT NULL,
        refused_dose_count      INT           NOT NULL,
        prn_dose_count          INT           NOT NULL DEFAULT (0),
        has_baseline            BIT           NOT NULL DEFAULT (0),
        baseline_median_doses   DECIMAL(8,2)  NULL,
        percentage_of_baseline  DECIMAL(6,2)  NULL,
        requires_review         BIT           NOT NULL DEFAULT (0),
        source_file             NVARCHAR(255) NOT NULL,
        created_at              DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_medication
            PRIMARY KEY (medication_key),

        CONSTRAINT UQ_fact_medication_grain
            UNIQUE (source_file, week_start_date_key, resident_key),

        CONSTRAINT CK_fact_medication_counts
            CHECK (
                total_dose_count >= 0
                AND accepted_dose_count >= 0
                AND refused_dose_count >= 0
                AND prn_dose_count >= 0
                AND accepted_dose_count + refused_dose_count
                    = total_dose_count
                AND prn_dose_count <= total_dose_count
            ),

        CONSTRAINT CK_fact_medication_baseline
            CHECK (
                (has_baseline = 0
                    AND baseline_median_doses IS NULL
                    AND percentage_of_baseline IS NULL)
                OR
                (has_baseline = 1
                    AND baseline_median_doses IS NOT NULL
                    AND percentage_of_baseline IS NOT NULL)
            ),

        CONSTRAINT FK_fact_medication_week
            FOREIGN KEY (week_start_date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_medication_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key)
    );
END;


/*==============================================================
  6. Appointment fact

  Grain:
  One row per Silver appointment log event. Booking and outcome rows remain
  separate and are not matched together.
==============================================================*/

IF OBJECT_ID(N'gold.fact_appointment', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_appointment (
        appointment_key          BIGINT         IDENTITY(1,1) NOT NULL,
        appointment_date_key     INT            NOT NULL,
        resident_key             INT            NOT NULL,
        appointment_type         NVARCHAR(250)  NOT NULL,
        appointment_status       NVARCHAR(50)   NOT NULL,
        scheduled_start_datetime DATETIME2      NULL,
        scheduled_end_datetime   DATETIME2      NULL,
        staff_required           BIT            NULL,
        completed                BIT            NOT NULL,
        has_conflict             BIT            NOT NULL DEFAULT (0),
        source_log_event_key     BIGINT         NOT NULL,
        source_file              NVARCHAR(255)  NOT NULL,
        created_at               DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_appointment
            PRIMARY KEY (appointment_key),

        CONSTRAINT UQ_fact_appointment_grain
            UNIQUE (
                source_file,
                source_log_event_key
            ),

        CONSTRAINT CK_fact_appointment_time
            CHECK (
                (
                    scheduled_start_datetime IS NULL
                    AND scheduled_end_datetime IS NULL
                )
                OR (
                    scheduled_start_datetime IS NOT NULL
                    AND scheduled_end_datetime IS NOT NULL
                    AND scheduled_end_datetime > scheduled_start_datetime
                )
            ),

        CONSTRAINT FK_fact_appointment_date
            FOREIGN KEY (appointment_date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_appointment_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key)
    );
END;


/*==============================================================
  7. Staff shift fact

  Grain:
  One observed staff shift per staff member, date and shift type.

  Shifts are derived from log timestamps rather than a rota file.
==============================================================*/

IF OBJECT_ID(N'gold.fact_staff_shift', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_staff_shift (
        staff_shift_key    BIGINT        IDENTITY(1,1) NOT NULL,
        date_key           INT           NOT NULL,
        staff_key          INT           NOT NULL,
        shift_type         NVARCHAR(10)  NOT NULL,
        first_log_datetime DATETIME2     NOT NULL,
        last_log_datetime  DATETIME2     NOT NULL,
        log_count          INT           NOT NULL,
        resident_count     INT           NOT NULL,
        source_file        NVARCHAR(255) NOT NULL,
        created_at         DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_staff_shift
            PRIMARY KEY (staff_shift_key),

        CONSTRAINT UQ_fact_staff_shift_grain
            UNIQUE (source_file, date_key, staff_key, shift_type),

        CONSTRAINT CK_fact_staff_shift_type
            CHECK (shift_type IN (N'Day', N'Night')),

        CONSTRAINT CK_fact_staff_shift_values
            CHECK (
                last_log_datetime >= first_log_datetime
                AND log_count >= 1
                AND resident_count >= 1
            ),

        CONSTRAINT FK_fact_staff_shift_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_staff_shift_staff
            FOREIGN KEY (staff_key)
            REFERENCES gold.dim_staff(staff_key)
    );
END;


/*==============================================================
  8. Staff involvement fact

  Grain:
  One completed staff-involvement event.

  Types:
  Appointment Escort, Resident Activity or Cleaning Task.
==============================================================*/

IF OBJECT_ID(N'gold.fact_staff_involvement', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_staff_involvement (
        involvement_key       BIGINT         IDENTITY(1,1) NOT NULL,
        date_key              INT            NOT NULL,
        resident_key          INT            NOT NULL,
        staff_key             INT            NOT NULL,
        involvement_type      NVARCHAR(30)   NOT NULL,
        involvement_detail    NVARCHAR(255)  NULL,
        source_log_event_key  BIGINT         NOT NULL,
        source_file           NVARCHAR(255)  NOT NULL,
        created_at            DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_staff_involvement
            PRIMARY KEY (involvement_key),

        CONSTRAINT UQ_fact_staff_involvement_event
            UNIQUE (
                source_file,
                source_log_event_key,
                involvement_type,
                staff_key
            ),

        CONSTRAINT CK_fact_staff_involvement_type
            CHECK (
                involvement_type IN (
                    N'Appointment Escort',
                    N'Resident Activity',
                    N'Cleaning Task'
                )
            ),

        CONSTRAINT FK_fact_staff_involvement_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_staff_involvement_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key),

        CONSTRAINT FK_fact_staff_involvement_staff
            FOREIGN KEY (staff_key)
            REFERENCES gold.dim_staff(staff_key)
    );
END;


/*==============================================================
  9. Incident fact

  Grain:
  One row per validated Silver incident event.
==============================================================*/

IF OBJECT_ID(N'gold.fact_incident', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_incident (
        incident_key         BIGINT         IDENTITY(1,1) NOT NULL,
        date_key             INT            NOT NULL,
        resident_key         INT            NOT NULL,
        staff_key            INT            NOT NULL,
        incident_type        NVARCHAR(100)  NOT NULL,
        incident_detail      NVARCHAR(250)  NULL,
        incident_datetime    DATETIME2      NOT NULL,
        shift_type           NVARCHAR(10)   NOT NULL,
        witnessed_by         NVARCHAR(100)  NULL,
        description_clean    NVARCHAR(MAX)  NULL,
        bookmarked           BIT            NOT NULL DEFAULT (0),
        source_log_event_key BIGINT         NOT NULL,
        source_file          NVARCHAR(255)  NOT NULL,
        created_at           DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_incident
            PRIMARY KEY (incident_key),

        CONSTRAINT UQ_fact_incident_source_event
            UNIQUE (source_file, source_log_event_key),

        CONSTRAINT CK_fact_incident_type
            CHECK (incident_type IN (
                N'Negative Behaviour', N'Self-Harm Concern', N'Fall',
                N'Assault', N'Missing Person', N'Other'
            )),

        CONSTRAINT CK_fact_incident_shift
            CHECK (shift_type IN (N'Day', N'Night')),

        CONSTRAINT FK_fact_incident_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_incident_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key),

        CONSTRAINT FK_fact_incident_staff
            FOREIGN KEY (staff_key)
            REFERENCES gold.dim_staff(staff_key)
    );

    CREATE INDEX IX_fact_incident_source_date_resident
        ON gold.fact_incident (source_file, date_key, resident_key);
END;


/*==============================================================
  10. Flagged-log fact

  Grain:
  One manually bookmarked Silver log event.

  This table supplies the Important Logs and Action Queue panels.
==============================================================*/

IF OBJECT_ID(N'gold.fact_flagged_log', N'U') IS NULL
BEGIN
    CREATE TABLE gold.fact_flagged_log (
        flagged_log_key      BIGINT         IDENTITY(1,1) NOT NULL,
        date_key             INT            NOT NULL,
        resident_key         INT            NOT NULL,
        staff_key            INT            NOT NULL,
        log_type_key         INT            NOT NULL,
        source_log_event_key BIGINT         NOT NULL,
        logged_at            DATETIME2      NOT NULL,
        shift_type           NVARCHAR(10)   NOT NULL,
        title                NVARCHAR(250)  NULL,
        description_clean    NVARCHAR(MAX)  NULL,
        source_file          NVARCHAR(255)  NOT NULL,
        created_at           DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_fact_flagged_log
            PRIMARY KEY (flagged_log_key),

        CONSTRAINT UQ_fact_flagged_log_event
            UNIQUE (source_file, source_log_event_key),

        CONSTRAINT CK_fact_flagged_log_shift
            CHECK (shift_type IN (N'Day', N'Night')),

        CONSTRAINT FK_fact_flagged_log_date
            FOREIGN KEY (date_key)
            REFERENCES gold.dim_date(date_key),

        CONSTRAINT FK_fact_flagged_log_resident
            FOREIGN KEY (resident_key)
            REFERENCES gold.dim_resident(resident_key),

        CONSTRAINT FK_fact_flagged_log_staff
            FOREIGN KEY (staff_key)
            REFERENCES gold.dim_staff(staff_key),

        CONSTRAINT FK_fact_flagged_log_log_type
            FOREIGN KEY (log_type_key)
            REFERENCES gold.dim_log_type(log_type_key)
    );
END;


/*==============================================================
  11. Check all Gold tables
==============================================================*/

SELECT
    s.name AS schema_name,
    t.name AS table_name,
    SUM(p.rows) AS row_count
FROM sys.tables AS t
JOIN sys.schemas AS s
    ON s.schema_id = t.schema_id
LEFT JOIN sys.partitions AS p
    ON p.object_id = t.object_id
   AND p.index_id IN (0, 1)
WHERE s.name = N'gold'
GROUP BY
    s.name,
    t.name
ORDER BY
    t.name;
