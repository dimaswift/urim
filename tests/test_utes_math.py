import pytest
from hypothesis import given
from hypothesis import strategies as st

from urim import utime
from urim.utime import DAY, HOUR


def test_unix_epoch_is_zero():
    assert utime.utes_from_date(1970, 1, 1) == 0
    assert utime.gregorian_to_jdn(1970, 1, 1) == utime.UNIX_EPOCH_JDN


@pytest.mark.parametrize(
    ("ymd", "jdn"),
    [
        ((2000, 1, 1), 2_451_545),
        ((1582, 10, 15), 2_299_161),  # first day of the Gregorian reform
        ((-4713, 11, 24), 0),  # JDN epoch on the proleptic Gregorian calendar
        ((1, 1, 1), 1_721_426),
        ((0, 12, 31), 1_721_425),
    ],
)
def test_known_julian_day_numbers(ymd, jdn):
    assert utime.gregorian_to_jdn(*ymd) == jdn
    assert utime.jdn_to_gregorian(jdn) == ymd


def test_bce_numbering():
    assert utime.bce_to_astronomical(1) == 0
    assert utime.bce_to_astronomical(860) == -859
    assert utime.astronomical_to_era(-859) == (860, "BCE")
    assert utime.astronomical_to_era(30) == (30, "CE")
    with pytest.raises(ValueError):
        utime.bce_to_astronomical(0)


def test_calendar_dates_land_on_midnight():
    """The v1.0 nominal-year formula put 860 BCE at 23:13. Calendar dates must be midnights."""
    t = utime.utes_from_bce(860)
    assert t % DAY == 0
    assert utime.utes_to_date(t).label() == "860 BCE-01-01 00:00"


def test_diurnal_offsets_are_wall_clock():
    day = utime.utes_from_bce(860, 9, 14)
    noon = day + utime.time_of_day_seconds("TZOHORAYIM")
    minchah = day + utime.time_of_day_seconds("MINCHAH")
    assert utime.utes_to_date(noon).label() == "860 BCE-09-14 12:00"
    assert minchah - noon == 3 * HOUR
    assert utime.time_of_day_seconds("19:30") == 19 * HOUR + 30 * 60


def test_next_time_of_day_rolls_forward_never_back():
    day = utime.utes_from_bce(860, 9, 14)
    evening = day + 20 * HOUR
    assert utime.next_time_of_day(day + 5 * HOUR, "TZOHORAYIM") == day + 12 * HOUR
    assert utime.next_time_of_day(evening, "BOKER") == day + DAY + 6 * HOUR
    assert utime.next_time_of_day(day + 12 * HOUR, "TZOHORAYIM") == day + 12 * HOUR


def test_bad_time_of_day_rejected():
    for bad in ("NOONISH", "25:00", "12", "ab:cd"):
        with pytest.raises(ValueError):
            utime.time_of_day_seconds(bad)


def test_durations():
    assert utime.duration_seconds(40, "days") == 3_456_000
    assert utime.duration_seconds(1, "years") == 31_556_952
    assert utime.duration_seconds(2.5, "hours") == 9_000


@st.composite
def dates(draw):
    year = draw(st.integers(min_value=-20_000, max_value=5_000))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=utime.days_in_month(year, month)))
    return year, month, day


@given(dates())
def test_date_jdn_roundtrip(ymd):
    assert utime.jdn_to_gregorian(utime.gregorian_to_jdn(*ymd)) == ymd


@given(st.integers(min_value=-(10**12), max_value=10**11))
def test_utes_roundtrip(t):
    d = utime.utes_to_date(t)
    assert utime.utes_from_date(d.year, d.month, d.day, d.seconds) == t


@given(dates())
def test_consecutive_days_are_one_day_apart(ymd):
    jdn = utime.gregorian_to_jdn(*ymd)
    assert utime.gregorian_to_jdn(*utime.jdn_to_gregorian(jdn + 1)) == jdn + 1
