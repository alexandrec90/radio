from radio.util import format_duration


def test_minutes_and_seconds():
    assert format_duration(75) == "1:15"


def test_hours():
    assert format_duration(3725) == "1:02:05"


def test_zero_and_fractions():
    assert format_duration(0) == "0:00"
    assert format_duration(59.9) == "0:59"


def test_unknown_length_reads_as_live():
    assert format_duration(None) == "live"


def test_negative_clamps_to_zero():
    assert format_duration(-5) == "0:00"
