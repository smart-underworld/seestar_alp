import geocoder
from datetime import datetime
from astropy.coordinates import FK4,FK5, SkyCoord
from astropy.time import Time
import astropy.units as u
import math

class Util:
    @staticmethod
    def get_current_gps_coordinates():
        g = geocoder.ip('me')#this function is used to find the current information using our IP Add
        if g.latlng is not None: #g.latlng tells if the coordiates are found or not
            return g.latlng
        else:
            return None
    
    # in_ra = '17h21m29.17s'  # Center RA in hour-degree format
    # in_dec = '+80d33m44.5s'  # Center Dec in degree-minute format
    # returning a SkyCoord object in JNow coordinate system
#    def j2000_to_jnow(in_ra, in_dec):
#        _in_j2000 = SkyCoord(ra=in_ra, dec=in_dec, unit=(u.hourangle, u.deg), frame='icrs')
#        _fk5 = FK5(equinox=Time(datetime.now(datetime.utc).jd, format="jd", scale="utc"))
#        return _in_j2000.transform_to(_fk5) 
    
    @staticmethod
    def parse_coordinate(is_j2000, in_ra, in_dec):
        _fk5 = FK5(equinox=Time(Time(datetime.utcnow(), scale='utc').jd, format="jd", scale="utc"))
        if is_j2000:
            coord_frame = 'icrs'
        else:
            coord_frame = _fk5
        if isinstance(in_ra, str):
            result = SkyCoord(ra=in_ra, dec=in_dec, unit=(u.hourangle, u.deg), frame=coord_frame)
        else:
            result = SkyCoord(ra=in_ra*u.hour, dec=in_dec*u.deg, frame=coord_frame)
        if is_j2000:
            result = result.transform_to(_fk5)
        return result

    # take into account ra spacing factor changes depends on dec position as 1/cos(dec)
    @staticmethod
    def mosaic_next_center_spacing(in_ra, in_dec, overlap_percent):
        # seestar fov at dec = 0
        dec_length = 1.29 # degrees
        ra_length = 3/60.0  # 3 minutes when dec is at 0 degress, changes by factor of 1/cos(dec)

        delta_Dec = dec_length * (100.0-overlap_percent)/100.0
        delta_RA = ra_length * (100.0-overlap_percent)/100.0

        # in case we are too close to the poles
        if (abs(in_dec) > 85.0):
            return [1.0, delta_Dec]
        
        factor_RA = math.cos(in_dec*math.pi/180.0)
        #print("delta_RA at dec = 0: ", delta_RA)
        delta_RA /= factor_RA
        #print("factor: ", factor_RA, ", result: ", delta_RA)
        return [delta_RA, delta_Dec]

    # trim out the seconds to 1 decimal precision
    @staticmethod
    def trim_seconds(test_str):
        out = test_str
        if isinstance(test_str, str) and test_str.endswith('s'):
            index =  test_str.find('m')
            if index > 0:
                str_seconds = test_str[index+1:len(test_str)-1]
                float_seconds = float(str_seconds)
                #bprint(str_seconds)
                # print(float_seconds)
                out = "{}{:.1f}s".format(test_str[:index+1], float_seconds)
        return out
