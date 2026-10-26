"""Data model for a form-filling run.

Case data (vehicle, offence, location, description) is non-secret and arrives
as workflow inputs. The complainant identity arrives only through environment
variables mapped from GitHub Secrets; values are never logged or printed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

JERUSALEM_TZ = ZoneInfo("Asia/Jerusalem")

HEBREW_WEEKDAYS = {
    0: "שני",
    1: "שלישי",
    2: "רביעי",
    3: "חמישי",
    4: "שישי",
    5: "שבת",
    6: "ראשון",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# Nothing is submitted to a station - the PDF is only emailed to the complainant
# for review - so the station line is a formality. Default per user decision.
DEFAULT_POLICE_STATION = "ירושלים"

COMPLAINANT_ENV_VARS = (
    "COMPLAINANT_FIRST_NAME",
    "COMPLAINANT_LAST_NAME",
    "COMPLAINANT_ID",
    "COMPLAINANT_ADDRESS",
    "COMPLAINANT_PHONE",
)

DELIVERY_ENV_VARS = (
    "PDF_PASSWORD",
    "RECIPIENT_EMAIL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_APP_PASSWORD",
    "SMTP_FROM",
)

# SMTP_PORT is optional (default 587); all other delivery secrets are required to send.
OPTIONAL_DELIVERY_ENV_VARS = {"SMTP_PORT"}


class TriState(Enum):
    """A yes/no form field that may legitimately stay unanswered."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: str | None) -> TriState:
        normalized = (value or "").strip().lower()
        if normalized in {"yes", "כן", "true", "1"}:
            return cls.YES
        if normalized in {"no", "לא", "false", "0"}:
            return cls.NO
        if normalized in {"", "unknown", "לא ידוע"}:
            return cls.UNKNOWN
        raise ValueError(f"invalid yes/no value: {value!r}")


def is_valid_israeli_id(id_number: str) -> bool:
    """Checksum for a 9-digit Israeli ID number. Used as a warning-level guard."""
    digits = re.sub(r"\D", "", id_number)
    if len(digits) != 9:
        return False
    total = 0
    for index, char in enumerate(digits):
        digit = int(char) * (1 if index % 2 == 0 else 2)
        if digit > 9:
            digit -= 9
        total += digit
    return total % 10 == 0


def parse_iso_date(value: str, *, field_name: str) -> date:
    text = (value or "").strip()
    if not DATE_RE.match(text):
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return datetime.strptime(text, "%Y-%m-%d").date()


def hebrew_weekday(day: date) -> str:
    return HEBREW_WEEKDAYS[day.weekday()]


@dataclass(frozen=True, repr=False)
class Complainant:
    """Identity of the person filing the complaint. Loaded only from secrets."""

    first_name: str
    last_name: str
    id_number: str
    address: str
    phone: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> tuple[Complainant | None, list[str]]:
        """Build from environment variables.

        Returns (complainant, []) on success or (None, [missing variable names]).
        Values are never logged; only variable NAMES are reported when missing.
        """
        env = os.environ if environ is None else environ
        missing = [name for name in COMPLAINANT_ENV_VARS if not env.get(name, "").strip()]
        if missing:
            return None, missing
        return (
            cls(
                first_name=env["COMPLAINANT_FIRST_NAME"].strip(),
                last_name=env["COMPLAINANT_LAST_NAME"].strip(),
                id_number=env["COMPLAINANT_ID"].strip(),
                address=env["COMPLAINANT_ADDRESS"].strip(),
                phone=env["COMPLAINANT_PHONE"].strip(),
            ),
            [],
        )

    def checksum_warnings(self) -> list[str]:
        if not is_valid_israeli_id(self.id_number):
            return ["COMPLAINANT_ID does not pass the Israeli ID checksum (value not shown)"]
        return []


@dataclass(frozen=True)
class Vehicle:
    number: str
    manufacturer: str
    color: str
    type: str = ""


@dataclass(frozen=True)
class Offence:
    date: date
    day: str
    time: str
    street: str
    junction_or_house: str
    city: str
    description: str


@dataclass(frozen=True)
class Witness:
    name: str = ""
    id_number: str = ""
    phone: str = ""
    address: str = ""

    @property
    def is_empty(self) -> bool:
        return not any((self.name, self.id_number, self.phone, self.address))


@dataclass(frozen=True)
class Incident:
    """One offence event. Several incidents may share a vehicle (merged complaint)."""

    date: date
    day: str
    time: str
    street: str
    junction_or_house: str
    city: str
    description: str
    municipal_case: str = ""


@dataclass(frozen=True)
class CaseData:
    """Non-secret complaint details, supplied as workflow inputs."""

    police_station: str
    complaint_date: date
    vehicle: Vehicle
    offence: Offence
    can_identify_driver: TriState
    knows_driver: TriState
    willing_to_testify: bool
    driver_name: str = ""
    driver_address: str = ""
    driver_identifying_marks: str = ""
    witness: Witness = field(default_factory=Witness)
    # Populated only for a merged multi-incident complaint (2+ incidents);
    # stays empty for the classic single-incident form.
    incidents: tuple[Incident, ...] = ()

    VEHICLE_REQUIRED = (
        "vehicle_number",
        "vehicle_manufacturer",
        "vehicle_color",
    )

    OFFENCE_REQUIRED = (
        "offence_date",
        "offence_time",
        "offence_street",
        "offence_city",
        "offence_description",
    )

    # Keys required when no incidents[] list is supplied (backward compatibility).
    REQUIRED_INPUTS = VEHICLE_REQUIRED + OFFENCE_REQUIRED

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CaseData:
        problems: list[str] = []

        def text(key: str, source: Mapping[str, Any] = data) -> str:
            return str(source.get(key, "") or "").strip()

        for key in cls.VEHICLE_REQUIRED:
            if not text(key):
                problems.append(f"missing required input: {key}")

        def parse_incident(source: Mapping[str, Any], label: str) -> Incident | None:
            """Validate one incident. label identifies the entry by position, never by content."""
            prefix = f"{label}: " if label else ""
            ok = True
            for key in cls.OFFENCE_REQUIRED:
                if not text(key, source):
                    problems.append(f"{prefix}missing required input: {key}")
                    ok = False
            incident_date = None
            if text("offence_date", source):
                try:
                    incident_date = parse_iso_date(text("offence_date", source), field_name=f"{prefix}offence_date")
                except ValueError as exc:
                    problems.append(str(exc))
                    ok = False
            incident_time = text("offence_time", source)
            if incident_time and not TIME_RE.match(incident_time):
                problems.append(f"{prefix}offence_time must be HH:MM")
                ok = False
            if not ok or incident_date is None:
                return None
            return Incident(
                date=incident_date,
                day=text("offence_day", source) or hebrew_weekday(incident_date),
                time=incident_time,
                street=text("offence_street", source),
                junction_or_house=text("offence_junction_or_house", source),
                city=text("offence_city", source),
                description=str(source.get("offence_description", "")).strip(),
                municipal_case=text("municipal_case", source),
            )

        incidents: list[Incident] = []
        raw_incidents = data.get("incidents")
        if raw_incidents is not None:
            if not isinstance(raw_incidents, list) or not raw_incidents:
                problems.append("incidents must be a non-empty list of objects")
            else:
                for index, item in enumerate(raw_incidents, start=1):
                    if not isinstance(item, Mapping):
                        problems.append(f"incident #{index}: must be an object")
                        continue
                    parsed = parse_incident(item, f"incident #{index}")
                    if parsed is not None:
                        incidents.append(parsed)
        else:
            single = parse_incident(data, "")
            if single is not None:
                incidents.append(single)

        complaint_date_raw = text("complaint_date")
        complaint_date = None
        if complaint_date_raw:
            try:
                complaint_date = parse_iso_date(complaint_date_raw, field_name="complaint_date")
            except ValueError as exc:
                problems.append(str(exc))
        else:
            complaint_date = datetime.now(JERUSALEM_TZ).date()

        try:
            can_identify = TriState.parse(text("can_identify_driver"))
            knows_driver = TriState.parse(text("knows_driver"))
        except ValueError as exc:
            problems.append(str(exc))
            can_identify = TriState.UNKNOWN
            knows_driver = TriState.UNKNOWN

        if problems:
            raise ValueError("; ".join(problems))

        if not incidents or complaint_date is None:  # pragma: no cover - guarded above
            raise ValueError("no valid incident could be parsed")
        first = incidents[0]
        return cls(
            police_station=text("police_station") or DEFAULT_POLICE_STATION,
            complaint_date=complaint_date,
            vehicle=Vehicle(
                number=text("vehicle_number"),
                manufacturer=text("vehicle_manufacturer"),
                color=text("vehicle_color"),
                type=text("vehicle_type"),
            ),
            offence=Offence(
                date=first.date,
                day=first.day,
                time=first.time,
                street=first.street,
                junction_or_house=first.junction_or_house,
                city=first.city,
                description=first.description,
            ),
            can_identify_driver=can_identify,
            knows_driver=knows_driver,
            willing_to_testify=TriState.parse(text("willing_to_testify") or "yes") is TriState.YES,
            driver_name=text("driver_name"),
            driver_address=text("driver_address"),
            driver_identifying_marks=text("driver_identifying_marks"),
            witness=Witness(
                name=text("witness_name"),
                id_number=text("witness_id"),
                phone=text("witness_phone"),
                address=text("witness_address"),
            ),
            incidents=tuple(incidents) if len(incidents) > 1 else (),
        )
