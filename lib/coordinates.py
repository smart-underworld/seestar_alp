"""Coordinate calculations"""


def parse_dec_to_float(dec_string: str):
    # Split the Dec string into degrees, minutes, and seconds
    if dec_string[0] == "-":
        sign = -1
        dec_string = dec_string[1:]
    else:
        sign = 1
    degrees, minutes, seconds = map(float, dec_string.split(":"))

    # Convert to decimal degrees. The sign applies to the WHOLE value, not just
    # the degrees term (otherwise "-30:30:00" wrongly parsed as -29.5).
    dec_decimal = sign * (degrees + minutes / 60 + seconds / 3600)

    return dec_decimal
