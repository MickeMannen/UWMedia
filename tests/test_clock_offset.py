"""utils/clock_offset.py - how the Color page shows the camera's clock offset
and reads a dive time typed from the computer's display."""
from utils.clock_offset import format_offset, parse_dive_time


def test_offset_text_reads_like_a_person_would_say_it():
    assert format_offset(0) == "0 s"
    assert format_offset(7214) == "+2 h 14 s"
    assert format_offset(-37) == "-37 s"
    assert format_offset(3600) == "+1 h"
    assert format_offset(-125) == "-2 min 5 s"


def test_dive_time_parsing_accepts_what_a_computer_shows():
    assert parse_dive_time("12:34") == 754
    assert parse_dive_time("1:02:03") == 3723
    assert parse_dive_time("12.34") == 754
    assert parse_dive_time("754") == 754
    assert parse_dive_time("12m34s") == 754
    assert parse_dive_time(" 0:05 ") == 5
    assert parse_dive_time("12:70") is None and parse_dive_time("abc") is None and parse_dive_time("") is None
