/* Raw care-log records loaded by the ADF Copy Data activity. */

SET NOCOUNT ON;

IF SCHEMA_ID(N'bronze') IS NULL
    EXEC(N'CREATE SCHEMA bronze');
GO

IF OBJECT_ID(N'bronze.care_logs', N'U') IS NULL
BEGIN
    CREATE TABLE bronze.care_logs (
        bronze_log_key        BIGINT         IDENTITY(1,1) NOT NULL,
        source_log_id         NVARCHAR(50)   NULL,
        home                  NVARCHAR(100)  NULL,
        home_id               NVARCHAR(50)   NULL,
        resident              NVARCHAR(100)  NULL,
        resident_id           NVARCHAR(50)   NULL,
        category              NVARCHAR(100)  NULL,
        item                  NVARCHAR(150)  NULL,
        title                 NVARCHAR(250)  NULL,
        description           NVARCHAR(MAX)  NULL,
        deleted               NVARCHAR(20)   NULL,
        time_logged           NVARCHAR(50)   NULL,
        logged_by             NVARCHAR(100)  NULL,
        witnessed_by          NVARCHAR(100)  NULL,
        edited_by             NVARCHAR(100)  NULL,
        edited_at             NVARCHAR(50)   NULL,
        amount_1              NVARCHAR(100)  NULL,
        amount_2              NVARCHAR(100)  NULL,
        amount_one_key        NVARCHAR(100)  NULL,
        amount_two_key        NVARCHAR(100)  NULL,
        bookmark              NVARCHAR(20)   NULL,
        source_file           NVARCHAR(255)  NOT NULL,
        ingestion_timestamp   DATETIME2      NOT NULL
            CONSTRAINT DF_bronze_care_logs_ingestion_timestamp
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_bronze_care_logs
            PRIMARY KEY (bronze_log_key)
    );

    CREATE INDEX IX_bronze_care_logs_source_file
        ON bronze.care_logs (source_file);

    CREATE INDEX IX_bronze_care_logs_source_log_id
        ON bronze.care_logs (source_log_id);
END;
GO
