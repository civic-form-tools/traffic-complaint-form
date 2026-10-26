from datetime import date

import pytest

from traffic_complaint_form.models import (
    DEFAULT_POLICE_STATION,
    CaseData,
    Complainant,
    TriState,
    hebrew_weekday,
    is_valid_israeli_id,
    parse_iso_date,
)
from traffic_complaint_form.sample import sample_case

VALID_CASE = {
    "police_station": "מוריה",
    "vehicle_number": "12-345-67",
    "vehicle_manufacturer": "טויוטה",
    "vehicle_color": "לבן",
    "offence_date": "2026-01-15",
    "offence_time": "14:30",
    "offence_street": "רחוב הדוגמה",
    "offence_city": "ירושלים",
    "offence_description": "תיאור בדייקני",
}


def test_tristate_parse():
    assert TriState.parse("yes") is TriState.YES
    assert TriState.parse("כן") is TriState.YES
    assert TriState.parse("no") is TriState.NO
    assert TriState.parse("") is TriState.UNKNOWN
    assert TriState.parse(None) is TriState.UNKNOWN
    with pytest.raises(ValueError):
        TriState.parse("maybe")


def test_israeli_id_checksum():
    assert is_valid_israeli_id("123456782")  # documented placeholder, checksum-valid
    assert not is_valid_israeli_id("123456781")
    assert not is_valid_israeli_id("123")
    assert not is_valid_israeli_id("")


def test_parse_iso_date():
    assert parse_iso_date("2026-01-15", field_name="offence_date") == date(2026, 1, 15)
    with pytest.raises(ValueError):
        parse_iso_date("15/01/2026", field_name="offence_date")


def test_hebrew_weekday():
    assert hebrew_weekday(date(2026, 10, 26)) == "שני"  # Monday
    assert hebrew_weekday(date(2026, 1, 15)) == "חמישי"  # Thursday


def test_case_from_dict_valid():
    case = CaseData.from_dict(VALID_CASE)
    assert case.vehicle.number == "12-345-67"
    assert case.offence.day == "חמישי"  # derived from the date
    assert case.offence.date == date(2026, 1, 15)
    assert case.witness.is_empty
    assert case.willing_to_testify is True


def test_case_from_dict_offence_day_override():
    case = CaseData.from_dict({**VALID_CASE, "offence_day": "ראשון"})
    assert case.offence.day == "ראשון"


def test_case_from_dict_missing_required_lists_all():
    with pytest.raises(ValueError) as excinfo:
        CaseData.from_dict({"vehicle_number": "1"})
    message = str(excinfo.value)
    assert "offence_description" in message
    assert "vehicle_manufacturer" in message
    assert "police_station" not in message  # optional since it defaults to ירושלים


def test_case_from_dict_station_defaults_to_jerusalem():
    data = {k: v for k, v in VALID_CASE.items() if k != "police_station"}
    assert CaseData.from_dict(data).police_station == DEFAULT_POLICE_STATION
    assert CaseData.from_dict({**VALID_CASE, "police_station": "  "}).police_station == DEFAULT_POLICE_STATION
    assert CaseData.from_dict({**VALID_CASE, "police_station": "מוריה"}).police_station == "מוריה"


def test_case_from_dict_bad_time():
    with pytest.raises(ValueError, match="offence_time"):
        CaseData.from_dict({**VALID_CASE, "offence_time": "2pm"})


def test_complainant_from_env_missing_names_only():
    result, missing = Complainant.from_env({"COMPLAINANT_FIRST_NAME": "x"})
    assert result is None
    assert "COMPLAINANT_ID" in missing
    assert "COMPLAINANT_FIRST_NAME" not in missing


def test_complainant_checksum_warning(complainant):
    assert complainant.checksum_warnings() == []
    bad = Complainant("א", "ב", "000000001", "כתובת", "050")
    warnings = bad.checksum_warnings()
    assert len(warnings) == 1
    assert "000000001" not in warnings[0]  # never echoes the value


def test_sample_case_is_well_formed():
    case = sample_case()
    assert case.police_station
    assert case.offence.day == hebrew_weekday(case.offence.date)
