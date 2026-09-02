# Data

This project uses a privacy-safe synthetic dataset informed by operational
experience in the care sector. It contains 41,345 care logs for seven residents
across 52 Monday-to-Sunday CSV files. The records mirror the information support
workers would enter during day-to-day care, including wellbeing, medication,
incidents, appointments and activities.

![Synthetic care-log sample](synthetic_data_sample.png)

## Generation constraints

The data was generated against defined business and data-quality rules rather
than produced randomly. These controlled the 20-column schema, resident and
staff IDs, permitted values, appointment statuses, event frequency and daily
record volumes. Each resident has 15-18 logs per day. Validation checks covered
required fields, timestamps, duplicate IDs, weekly date boundaries and the
relationship between appointment bookings and separately recorded outcomes.

## Connected storylines

Events were linked across weeks to create realistic patterns for analysis. These
include recurring changes in mood and communication, medication refusals,
incidents, bookmarked management actions, care-team follow-ups, financial-stress
support and overlapping staff-supported appointments. Exceptions were also
included, such as low wellbeing without an incident and falls without earlier
mood or communication warnings, to avoid presenting correlation as causation.

## File structure

The weekly filename pattern is:

```text
logs_YYYY-MM-DD_YYYY-MM-DD.csv
```

The filename is retained as `source_file` throughout the pipeline, providing
lineage and preventing the same weekly file from being processed twice.

