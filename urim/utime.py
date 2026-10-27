"""UTES: Unified Temporal Epoch Seconds.

A UTES value is a signed 64-bit count of nominal seconds since 1970-01-01T00:00:00Z on the
proleptic Gregorian calendar, ignoring leap seconds. Years use astronomical numbering
(1 BCE = 0, 2 BCE = -1, ...).

Day arithmetic goes through Julian Day Numbers, so every calendar date maps to an exact
midnight and time-of-day offsets land where they claim to. The nominal 365.2425-day year is
only used for "N years later" durations, never to locate a calendar date.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

MINUTE = 60
HOUR = 3_600
DAY = 86_400
WEEK = 7 * DAY
NOMINAL_YEAR = 31_556_952  # 365.2425 days
SYNODIC_MONTH = 2_551_443  # 29.530588 days, rounded to the second

UNIX_EPOCH_JDN = 2_440_588  # JDN of 1970-01-01
GREGORIAN_CYCLE_DAYS = 146_097  # days in 400 Gregorian years

DurationUnit = Literal["seconds", "minutes", "hours", "days", "weeks", "months", "years"]

UNIT_SECONDS: dict[str, int] = {
    "seconds": 1,
    "minutes": MINUTE,
    "hours": HOUR,
    "days": DAY,
    "weeks": WEEK,
    "months": SYNODIC_MONTH,
    "years": NOMINAL_YEAR,
}


def duration_seconds(value: float, unit: DurationUnit) -> int:
    return round(value * UNIT_SECONDS[unit])


# ---------------------------------------------------------------------------------------------
# Year numbering
# ---------------------------------------------------------------------------------------------


def bce_to_astronomical(year_bce: int) -> int:
    if year_bce < 1:
        raise ValueError(f"BCE year must be >= 1, got {year_bce}")
    return 1 - year_bce


def astronomical_to_era(year: int) -> tuple[int, Literal["BCE", "CE"]]:
    return (1 - year, "BCE") if year <= 0 else (year, "CE")


# ---------------------------------------------------------------------------------------------
# Proleptic Gregorian <-> Julian Day Number
# ---------------------------------------------------------------------------------------------


def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    """JDN for a proleptic Gregorian date with astronomical year numbering. Valid for any year."""
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range: {month}")
    if not 1 <= day <= days_in_month(year, month):
        raise ValueError(f"day out of range: {year}-{month}-{day}")
    # Shift into positive years by whole 400-year cycles so the integer formula stays valid.
    cycles = 0
    if year < -4000:
        cycles = (-4000 - year) // 400 + 1
    y_shifted = year + 400 * cycles
    a = (14 - month) // 12
    y = y_shifted + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jdn - cycles * GREGORIAN_CYCLE_DAYS


def jdn_to_gregorian(jdn: int) -> tuple[int, int, int]:
    """Inverse of gregorian_to_jdn: (astronomical year, month, day)."""
    cycles = 0
    if jdn < 0:
        cycles = -jdn // GREGORIAN_CYCLE_DAYS + 1
    a = jdn + cycles * GREGORIAN_CYCLE_DAYS + 32044
    b = (4 * a + 3) // GREGORIAN_CYCLE_DAYS
    c = a - GREGORIAN_CYCLE_DAYS * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year - 400 * cycles, month, day


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap_year(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


# ---------------------------------------------------------------------------------------------
# Calendar <-> UTES
# ---------------------------------------------------------------------------------------------


def utes_from_date(year: int, month: int = 1, day: int = 1, seconds: int = 0) -> int:
    """UTES for a proleptic Gregorian date (astronomical year) plus seconds after midnight."""
    return (gregorian_to_jdn(year, month, day) - UNIX_EPOCH_JDN) * DAY + seconds


def utes_from_bce(year_bce: int, month: int = 1, day: int = 1, seconds: int = 0) -> int:
    return utes_from_date(bce_to_astronomical(year_bce), month, day, seconds)


@dataclass(frozen=True)
class UtesDate:
    year: int  # astronomical
    month: int
    day: int
    seconds: int  # since midnight

    @property
    def hour(self) -> int:
        return self.seconds // HOUR

    @property
    def minute(self) -> int:
        return self.seconds % HOUR // MINUTE

    def label(self, with_time: bool = True) -> str:
        """Human label, e.g. '860 BCE-09-14 15:00'."""
        y, era = astronomical_to_era(self.year)
        text = f"{y} {era}-{self.month:02d}-{self.day:02d}"
        return f"{text} {self.hour:02d}:{self.minute:02d}" if with_time else text


def utes_to_date(utes: int) -> UtesDate:
    days, seconds = divmod(utes, DAY)
    year, month, day = jdn_to_gregorian(days + UNIX_EPOCH_JDN)
    return UtesDate(year, month, day, seconds)


def floor_to_day(utes: int) -> int:
    return utes - utes % DAY


# ---------------------------------------------------------------------------------------------
# Ancient time-of-day markers
# ---------------------------------------------------------------------------------------------


class Diurnal(StrEnum):
    """Nominal solar times for biblical time-of-day markers (seconds after civil midnight).

    The Hebrew day begins at sunset (EREV); UTES days begin at midnight. Narrative "next day"
    reasoning is the Chronologist's job; this table only fixes clock positions.
    """

    ASHMORET_HABOKER = "ASHMORET_HABOKER"  # last night watch, 02:00-06:00
    SHACHAR = "SHACHAR"  # dawn, first light
    BOKER = "BOKER"  # sunrise / morning
    HORA_TERTIA = "HORA_TERTIA"  # third hour
    TZOHORAYIM = "TZOHORAYIM"  # noon, "double light"; also kchom hayom
    MINCHAH = "MINCHAH"  # ba'alot hamincha, afternoon offering
    BEIN_HAARBAYIM = "BEIN_HAARBAYIM"  # "between the evenings", twilight
    EREV = "EREV"  # sunset, start of the Hebrew day and of the first watch
    ASHMORET_HATICHONAH = "ASHMORET_HATICHONAH"  # middle night watch, 22:00-02:00


DIURNAL_SECONDS: dict[Diurnal, int] = {
    Diurnal.ASHMORET_HABOKER: 2 * HOUR,
    Diurnal.SHACHAR: 5 * HOUR + 30 * MINUTE,
    Diurnal.BOKER: 6 * HOUR,
    Diurnal.HORA_TERTIA: 9 * HOUR,
    Diurnal.TZOHORAYIM: 12 * HOUR,
    Diurnal.MINCHAH: 15 * HOUR,
    Diurnal.BEIN_HAARBAYIM: 17 * HOUR + 30 * MINUTE,
    Diurnal.EREV: 18 * HOUR,
    Diurnal.ASHMORET_HATICHONAH: 22 * HOUR,
}


def time_of_day_seconds(value: str) -> int:
    """Seconds after midnight for a Diurnal marker name or an 'HH:MM' clock time."""
    if value in Diurnal.__members__:
        return DIURNAL_SECONDS[Diurnal(value)]
    hh, sep, mm = value.partition(":")
    if not sep or not (hh.isdigit() and mm.isdigit()):
        raise ValueError(f"not a diurnal marker or HH:MM time: {value!r}")
    h, m = int(hh), int(mm)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"clock time out of range: {value!r}")
    return h * HOUR + m * MINUTE


def next_time_of_day(utes: int, time_of_day: str) -> int:
    """First instant at or after `utes` whose clock time is `time_of_day`."""
    candidate = floor_to_day(utes) + time_of_day_seconds(time_of_day)
    return candidate if candidate >= utes else candidate + DAY
