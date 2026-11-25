import unittest
from datetime import date

from bench.date_notes import calendar_note


CASES = [
    ("I visited yesterday.", date(2024, 3, 1), "yesterday = 29 February 2024"),
    ("I met her yesterday.", date(2023, 1, 1), "yesterday = 31 December 2022"),
    ("Tomorrow I will travel.", date(2024, 12, 31), "tomorrow = 1 January 2025"),
    ("Yesterday and again YESTERDAY.", date(2023, 5, 8), "yesterday = 7 May 2023"),
    ("My course began last month.", date(2023, 1, 18), "last month = December 2022"),
    ("I started last month.", date(2024, 3, 31), "last month = February 2024"),
    ("We met last year.", date(2023, 1, 1), "last year = 2022"),
    ("Someone wrote last week.", date(2022, 8, 14), "last week = week before 14 August 2022"),
    ("Last year, then yesterday.", date(2024, 3, 1), "last year = 2023; yesterday = 29 February 2024"),
]
GUARDS = [
    ("I was busy in the last month.", date(2024, 3, 1)),
    ("For the last week, things have been quiet.", date(2024, 3, 1)),
    ("It was the last year of school.", date(2024, 3, 1)),
    ("I liked the yesterdays album.", date(2024, 3, 1)),
    ("We visited on 14 August 2022.", date(2024, 3, 1)),
    ("It was yesterday.", None),
]


class CalendarNotesTest(unittest.TestCase):
    def test_relative_dates(self):
        for body, stamp, expected in CASES:
            with self.subTest(body=body, stamp=stamp):
                self.assertEqual(calendar_note(body, stamp), expected)

    def test_no_reference_invented(self):
        for body, stamp in GUARDS:
            with self.subTest(body=body):
                self.assertEqual(calendar_note(body, stamp), "")
