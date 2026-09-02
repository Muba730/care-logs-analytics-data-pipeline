/* Validated canonical events and typed Silver tables. */

IF SCHEMA_ID(N'silver') IS NULL
    EXEC(N'CREATE SCHEMA silver');
GO

IF OBJECT_ID(N'silver.log_event', N'U') IS NULL
BEGIN
    CREATE TABLE silver.log_event (
        log_event_key        BIGINT         IDENTITY(1,1) NOT NULL,
        source_log_id        NVARCHAR(50)   NOT NULL,
        home                 NVARCHAR(100)  NULL,
        home_id              NVARCHAR(50)   NULL,
        resident             NVARCHAR(100)  NULL,
        resident_id          NVARCHAR(50)   NOT NULL,
        category             NVARCHAR(100)  NOT NULL,
        item                 NVARCHAR(150)  NOT NULL,
        title                NVARCHAR(250)  NULL,
        description_clean    NVARCHAR(MAX)  NULL,
        log_datetime         DATETIME2      NOT NULL,
        logged_by            NVARCHAR(100)  NOT NULL,
        witnessed_by         NVARCHAR(100)  NULL,
        edited_by            NVARCHAR(100)  NULL,
        edited_at            DATETIME2      NULL,
        amount_1             NVARCHAR(100)  NULL,
        amount_2             NVARCHAR(100)  NULL,
        amount_one_key       NVARCHAR(100)  NULL,
        amount_two_key       NVARCHAR(100)  NULL,
        bookmark             BIT            NOT NULL DEFAULT (0),
        log_date             DATE           NOT NULL,
        shift_type           NVARCHAR(10)   NOT NULL,
        week_start_date      DATE           NOT NULL,
        source_file          NVARCHAR(255)  NOT NULL,
        ingestion_timestamp  DATETIME2      NOT NULL,

        CONSTRAINT PK_silver_log_event
            PRIMARY KEY (log_event_key),

        CONSTRAINT UQ_silver_log_event_source
            UNIQUE (source_file, source_log_id),

        CONSTRAINT CK_silver_log_event_shift
            CHECK (shift_type IN (N'Day', N'Night'))
    );

    CREATE INDEX IX_silver_log_event_source_date
        ON silver.log_event (source_file, log_date, resident_id);
END;
GO

IF OBJECT_ID(N'silver.activity', N'U') IS NULL
BEGIN
    CREATE TABLE silver.activity (
        activity_key       BIGINT         IDENTITY(1,1) NOT NULL,
        log_event_key      BIGINT         NOT NULL,
        resident_id        NVARCHAR(50)   NOT NULL,
        activity_type      NVARCHAR(250)  NULL,
        activity_status    NVARCHAR(30)   NOT NULL,
        is_housework       BIT            NOT NULL,
        staff_involved     BIT            NOT NULL,
        log_datetime       DATETIME2      NOT NULL,
        log_date           DATE           NOT NULL,
        week_start_date    DATE           NOT NULL,
        logged_by          NVARCHAR(100)  NOT NULL,
        description_clean  NVARCHAR(MAX)  NULL,
        source_file        NVARCHAR(255)  NOT NULL,
        transformed_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_activity PRIMARY KEY (activity_key),
        CONSTRAINT UQ_silver_activity_event UNIQUE (log_event_key),
        CONSTRAINT FK_silver_activity_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.appointment', N'U') IS NULL
BEGIN
    CREATE TABLE silver.appointment (
        appointment_key          BIGINT         IDENTITY(1,1) NOT NULL,
        log_event_key            BIGINT         NOT NULL,
        resident_id              NVARCHAR(50)   NOT NULL,
        appointment_type         NVARCHAR(250)  NOT NULL,
        appointment_status       NVARCHAR(50)   NOT NULL,
        scheduled_datetime       DATETIME2      NULL,
        scheduled_end_datetime   DATETIME2      NULL,
        supported_by_staff       BIT            NULL,
        completed                BIT            NOT NULL,
        log_datetime             DATETIME2      NOT NULL,
        log_date                 DATE           NOT NULL,
        week_start_date          DATE           NOT NULL,
        logged_by                NVARCHAR(100)  NOT NULL,
        description_clean        NVARCHAR(MAX)  NULL,
        source_file              NVARCHAR(255)  NOT NULL,
        transformed_at           DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_appointment PRIMARY KEY (appointment_key),
        CONSTRAINT UQ_silver_appointment_event UNIQUE (log_event_key),
        CONSTRAINT CK_silver_appointment_time CHECK (
            (scheduled_datetime IS NULL AND scheduled_end_datetime IS NULL)
            OR (
                scheduled_datetime IS NOT NULL
                AND scheduled_end_datetime IS NOT NULL
                AND scheduled_end_datetime > scheduled_datetime
            )
        ),
        CONSTRAINT FK_silver_appointment_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.communication', N'U') IS NULL
BEGIN
    CREATE TABLE silver.communication (
        communication_key     BIGINT         IDENTITY(1,1) NOT NULL,
        log_event_key         BIGINT         NOT NULL,
        resident_id           NVARCHAR(50)   NOT NULL,
        communication_label   NVARCHAR(50)   NOT NULL,
        communication_score   TINYINT        NOT NULL,
        log_datetime          DATETIME2      NOT NULL,
        log_date              DATE           NOT NULL,
        week_start_date       DATE           NOT NULL,
        shift_type            NVARCHAR(10)   NOT NULL,
        logged_by             NVARCHAR(100)  NOT NULL,
        description_clean     NVARCHAR(MAX)  NULL,
        bookmark              BIT            NOT NULL,
        source_file           NVARCHAR(255)  NOT NULL,
        transformed_at        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_communication PRIMARY KEY (communication_key),
        CONSTRAINT UQ_silver_communication_event UNIQUE (log_event_key),
        CONSTRAINT CK_silver_communication_score
            CHECK (communication_score BETWEEN 1 AND 4),
        CONSTRAINT CK_silver_communication_shift
            CHECK (shift_type IN (N'Day', N'Night')),
        CONSTRAINT FK_silver_communication_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.medication', N'U') IS NULL
BEGIN
    CREATE TABLE silver.medication (
        medication_event_key BIGINT        IDENTITY(1,1) NOT NULL,
        log_event_key       BIGINT         NOT NULL,
        resident_id         NVARCHAR(50)   NOT NULL,
        medication_name     NVARCHAR(150)  NULL,
        medication_round    NVARCHAR(50)   NULL,
        medication_status   NVARCHAR(30)   NULL,
        refusal_reason      NVARCHAR(500)  NULL,
        log_datetime        DATETIME2      NOT NULL,
        log_date            DATE           NOT NULL,
        week_start_date     DATE           NOT NULL,
        shift_type          NVARCHAR(10)   NOT NULL,
        logged_by           NVARCHAR(100)  NOT NULL,
        description_clean   NVARCHAR(MAX)  NULL,
        source_file         NVARCHAR(255)  NOT NULL,
        transformed_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_medication PRIMARY KEY (medication_event_key),
        CONSTRAINT UQ_silver_medication_event UNIQUE (log_event_key),
        CONSTRAINT CK_silver_medication_status
            CHECK (medication_status IS NULL OR medication_status IN (N'Accepted', N'Refused')),
        CONSTRAINT CK_silver_medication_shift
            CHECK (shift_type IN (N'Day', N'Night')),
        CONSTRAINT FK_silver_medication_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.mood', N'U') IS NULL
BEGIN
    CREATE TABLE silver.mood (
        mood_event_key    BIGINT         IDENTITY(1,1) NOT NULL,
        log_event_key     BIGINT         NOT NULL,
        resident_id       NVARCHAR(50)   NOT NULL,
        mood_label        NVARCHAR(50)   NOT NULL,
        mood_score        TINYINT        NOT NULL,
        log_datetime      DATETIME2      NOT NULL,
        log_date          DATE           NOT NULL,
        week_start_date   DATE           NOT NULL,
        shift_type        NVARCHAR(10)   NOT NULL,
        logged_by         NVARCHAR(100)  NOT NULL,
        bookmark          BIT            NOT NULL,
        source_file       NVARCHAR(255)  NOT NULL,
        transformed_at    DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_mood PRIMARY KEY (mood_event_key),
        CONSTRAINT UQ_silver_mood_event UNIQUE (log_event_key),
        CONSTRAINT CK_silver_mood_score CHECK (mood_score BETWEEN 1 AND 5),
        CONSTRAINT CK_silver_mood_shift CHECK (shift_type IN (N'Day', N'Night')),
        CONSTRAINT FK_silver_mood_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.incident', N'U') IS NULL
BEGIN
    CREATE TABLE silver.incident (
        incident_key       BIGINT         IDENTITY(1,1) NOT NULL,
        log_event_key      BIGINT         NOT NULL,
        resident_id        NVARCHAR(50)   NOT NULL,
        incident_type      NVARCHAR(100)  NOT NULL,
        incident_detail    NVARCHAR(250)  NULL,
        log_datetime       DATETIME2      NOT NULL,
        log_date           DATE           NOT NULL,
        week_start_date    DATE           NOT NULL,
        shift_type         NVARCHAR(10)   NOT NULL,
        logged_by          NVARCHAR(100)  NOT NULL,
        witnessed_by       NVARCHAR(100)  NULL,
        description_clean  NVARCHAR(MAX)  NULL,
        bookmark           BIT            NOT NULL,
        source_file        NVARCHAR(255)  NOT NULL,
        transformed_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_incident PRIMARY KEY (incident_key),
        CONSTRAINT UQ_silver_incident_event UNIQUE (log_event_key),
        CONSTRAINT CK_silver_incident_type CHECK (incident_type IN (
            N'Negative Behaviour', N'Self-Harm Concern', N'Fall',
            N'Assault', N'Missing Person', N'Other'
        )),
        CONSTRAINT CK_silver_incident_shift CHECK (shift_type IN (N'Day', N'Night')),
        CONSTRAINT FK_silver_incident_event FOREIGN KEY (log_event_key)
            REFERENCES silver.log_event(log_event_key)
    );
END;
GO

IF OBJECT_ID(N'silver.staff_shift', N'U') IS NULL
BEGIN
    CREATE TABLE silver.staff_shift (
        staff_shift_key     BIGINT         IDENTITY(1,1) NOT NULL,
        staff_name          NVARCHAR(100)  NOT NULL,
        shift_date          DATE           NOT NULL,
        week_start_date     DATE           NOT NULL,
        shift_type          NVARCHAR(10)   NOT NULL,
        first_log_datetime  DATETIME2      NOT NULL,
        last_log_datetime   DATETIME2      NOT NULL,
        log_count           INT            NOT NULL,
        source_file         NVARCHAR(255)  NOT NULL,
        transformed_at      DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_silver_staff_shift PRIMARY KEY (staff_shift_key),
        CONSTRAINT UQ_silver_staff_shift_grain
            UNIQUE (source_file, staff_name, shift_date, shift_type),
        CONSTRAINT CK_silver_staff_shift_type
            CHECK (shift_type IN (N'Day', N'Night')),
        CONSTRAINT CK_silver_staff_shift_values
            CHECK (last_log_datetime >= first_log_datetime AND log_count >= 1)
    );
END;
GO
