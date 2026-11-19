"""Time resolver for historical enterprise operations data.

Purpose:
    Relative temporal expressions (e.g. 'last month', 'this month', 'last 30 days')
    are resolved deterministically against a configured AS_OF_DATE (default 2018-09-01).
    The LLM never computes dates on its own.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta
import re
from typing import Optional
from pydantic import BaseModel


class DateRange(BaseModel):
    """Resolved start and end date range with an explanatory label."""
    start: date
    end: date
    label: str

    def to_fact_string(self) -> str:
        """Rendered as an explicit fact for inclusion in LLM prompts."""
        return f"Resolved: '{self.label}' = {self.start.isoformat()} to {self.end.isoformat()}"


MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12
}


def resolve_time_expression(text: str, as_of_str: str = "2018-09-01") -> Optional[DateRange]:
    """Pure function resolving natural language time expressions against as_of date.

    Args:
        text: Natural language query text.
        as_of_str: ISO format date string (e.g., '2018-09-01').

    Returns:
        DateRange if matched, else None.
    """
    if not text:
        return None

    as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
    lower_text = text.lower()

    # 1. "last month"
    if "last month" in lower_text or "previous month" in lower_text:
        first_of_this_month = as_of.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return DateRange(start=last_month_start, end=last_month_end, label="last month")

    # 2. "this month"
    if "this month" in lower_text:
        first_of_month = as_of.replace(day=1)
        _, last_day = monthrange(as_of.year, as_of.month)
        end_of_month = as_of.replace(day=last_day)
        return DateRange(start=first_of_month, end=end_of_month, label="this month")

    # 3. "last 30 days" / "past 30 days"
    if "last 30 days" in lower_text or "past 30 days" in lower_text or "trailing 30 days" in lower_text:
        start_date = as_of - timedelta(days=30)
        end_date = as_of
        return DateRange(start=start_date, end=end_date, label="last 30 days")

    # 4. Quarters: e.g. "Q1 2018", "first quarter of 2018"
    q_match = re.search(r"\b(?:q([1-4])\s*(\d{4})|(\d{4})\s*q([1-4]))\b", lower_text)
    if q_match:
        q_num = int(q_match.group(1) or q_match.group(4))
        year = int(q_match.group(2) or q_match.group(3))
        start_month = (q_num - 1) * 3 + 1
        end_month = start_month + 2
        _, last_day = monthrange(year, end_month)
        return DateRange(
            start=date(year, start_month, 1),
            end=date(year, end_month, last_day),
            label=f"Q{q_num} {year}"
        )

    # 5. Month name + Year: e.g. "August 2018", "in July 2018"
    for name, month_num in MONTH_NAMES.items():
        m_regex = rf"\b{name}\s+(\d{{4}})\b"
        match = re.search(m_regex, lower_text)
        if match:
            year = int(match.group(1))
            _, last_day = monthrange(year, month_num)
            return DateRange(
                start=date(year, month_num, 1),
                end=date(year, month_num, last_day),
                label=f"{name.capitalize()} {year}"
            )

    # 6. Specific year alone: e.g. "in 2018", "throughout 2017", "during 2018"
    y_match = re.search(r"\b(?:in|throughout|during|for)\s+(201[6-8])\b", lower_text)
    if y_match:
        year = int(y_match.group(1))
        return DateRange(
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            label=f"year {year}"
        )

    return None
