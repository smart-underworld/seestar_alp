import subprocess
import sys
from astropy.coordinates import SkyCoord
from astropy import units as u

def astap_to_floats(coord_string):
    # Your input string
    # coord_string = "21: 35  22.5 +57d 29 59"

    # 1. Clean up and reformat the string
    # The RA part is '21: 35  22.5' -> RA in H:M:S format
    # The Dec part is '+57d 29 59' -> Dec in D:M:S format (with 'd' separator)

    # Separate RA and Dec parts. The Dec part is separated by the sign ('+' or '-').
    # For simplicity, we can split the string by the first occurrence of '+' or '-'
    # which is right before the declination.

    ra_dec_parts = coord_string.split('+')
    # If the sign was '-', use: ra_dec_parts = coord_string.split('-')
    # and prepend '-' to the dec_part if it was split
    if len(ra_dec_parts) == 1:
        ra_dec_parts = coord_string.split('-')
        dec_sign = '-'
        ra_part = ra_dec_parts[0].strip()
        dec_part = ra_dec_parts[1].strip()

    else:
        dec_sign = '+'
        ra_part = ra_dec_parts[0].strip()
        dec_part = ra_dec_parts[1].strip()


    # Clean up RA: replace ':' with spaces
    ra_part = ra_part.replace(':', ' ').strip()
    # Clean up Dec: replace 'd' with space
    dec_part = dec_part.replace('d', ' ').strip()

    # Recombine the string for SkyCoord, explicitly using RA and Dec parts
    clean_coord_string = f"{ra_part} {dec_sign}{dec_part}"

    # 2. Use SkyCoord, specifying the units as (hourangle, degree)
    # The RA part is H M S, so unit is 'hourangle'
    # The Dec part is D M S, so unit is 'degree'
    c = SkyCoord(clean_coord_string,
             unit=(u.hourangle, u.deg))

    # 3. Extract the RA and Dec as floats in decimal degrees
    ra_float = c.ra.deg
    dec_float = c.dec.deg
    return float(ra_float), float(dec_float)


# Execute a simple command and get its output
# astap_cli -f Stacked_647_Unknown_20.0s_IRCUT_20250922-061754.fit -fov 1.26 -d /opt/astap/
# in_file = 'data/Unknown/Stacked_647_Unknown_20.0s_IRCUT_20250922-061754.fit'
in_file = sys.argv[1]

result = subprocess.run(['astap_cli', '-f', in_file, '-log', '-progress', '-ra', '21', '-dec', '+57', 
         '-t', '0.01', '-z', '1', '-s', '30','-r', '5', '-fov', '1.26', '-d', '/opt/astap/'],
          capture_output=True, text=True, check=True)
print("Stdout:", result.stdout)
print("Stderr:", result.stderr)

answer = result.stdout
result_start = answer.find("Solution found: ")
if result_start != -1:
    after_result = answer[result_start+16:]
    result = after_result[:after_result.find('\n')]
    print(astap_to_floats(result))
else:
    print("No solutions found.")