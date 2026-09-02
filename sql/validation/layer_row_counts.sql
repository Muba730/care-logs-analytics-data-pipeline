/* Row-count check for the completed medallion pipeline. */

SET NOCOUNT ON;

SELECT N'bronze.care_logs' AS table_name, COUNT_BIG(*) AS row_count
FROM bronze.care_logs
UNION ALL
SELECT N'audit.pipeline_run', COUNT_BIG(*) FROM audit.pipeline_run
UNION ALL
SELECT N'audit.data_exception', COUNT_BIG(*) FROM audit.data_exception
UNION ALL
SELECT N'silver.log_event', COUNT_BIG(*) FROM silver.log_event
UNION ALL
SELECT N'silver.activity', COUNT_BIG(*) FROM silver.activity
UNION ALL
SELECT N'silver.appointment', COUNT_BIG(*) FROM silver.appointment
UNION ALL
SELECT N'silver.communication', COUNT_BIG(*) FROM silver.communication
UNION ALL
SELECT N'silver.medication', COUNT_BIG(*) FROM silver.medication
UNION ALL
SELECT N'silver.mood', COUNT_BIG(*) FROM silver.mood
UNION ALL
SELECT N'silver.incident', COUNT_BIG(*) FROM silver.incident
UNION ALL
SELECT N'silver.staff_shift', COUNT_BIG(*) FROM silver.staff_shift
UNION ALL
SELECT N'gold.dim_date', COUNT_BIG(*) FROM gold.dim_date
UNION ALL
SELECT N'gold.dim_resident', COUNT_BIG(*) FROM gold.dim_resident
UNION ALL
SELECT N'gold.dim_staff', COUNT_BIG(*) FROM gold.dim_staff
UNION ALL
SELECT N'gold.dim_log_type', COUNT_BIG(*) FROM gold.dim_log_type
UNION ALL
SELECT N'gold.agg_log_count_daily', COUNT_BIG(*) FROM gold.agg_log_count_daily
UNION ALL
SELECT N'gold.fact_mood_daily', COUNT_BIG(*) FROM gold.fact_mood_daily
UNION ALL
SELECT N'gold.fact_communication', COUNT_BIG(*) FROM gold.fact_communication
UNION ALL
SELECT N'gold.fact_medication', COUNT_BIG(*) FROM gold.fact_medication
UNION ALL
SELECT N'gold.fact_appointment', COUNT_BIG(*) FROM gold.fact_appointment
UNION ALL
SELECT N'gold.fact_incident', COUNT_BIG(*) FROM gold.fact_incident
UNION ALL
SELECT N'gold.fact_staff_shift', COUNT_BIG(*) FROM gold.fact_staff_shift
UNION ALL
SELECT N'gold.fact_staff_involvement', COUNT_BIG(*) FROM gold.fact_staff_involvement
UNION ALL
SELECT N'gold.fact_flagged_log', COUNT_BIG(*) FROM gold.fact_flagged_log
ORDER BY table_name;
