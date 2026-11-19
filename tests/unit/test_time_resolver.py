"""Unit tests for deterministic time expression resolver."""

from datetime import date
from ontoagent.ontology.time import resolve_time_expression


def test_resolve_last_month():
    # As of 2018-09-01, last month is August 2018 (2018-08-01 to 2018-08-31)
    res = resolve_time_expression("What was the delay last month?", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2018, 8, 1)
    assert res.end == date(2018, 8, 31)
    assert res.label == "last month"
    assert "2018-08-01 to 2018-08-31" in res.to_fact_string()


def test_resolve_this_month():
    res = resolve_time_expression("Show sales for this month", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2018, 9, 1)
    assert res.end == date(2018, 9, 30)
    assert res.label == "this month"


def test_resolve_last_30_days():
    res = resolve_time_expression("Late rate over the last 30 days", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2018, 8, 2)
    assert res.end == date(2018, 9, 1)


def test_resolve_specific_month():
    res = resolve_time_expression("Orders delivered in August 2018", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2018, 8, 1)
    assert res.end == date(2018, 8, 31)


def test_resolve_quarter():
    res = resolve_time_expression("Show volume in Q1 2018", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2018, 1, 1)
    assert res.end == date(2018, 3, 31)


def test_resolve_year():
    res = resolve_time_expression("Revenue throughout 2017", as_of_str="2018-09-01")
    assert res is not None
    assert res.start == date(2017, 1, 1)
    assert res.end == date(2017, 12, 31)


def test_resolve_unknown_returns_none():
    res = resolve_time_expression("How many sellers are active?", as_of_str="2018-09-01")
    assert res is None
