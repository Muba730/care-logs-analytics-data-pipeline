import unittest
from datetime import date, datetime

from azure_functions.silver_loader import (
    clean_text,
    get_shift,
    parse_range_start,
    validate_record,
)


class SilverLoaderTests(unittest.TestCase):
    def valid_record(self):
        return {
            "source_log_id": "LOG-001",
            "resident_id": "R01",
            "category": "Health Recordings",
            "item": "Mood",
            "title": "Mood - Good",
            "log_datetime": datetime(2025, 1, 6, 10, 0),
            "logged_by": "Staff 01",
            "amount_one_key": None,
            "amount_1": None,
            "amount_two_key": None,
            "amount_2": None,
        }

    def test_clean_text_removes_repeated_whitespace(self):
        self.assertEqual(clean_text("  First line\nSecond   line  "), "First line Second line")

    def test_day_shift_starts_at_0800(self):
        shift_date, shift_type = get_shift(datetime(2025, 1, 6, 8, 0))
        self.assertEqual(shift_date, date(2025, 1, 6))
        self.assertEqual(shift_type, "Day")

    def test_night_shift_starts_at_2100(self):
        shift_date, shift_type = get_shift(datetime(2025, 1, 6, 21, 0))
        self.assertEqual(shift_date, date(2025, 1, 6))
        self.assertEqual(shift_type, "Night")

    def test_early_morning_belongs_to_previous_night_shift(self):
        shift_date, shift_type = get_shift(datetime(2025, 1, 7, 2, 0))
        self.assertEqual(shift_date, date(2025, 1, 6))
        self.assertEqual(shift_type, "Night")

    def test_appointment_range_returns_start_time(self):
        result = parse_range_start("11/01/2025 10:30-12:00")
        self.assertEqual(result, datetime(2025, 1, 11, 10, 30))

    def test_unknown_resident_is_rejected(self):
        record = self.valid_record()
        record["resident_id"] = "R08"
        errors = validate_record(record, {"R01"}, {"Staff 01"})
        self.assertIn("Unknown resident_id", errors)

    def test_unknown_mood_value_is_rejected(self):
        record = self.valid_record()
        record["title"] = "Mood - Best"
        errors = validate_record(record, {"R01"}, {"Staff 01"})
        self.assertIn("Unknown mood label", errors)


if __name__ == "__main__":
    unittest.main()
