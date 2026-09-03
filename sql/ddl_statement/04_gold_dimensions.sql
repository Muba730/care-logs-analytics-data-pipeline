/*
    Care Home Data Engineering Project
    Gold Layer: Schema and Dimension Tables

    This script creates the Gold schema and four dimension tables.
    The IF checks make the script safe to run more than once.
    No Bronze or Silver data is changed by this script.
*/

-- Stop SQL Server from returning a message after every statement.
SET NOCOUNT ON;


/*==============================================================
  1. Create the Gold schema
==============================================================*/

IF NOT EXISTS (
    SELECT 1
    FROM sys.schemas
    WHERE name = N'gold'
)
BEGIN
    EXEC(N'CREATE SCHEMA gold');
END;


/*==============================================================
  2. Date dimension

  One row will represent one calendar date.
  date_key will use the YYYYMMDD format, for example 20250105.
==============================================================*/

IF OBJECT_ID(N'gold.dim_date', N'U') IS NULL
BEGIN
    CREATE TABLE gold.dim_date (
        date_key               INT          NOT NULL,
        full_date              DATE         NOT NULL,
        day_name               NVARCHAR(10) NOT NULL,
        day_of_week_number     TINYINT      NOT NULL,
        is_weekend             BIT          NOT NULL,
        week_start_date        DATE         NOT NULL,
        week_end_date          DATE         NOT NULL,
        iso_week_number        TINYINT      NOT NULL,
        reporting_week_number  TINYINT      NULL,
        month_number           TINYINT      NOT NULL,
        month_name             NVARCHAR(10) NOT NULL,
        quarter_number         TINYINT      NOT NULL,
        calendar_year          SMALLINT     NOT NULL,
        created_at             DATETIME2    NOT NULL
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_dim_date
            PRIMARY KEY (date_key),

        CONSTRAINT UQ_dim_date_full_date
            UNIQUE (full_date)
    );
END;


/*==============================================================
  3. Resident dimension

  One row will represent one resident.
  resident_key is the warehouse key used by the Gold fact tables.
==============================================================*/

IF OBJECT_ID(N'gold.dim_resident', N'U') IS NULL
BEGIN
    CREATE TABLE gold.dim_resident (
        resident_key    INT           IDENTITY(1,1) NOT NULL,
        resident_id     NVARCHAR(50)  NOT NULL,
        resident_name   NVARCHAR(100) NOT NULL,
        is_active       BIT           NOT NULL DEFAULT (1),
        created_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_dim_resident
            PRIMARY KEY (resident_key),

        CONSTRAINT UQ_dim_resident_resident_id
            UNIQUE (resident_id)
    );
END;


/*==============================================================
  4. Staff dimension

  This table will contain Manager 01 and Staff 01 to Staff 05.
  is_support_worker lets us exclude the manager from staff rankings.
==============================================================*/

IF OBJECT_ID(N'gold.dim_staff', N'U') IS NULL
BEGIN
    CREATE TABLE gold.dim_staff (
        staff_key          INT          IDENTITY(1,1) NOT NULL,
        staff_id           NVARCHAR(50) NOT NULL,
        staff_role         NVARCHAR(30) NOT NULL,
        is_support_worker  BIT          NOT NULL,
        is_active          BIT          NOT NULL DEFAULT (1),
        created_at         DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_dim_staff
            PRIMARY KEY (staff_key),

        CONSTRAINT UQ_dim_staff_staff_id
            UNIQUE (staff_id),

        CONSTRAINT CK_dim_staff_role
            CHECK (staff_role IN (N'Manager', N'Support Worker'))
    );
END;


/*==============================================================
  5. Log type dimension

  Each valid Category and Item combination will have one row.
  Unexpected combinations will continue to be handled by validation.
==============================================================*/

IF OBJECT_ID(N'gold.dim_log_type', N'U') IS NULL
BEGIN
    CREATE TABLE gold.dim_log_type (
        log_type_key  INT            IDENTITY(1,1) NOT NULL,
        category      NVARCHAR(100)  NOT NULL,
        item          NVARCHAR(150)  NOT NULL,
        log_type_name NVARCHAR(255)  NOT NULL,
        is_active     BIT            NOT NULL DEFAULT (1),
        created_at    DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_dim_log_type
            PRIMARY KEY (log_type_key),

        CONSTRAINT UQ_dim_log_type_category_item
            UNIQUE (category, item)
    );
END;


/*==============================================================
  6. Check that the tables were created
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
