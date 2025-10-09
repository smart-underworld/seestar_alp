import geocoder
from datetime import datetime
from astropy.coordinates import FK5, SkyCoord, AltAz
from astropy.time import Time
import astropy.units as u
import math
import numpy as np
import collections


class Util:
    @staticmethod
    def get_current_gps_coordinates():
        g = geocoder.ip(
            "me"
        )  # this function is used to find the current information using our IP Add
        if g.latlng is not None:  # g.latlng tells if the coordiates are found or not
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
        _fk5 = FK5(
            equinox=Time(
                Time(datetime.utcnow(), scale="utc").jd, format="jd", scale="utc"
            )
        )
        if is_j2000:
            coord_frame = "icrs"
        else:
            coord_frame = _fk5
        if isinstance(in_ra, str):
            result = SkyCoord(
                ra=in_ra, dec=in_dec, unit=(u.hourangle, u.deg), frame=coord_frame
            )
        else:
            result = SkyCoord(ra=in_ra * u.hour, dec=in_dec * u.deg, frame=coord_frame)
        if is_j2000:
            result = result.transform_to(_fk5)
        return result

    # take into account ra spacing factor changes depends on dec position as 1/cos(dec)
    @staticmethod
    def mosaic_next_center_spacing(in_ra, in_dec, overlap_percent, device_model="Seestar S50"):
        # seestar fov at dec = 0
        dec_length = 1.27  # degrees
        ra_length = (
            2.83 / 60.0
        )  # 3 minutes when dec is at 0 degress, changes by factor of 1/cos(dec)

        if device_model == "Seestar S30":
            dec_length = 2.12

        # todo: support other models too

        delta_Dec = dec_length * (100.0 - overlap_percent) / 100.0
        delta_RA = ra_length * (100.0 - overlap_percent) / 100.0

        # in case we are too close to the poles
        if abs(in_dec) > 85.0:
            return [1.0, delta_Dec]

        factor_RA = math.cos(in_dec * math.pi / 180.0)
        # print("delta_RA at dec = 0: ", delta_RA)
        delta_RA /= factor_RA
        # print("factor: ", factor_RA, ", result: ", delta_RA)
        return [delta_RA, delta_Dec]

    # trim out the seconds to 1 decimal precision
    @staticmethod
    def trim_seconds(test_str):
        out = test_str
        if isinstance(test_str, str) and test_str.endswith("s"):
            index = test_str.find("m")
            if index > 0:
                str_seconds = test_str[index + 1 : len(test_str) - 1]
                float_seconds = float(str_seconds)
                # bprint(str_seconds)
                # print(float_seconds)
                out = "{}{:.1f}s".format(test_str[: index + 1], float_seconds)
        return out

    @staticmethod
    def get_JNow(ra: float, dec: float) -> SkyCoord:
        coord = SkyCoord(ra=ra, dec=dec, frame="fk5", unit="deg", equinox="JNow")
        return coord

    @staticmethod
    def get_altaz(self, ra: float, dec: float, coord_frame: AltAz) -> SkyCoord:
        coord = self.get_JNow(ra, dec)
        return coord.transform_to(coord_frame)

    @staticmethod
    def get_altaz_deg(self, ra: float, dec: float, coord_frame: AltAz) -> np.ndarray:
        coord = self.get_altaz(ra, dec, coord_frame)
        return np.asarray([coord.alt.deg, coord.az.deg])

    @staticmethod
    def get_altaz_frame(self, site_ra: float, site_dec: float) -> AltAz:
        site = self.get_JNow(site_ra, site_dec)
        altaz_frame = AltAz(location=site)
        return altaz_frame
    
    @staticmethod
    # return number of minutes from previous midnight to the given hour and minute
    def get_start_minute_from_start_time(start_time_hour, start_time_minute):
        if start_time_hour <= 12:
            start_time_hour += 24
        return start_time_hour * 60 + start_time_minute

    @staticmethod
    # return a map of <panel_name>:{ra,dec} for all panels in the mosaic
    def get_panel_coordinates(center_RA, center_Dec, nRA, nDec, overlap_percent, model_name) -> map:

        # --- Define Mosaic Parameters ---
        # The central coordinate for the entire mosaic
        mosaic_center = SkyCoord(ra=center_RA * u.deg, dec=center_Dec * u.deg, frame='icrs')
        
        # The total desired size of the mosaic on the sky
        panel_fov_ra = 1.29 * u.deg
        panel_fov_dec = 0.7 * u.deg
        
        # The number of individual pointings (panels) in each direction
        num_panels_ra = nRA
        num_panels_dec = nDec
        
        # The desired fractional overlap between adjacent panels
        panel_overlap = overlap_percent / 100.0  # convert percentage to a fraction
        
        panel_map = {}
        spacing_result = Util.mosaic_next_center_spacing(
            center_RA, center_Dec, overlap_percent, model_name)
        delta_RA = spacing_result[0]
        delta_Dec = spacing_result[1]

        # adjust mosaic center if num panels is even
        if nRA % 2 == 0:
            center_RA -= delta_RA / 2
        if nDec % 2 == 0:
            center_Dec -= delta_Dec / 2

        cur_dec = center_Dec + int(nDec / 2) * delta_Dec
        for index_dec in range(nDec):
            cur_ra = center_RA + int(nRA / 2) * delta_RA
            for index_ra in range(nRA):
                # check if we are doing a subset of the panels
                panel_string = f"{chr(index_ra+ord("A"))}{index_dec + 1}"
                # round the floats ra and dec to 3 decimal places
                panel_map[panel_string] = [round(cur_ra, 3), round(cur_dec,3)]
                cur_ra -= delta_RA
            cur_dec -= delta_Dec
        return panel_map


    @staticmethod
    def convert_schedule_to_native_plan(schedule:map, device_model) -> map:
        native_plan = {}
        native_plan["update_time_seestar"] = datetime.utcnow().strftime("%Y.%m.%d")
        native_plan["plan_name"] = schedule.get("name", schedule.get("schedule_id", "Unnamed Plan"))
        native_plan["list"] = []
        # set start_time_hr to local time hour 
        # set start_time_minute to local time minute
        start_time_hour = datetime.now().hour
        start_time_minute = datetime.now().minute
        start_min = Util.get_start_minute_from_start_time(start_time_hour, start_time_minute)

        the_list = schedule.get("list", [])


        if isinstance(the_list, collections.deque):
            the_list = list(the_list)

        for item in the_list:
            if item.get("action") == "start_mosaic":
                native_item = {}
                params = item.get("params", {})
                target_name = params.get("target_name", "Unknown")
                is_j2000 = params.get("is_j2000", False)
                ra = params.get("ra", "0h0m0s")
                dec = params.get("dec", "0d0m0s")
                parsed_coord = Util.parse_coordinate(is_j2000, ra, dec)
                center_RA = parsed_coord.ra.hour
                center_Dec = parsed_coord.dec.deg
                native_item["lp_filter"] = params.get("is_use_lp_filter", False)
                native_item["state"] = "idle"
                native_item["target_id"] = 0  # no target ID in mosaic params
                native_item["duration_min"] = params.get("panel_time_sec", 0) // 60
                native_item["skip"] = False
                ra_num = params.get("ra_num", 1)
                dec_num = params.get("dec_num", 1)
                # calculate the ra, dec for the selected panel
                panel_coord_map = Util.get_panel_coordinates(center_RA, center_Dec, ra_num, dec_num, params.get("overlap_percent", 20), device_model)

                selected_panels = params.get("selected_panels", "")
                if selected_panels != "":
                    selected_list = selected_panels.split(";")
                    for panel_name in selected_list:
                        native_item_clone = native_item.copy()
                        native_item_clone["target_name"] = target_name+'_'+panel_name
                        panel_coords = panel_coord_map.get(panel_name, [center_RA, center_Dec])
                        native_item_clone["target_ra_dec"] = panel_coords
                        print(f"Selected panel {panel_name} is at {panel_coords}")
                        native_item_clone["start_min"] = start_min
                        native_plan["list"].append(native_item_clone)
                        start_min += native_item_clone["duration_min"]
                else:
                        native_item["target_name"] = target_name
                        native_item["target_ra_dec"] = [center_RA, center_Dec]
                        native_item["start_min"] = start_min

                        # use max of ra_num and dec_num as scale, up to max of 2
                        max_panels = max(ra_num, dec_num)
                        scale = min(max_panels, 2.0) 
                        native_item["duration_min"] = round(native_item["duration_min"] * scale * scale)  # increase duration by scale^2
                        
                        if max_panels > 1:
                            native_item["mosaic"] = {
                                "scale": scale,     
                                "angle": 0,  # no angle in mosaic params
                                "star_map_angle": 0,  # no star map angle in mosaic params
                            }
                        native_plan["list"].append(native_item)
                        start_min += native_item["duration_min"]

            elif item.get("action") == "wait_for":
                sleep_time = item["params"]["timer_sec"]
                start_min += sleep_time // 60

            elif item.get("action") == "wait_until":
                local_time_str = item["params"]["local_time"]
                if ":" in local_time_str:
                    time_parts = local_time_str.split(":")
                    if len(time_parts) == 2:
                        start_time_hour = int(time_parts[0])
                        start_time_minute = int(time_parts[1])
                        start_min = Util.get_start_minute_from_start_time(start_time_hour, start_time_minute)
                else:
                    # invalid time format, skip
                    continue

            else:
                # unsupported action, skip
                continue
        return native_plan
        

