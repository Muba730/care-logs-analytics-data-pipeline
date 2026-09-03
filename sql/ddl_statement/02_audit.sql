/* Pipeline-run audit and validation-exception objects. */

SET NOCOUNT ON;

IF SCHEMA_ID(N'audit') IS NULL
    EXEC(N'CREATE SCHEMA audit');
GO

/* One row is created each time a source file is processed. */
IF OBJECT_ID(N'audit.pipeline_run', N'U') IS NULL
BEGIN
    CREATE TABLE audit.pipeline_run (
        pipeline_run_key   BIGINT         IDENTITY(1,1) NOT NULL,
        source_file        NVARCHAR(255)  NOT NULL,
        week_start_date    DATE           NULL,
        rows_received      INT            NOT NULL,
        cleaned_at         DATETIME2      NULL,
        run_status         NVARCHAR(30)   NOT NULL,
        is_reload          BIT            NOT NULL DEFAULT (0),
        created_timestamp  DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_pipeline_run
            PRIMARY KEY (pipeline_run_key)
    );

    CREATE INDEX IX_pipeline_run_source_file
        ON audit.pipeline_run (source_file, pipeline_run_key DESC);
END;
GO

/* Validation failures are written here by the Bronze-to-Silver function. */
IF OBJECT_ID(N'audit.data_exception', N'U') IS NULL
BEGIN
    CREATE TABLE audit.data_exception (
        exception_id       BIGINT         IDENTITY(1,1) NOT NULL,
        pipeline_run_key   BIGINT         NOT NULL,
        source_file        NVARCHAR(255)  NOT NULL,
        source_log_id      NVARCHAR(50)   NULL,
        failed_field       NVARCHAR(128)  NOT NULL,
        raw_value          NVARCHAR(MAX)  NULL,
        exception_code     NVARCHAR(100)  NOT NULL,
        exception_detail   NVARCHAR(500)  NULL,
        detected_at        DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_data_exception
            PRIMARY KEY (exception_id),

        CONSTRAINT FK_data_exception_pipeline_run
            FOREIGN KEY (pipeline_run_key)
            REFERENCES audit.pipeline_run(pipeline_run_key)
    );

    CREATE INDEX IX_data_exception_source_file
        ON audit.data_exception (source_file, source_log_id);

    CREATE INDEX IX_data_exception_pipeline_run
        ON audit.data_exception (pipeline_run_key);
END;
GO

/* Called by ADF after the weekly file has been copied into Bronze. */
CREATE OR ALTER PROCEDURE audit.log_pipeline_run
    @source_file    NVARCHAR(255),
    @rows_received  INT,
    @run_status     NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @is_reload BIT =
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM audit.pipeline_run
                WHERE source_file = @source_file
            )
            THEN 1
            ELSE 0
        END;

    DECLARE @week_start_date DATE =
        TRY_CONVERT(DATE, SUBSTRING(@source_file, 6, 10), 23);

    INSERT INTO audit.pipeline_run (
        source_file,
        week_start_date,
        rows_received,
        run_status,
        is_reload
    )
    VALUES (
        @source_file,
        @week_start_date,
        @rows_received,
        @run_status,
        @is_reload
    );
END;
GO
