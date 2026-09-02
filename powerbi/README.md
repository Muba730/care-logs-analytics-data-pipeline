# Power BI

Power BI imports reporting-ready Gold tables only. Bronze, Silver and Audit
tables are excluded from the semantic model.

For `gold.fact_incident`, create these relationships:

```text
fact_incident.date_key     → dim_date.date_key
fact_incident.resident_key → dim_resident.resident_key
fact_incident.staff_key    → dim_staff.staff_key
```

The `.gitignore` excludes `.pbix` files because they can be large. Portfolio
screenshots or an exported template may be added deliberately under this
folder.
