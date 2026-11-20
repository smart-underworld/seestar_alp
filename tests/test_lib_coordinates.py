from lib.coordinates import parse_dec_to_float


def test_parse_dec_sign_applies_to_whole_value():
    # Regression: `sign * degrees + minutes/60 + seconds/3600` applied the sign
    # only to the degrees term, so "-30:30:00" parsed as -29.5 instead of -30.5.
    assert parse_dec_to_float("-30:30:00") == -30.5
    assert parse_dec_to_float("+30:30:00") == 30.5
    assert parse_dec_to_float("00:30:00") == 0.5


def test_parse_dec_is_a_plain_function_not_a_method():
    # Regression: the function carried a stray `self` first parameter; a normal
    # single-argument call would otherwise be a TypeError.
    assert parse_dec_to_float("-00:00:36") == -0.01
