# Implementation Notes

## Modelling decisions

- The controlled resident roster is `R01` to `R07`.
- Silver and Gold each contain a separate incident table.
- Appointment bookings and outcomes remain separate events.
- Appointment bookings are not matched to later outcome records.
- `escort_staff_key` is not used.
- Staff shifts are derived from logging timestamps rather than a rota file.
- `Manager 01` is excluded from support-worker shift reporting.
- Reloading the same file replaces the previous batch instead of adding duplicates.

## Validation

Bronze records that cannot be processed safely are written to
`audit.data_exception`. Deleted records and duplicates are filtered without
being treated as validation failures.

Run `sql/validation/layer_row_counts.sql` after processing the full dataset to
record the final Bronze, Silver and Gold row counts.
