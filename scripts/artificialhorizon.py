import os
import configparser
from PIL import Image
import matplotlib
matplotlib.use('Qt5Agg')  # Use an interactive backend
#matplotlib.use('Agg')  # Use a non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator
from astropy.coordinates import EarthLocation, AltAz, SkyCoord
from astropy.time import Time
from astropy import units as u
from astropy.units import isclose
import pytz
from datetime import datetime

def read_landscape_ini(fn):
    #Read landscape.ini file to find name of image used
    config_object = configparser.ConfigParser()
    file =open(fn,"r")
    config_object.read_file(file)
    output_dict=dict()
    sections=config_object.sections()
    for section in sections:
        items=config_object.items(section)
        output_dict[section]=dict(items)

    return output_dict['landscape']['maptex']

def find_values(image_path, posn=0, tp = False):

    # Open the image
    img = Image.open(image_path).convert("RGBA")

    # Extract the alpha channel
    alpha_channel = np.array(img)[:, :, 3]  # The 4th channel is the alpha channel
    alpha_channel[:,0] = alpha_channel[:,1] #Hack bc 0 column vals off???? MattC

    # Find start for each column
    start_pt = []
    for col in range(alpha_channel.shape[1]):
        if tp==False:
            ##if non_transparent, ie tp=false
            # Find the first row where alpha > 0 (not fully transparent)
            found_rows = np.where(alpha_channel[:, col] > 0)[0]
        else:
            ##if transparent, ie tp=true
            ## Find the first row where alpha is 0 (fully transparent)
            found_rows = np.where(alpha_channel[:, col] == 0)[0]
        if len(found_rows) > 0:
            #photo has to have as mid point the horizon and be 1024*2048 (rows, cols)
            #python seems to want to read png with 0,0 point in upper left vs lower left
            #so need to invert, calc diff from 512, take that as a pct of 512 and multiply
            #by 90 to get degrees above horizon
            #start_pt.append( int(((alpha_channel.shape[0]-found_rows[posn])-(1024/2))*90/(1024/2)) ) #altitude
            start_pt.append((((alpha_channel.shape[0] - found_rows[posn]) - (1024 / 2)) * 90 / (1024 / 2)))
        else:
            start_pt.append(None)

    return np.array(start_pt)

def wrap_array_start(y_pos, start_index):
    return y_pos[start_index:] + y_pos[:start_index]

def plot_positions(positions, startval=0):
    # Convert None to NaN for plotting (to avoid breaks in the line)
    y_positions = [
        pos if pos is not None else float('nan')
        for pos in positions
    ]

    y_positions = wrap_array_start(y_positions, startval)
    x_positions = list(np.linspace(0, 359, len(y_positions)))

    # Plot the line
    plt.figure(figsize=(10, 5))
    plt.plot(x_positions, y_positions, label="Alt", color='blue', linewidth=2)
    plt.xlabel("Azimuth")
    plt.ylabel("Altitude")
    plt.ylim(0,90)
    plt.title("Horizon Profile")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.show()

    x_positions.append(x_positions[0])
    y_positions.append(y_positions[0])

    #return zip(x_positions,y_positions)
    return np.column_stack((x_positions,y_positions))

# Check to see if a point in the sky is within the defined region of the polygon
def is_point_in_polygon(az_alt_list, test_point):
    """
    Determine if a test point (azimuth, altitude) is within the closed polygon
    described by a list of azimuth/altitude points.

    Uses "winding algorithm"

    Parameters:
        az_alt_list (list of tuples): List of (azimuth, altitude) pairs that define the polygon (degrees).
        test_point (tuple): A tuple (azimuth, altitude) for the test point (degrees).

    Returns:
        bool: True if the test point is inside the polygon, False otherwise.

    Note :
        If the test point lies exactly on an edge of the polygon, this function will consider it outside. This behavior can be adjusted if required.
    """

    def is_left(p0, p1, p2):
        """Helper function to calculate if a point is to the left of a vector."""
        return ((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]))

    test_az, test_alt = test_point
    winding_number = 0

    # Loop through all edges of the polygon
    for i in range(len(az_alt_list)):
        p1 = az_alt_list[i]
        p2 = az_alt_list[(i + 1) % len(az_alt_list)]  # Wrap around to form a closed polygon

        if p1[1] <= test_alt:  # Start vertex is below test point
            if p2[1] > test_alt:  # An upward crossing
                if is_left(p1, p2, (test_az, test_alt)) > 0:  # Point is to the left of the edge
                    winding_number += 1
        else:  # Start vertex is above test point
            if p2[1] <= test_alt:  # A downward crossing
                if is_left(p1, p2, (test_az, test_alt)) < 0:  # Point is to the right of the edge
                    winding_number -= 1

    # If winding number is non-zero, the point is inside the polygon
    return winding_number != 0

#Let's assume we have a landscape photo in stellarium that we want to convert
#to numeric values.  We'll calc all that and create a new landscape choice for Stellarium

# N43 57 4.18, W72 19 58.61
my_lat = 43.951161
my_long = -72.332947
my_height = 330
my_tz = "US/Eastern"
my_year = 2025
my_month = 1
my_day = 19
my_hour = 16
my_minute = 58
my_second = 22

#break this down exhaustively bc who knows about MacOS or future changes ...
stellpath = '/home/matt/.stellarium/'
stell_landscapes_folder = 'landscapes/'
stell_landscape = 'MattC_horizon' #want to isolate this for later use, ie no folder slashes
stell_landscape_new = 'new_'+stell_landscape
fn_landscape_ini = '/landscape.ini' #add slash prefix

adj1 = 170 #MattC I needed to rotate the array to align with "north"
adj2 = -6.50001 #MattC For reasons that escape me, the horizon.txt version needed to be adjusted as well

OVERRIDE = False #Change to True to use test data from erewhon

# Example RA and Dec strings for True
#ra_str = '22h54m37.98s'  # Right Ascension J2000
#dec_str = '-15d49m23.3s'  # Declination J2000
#ra_str = '22h55m57.87s'  # Right Ascension "on date"
#dec_str = '-15d41m23.2s'  # Declination "on date"

# Example RA and Dec strings for False; resume execution at line 317 after switch from True case
ra_str = '22h47m55.32s'  # Right Ascension J2000
dec_str = '-25d54m56.2s'  # Declination J2000

stellarium_landscape_file = stellpath + stell_landscapes_folder + stell_landscape + fn_landscape_ini

fn_profile = read_landscape_ini(stellarium_landscape_file)

# Define the path to the PNG file
image_path = stellpath + stell_landscapes_folder + stell_landscape + '/'+ fn_profile

#Ok, at this point we should have an image file to assess

#Collect altitude and azimuth values
y_obs = find_values(image_path, 0, False)
x_obs = np.linspace(0, 359, len(y_obs))

if OVERRIDE:
    #Override with a test set
    # Create new standardized dataset
    erewhon_obs = np.array([[12, 62],
    [17, 45],
    [18, 29],
    [19, 15],
    [22, 10],
    [29, 7],
    [29, 12],
    [37, 18],
    [45, 14],
    [54, 17],
    [53, 24],
    [53, 28],
    [64, 27],
    [76, 31],
    [76, 33],
    [91, 37],
    [88,44],
    [119, 54],
    [139, 42],
    [162, 44],
    [184, 24],
    [197, 24],
    [198, 50],
    [235, 42],
    [223, 63],
    [230, 66],
    [304, 73],
    [304, 73],
    [14, 11]])

    # Sort by the first column
    erewhon_obs_sort = erewhon_obs[np.argsort(erewhon_obs[:, 0])]

    # Find unique values and compute averages
    unique_x, indices = np.unique(erewhon_obs_sort[:, 0], return_inverse=True)
    y_sums = np.bincount(indices, weights=erewhon_obs_sort[:, 1])
    y_counts = np.bincount(indices)
    averaged_obs = np.column_stack((unique_x, y_sums / y_counts))

    x_obs=averaged_obs[:,0]
    y_obs=averaged_obs[:,1]

# Ensure the first and last y-values match to enforce periodicity
if y_obs[0] != y_obs[-1]:
    y_obs = np.append(y_obs,y_obs[0])
    x_obs = np.append(x_obs,360)  # Extend x_obs to 360 for periodicity to numpy array
if x_obs[0] != 0:
    x_obs = np.append([0], x_obs)
    y_obs = np.append(y_obs[-1], y_obs)

# Fit a periodic cubic spline
pchip = PchipInterpolator(x_obs, y_obs)

# Generate 360 evenly spaced x values
x_new = np.linspace(0, 359, 360)

# Evaluate the spline at the new x values
y_new = pchip(x_new)

# Convert to integers (optional)
##y_new_int = np.round(y_new).astype(int)
y_new_int = y_new

#Gather data pairs into one list
azalt_pairs = plot_positions(y_new_int,adj1) #tweak to align known marker with 0,0 (north)

#Setup to create a new horizon based on data, not image
directory_path = stellpath + stell_landscapes_folder + stell_landscape_new
os.makedirs(directory_path, exist_ok=True)

#Data values are not stored in an image but in horizon.txt
hfile_fn = directory_path + '/horizon.txt' #add slash prefix
hfile = open(hfile_fn,'wt')
hfile.write("\n\n\n\n\n")
for pair in azalt_pairs:
    #hfile.write(f"{pair[0].astype(int)}\t{pair[1].astype(int)}\n")
    hfile.write(f"{pair[0]}\t{pair[1]}\n")
hfile.close()

#Establish the new landscape.ini file
lfile_fn = directory_path + '/landscape.ini' #add slash prefix
lfile = open(lfile_fn,'w')
ltext = '[landscape]\n\
name = '+f'{stell_landscape_new}'+'\n\
author = author\n\
description = '+f'{stell_landscape_new}'+'\n\
type = polygonal\n\
polygonal_horizon_list = horizon.txt\n\
polygonal_angle_rotatez={adj2}\n\
ground_color = .15,.45,.05\n\
minimal_brightness = 0.15\n\
'
lfile.write(ltext)
lfile.close()

#Establish the new CMakeLists file
lfile_fn = directory_path + '/CMakeLists.txt' #add slash prefix
lfile = open(lfile_fn,'w')
ltext = '\n\
########### install files ###############\n\
\n\
# install landscape.ini\n\
INSTALL (FILES landscape.ini DESTINATION ${SDATALOC}/'+f'{stell_landscapes_folder}'+f'{stell_landscape_new}'+' )\n\
\n\
# install textures and descriptions\n\
INSTALL (DIRECTORY ./ DESTINATION ${SDATALOC}/'+f'{stell_landscapes_folder}'+f'{stell_landscape_new}'+'\n\
	FILES_MATCHING PATTERN "*.txt"\n\
	PATTERN "description.*.utf8"\n\
	PATTERN "CMake*" EXCLUDE )\n\
'
lfile.write(ltext)
lfile.close()

#Run a test:
# Define the location of observation
location = EarthLocation(lat=my_lat, lon=my_long, height=my_height)  # Latitude, Longitude in degrees, height in meters

# Define the observation time in Eastern Standard Time (EST)
est_tz = pytz.timezone(my_tz)
local_time = datetime(my_year, my_month, my_day, my_hour, my_minute, my_second, tzinfo=est_tz)

# Convert to UTC
utc_time = local_time.astimezone(pytz.utc)
obs_time = Time(utc_time, format="datetime", scale="utc")

# AltAz frame for the given location and time
altaz_frame = AltAz(obstime=obs_time, location=location)

# Create SkyCoord object for the given RA and Dec (J2000)
coord = SkyCoord(ra=ra_str, dec=dec_str, frame='icrs', unit=(u.hourangle, u.deg))

# Convert to AltAz (azimuth and altitude)
altaz = coord.transform_to(altaz_frame) #Should return referred to JNow

# Extract azimuth and altitude in degrees
azimuth = altaz.az.deg
altitude = altaz.alt.deg

print(f"Az (decimal degrees): {azimuth:.6f}")
print(f"Alt (decimal degrees): {altitude:.6f}")

test_point = (np.round(azimuth), np.round(altitude))

# Check if the test point is inside the polygon
inside = is_point_in_polygon(azalt_pairs, test_point)
print(azalt_pairs[int(test_point[0])])  #corresponding value of horizon
print(f"Is the test point {test_point} inside the circle? {inside}")
