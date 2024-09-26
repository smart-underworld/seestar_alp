import time
from datetime import datetime, timedelta
from tzlocal import get_localzone

import falcon
from falcon import HTTPTemporaryRedirect, HTTPFound
from astroquery.simbad import Simbad
from jinja2 import Template, Environment, FileSystemLoader
from wsgiref.simple_server import WSGIRequestHandler, make_server
from collections import OrderedDict
from pathlib import Path
import requests
import humanize
import json
import csv
import re
import os
import io
import socket
import sys
import ephem
import geocoder
import pytz
import re
import zipfile
import subprocess
import platform
import shutil
import signal

from skyfield.api import load


# if not getattr(sys, "frozen", False):  # if we are not running from a bundled app
#    sys.path.append(os.path.join(os.path.dirname(__file__), "../device"))

from device.seestar_logs import SeestarLogging
from device.config import Config  # type: ignore
from device.log import init_logging  # type: ignore
from device.version import Version # type: ignore
from device import telescope
import threading

logger = init_logging()


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def get_listening_ip():
    if Config.ip_address == "0.0.0.0":
        # Find the ip
        ip_address = get_ip()
    else:
        ip_address = Config.ip_address
    return ip_address


base_url = "http://" + get_listening_ip() + ":" + str(Config.port)
stellarium_url = 'http://' + str(Config.sthost) + ':' + str(Config.stport) + '/api/objects/info'
simbad_url = 'https://simbad.cds.unistra.fr/simbad/sim-id?output.format=ASCII&obj.bibsel=off&Ident='
messages = []
online = None
queue = {}

#
# Globally turned off IPv6 on requests.  This was causing incredible slowness
#   on Windows
#
requests.packages.urllib3.util.connection.HAS_IPV6 = False


def flash(resp, message):
    # todo : set to internal state so it can be used!
    resp.set_cookie('flash_cookie', message, path='/')
    messages.append(message)


def get_messages():
    if len(messages) > 0:
        resp = messages
        messages.clear()
        return resp
    return []


def get_telescopes():
    telescopes = Config.seestars
    return list(telescopes)


def get_telescope(telescope_id):
    telescopes = get_telescopes()
    return list(filter(lambda telescope: telescope['device_num'] == telescope_id, telescopes))[0]


def get_root(telescope_id):
    if telescope_id == 0:
        root = f"/0"
        return root
    else:
        telescopes = get_telescopes()
        # if len(telescopes) == 1:
        #     return ""
        telescope = list(filter(lambda tel: tel['device_num'] == telescope_id, telescopes))[0]
        if telescope:
            root = f"/{telescope['device_num']}"
            return root
    return ""


def get_imager_root(telescope_id):
    if telescope_id > 0:
        telescopes = get_telescopes()
        # if len(telescopes) == 1:
        #     return ""

        telescope = list(filter(lambda tel: tel['device_num'] == telescope_id, telescopes))[0]
        if telescope:
            root = f"http://{get_listening_ip()}:{Config.imgport}/{telescope['device_num']}"
            return root
    return ""


def get_context(telescope_id, req):
    # probably a better way of doing this...
    telescopes = get_telescopes()
    root = get_root(telescope_id)
    imager_root = get_imager_root(telescope_id)
    online = check_api_state(telescope_id)
    segments = req.relative_uri.lstrip("/").split("/", 1)
    partial_path = segments[1] if len(segments) > 1 else segments[0]
    experimental = Config.experimental
    uitheme = Config.uitheme
    if telescope_id > 0:
        telescope = get_telescope(telescope_id)
    else:
        telescope = {
            "device_num": 0,
            "name": "Seestar Federation",
            "ip_address": get_ip()
        }

    return {"telescope": telescope, "telescopes": telescopes, "root": root, "partial_path": partial_path,
            "online": online, "imager_root": imager_root, "experimental": experimental, "uitheme": uitheme}


def get_flash_cookie(req, resp):
    cookie = req.get_cookie_values('flash_cookie')
    if cookie:
        resp.unset_cookie('flash_cookie', path='/')
        return cookie
    return []


def update_twilight_times(latitude=None, longitude=None):
    observer = ephem.Observer()
    observer.date = datetime.now()
    local_timezone = get_localzone()
    sun = ephem.Sun()
    current_date_formatted = str(datetime.now().strftime("%Y-%m-%d"))

    if (latitude == None and longitude == None):
        if internet_connection:
            geo = geocoder.ip('me')
            latitude = str(geo.latlng[0])
            longitude = str(geo.latlng[1])
            observer.lat = str(geo.latlng[0])  # ephem likes str
            observer.lon = str(geo.latlng[1])  # ephem likes str
        else:
            twilight_times = {
                "Info": "No internet connection detected on the device running SSC. Please set Latitude and Longitude.",
                "Latitude": "",
                "Longitude": ""
            }

            # Don't update the cache file.
            return twilight_times
    else:
        observer.lat = str(latitude)  # ephem likes str
        observer.lon = str(longitude)  # ephem likes str

    # Sunrise & Sunset
    loc_sunset = pytz.utc.localize(observer.next_setting(sun).datetime()).astimezone(local_timezone)
    loc_next_sunrise = pytz.utc.localize(observer.next_rising(sun).datetime()).astimezone(local_timezone)

    # Civil Beginning and End
    observer.horizon = '-6'  # -6=civil twilight, -12=nautical, -18=astronomical
    loc_end_civil = pytz.utc.localize(observer.next_setting(sun, use_center=True).datetime()).astimezone(local_timezone)
    loc_next_beg_civil = pytz.utc.localize(observer.next_rising(sun, use_center=True).datetime()).astimezone(
        local_timezone)

    # Astronomical Beginning and End
    observer.horizon = '-18'  # -6=civil twilight, -12=nautical, -18=astronomical
    loc_beg_astronomical = pytz.utc.localize(observer.next_setting(sun, use_center=True).datetime()).astimezone(
        local_timezone)
    loc_next_end_astronomical = pytz.utc.localize(observer.next_rising(sun, use_center=True).datetime()).astimezone(
        local_timezone)

    twilight_times = {
        "Today's Date": current_date_formatted,
        "Latitude": str(latitude),
        "Longitude": str(longitude),
        "Today's Sunset": str(loc_sunset),
        "Next Sunrise": str(loc_next_sunrise),
        "Today's Civil End": str(loc_end_civil),
        "Next Civil Begin": str(loc_next_beg_civil),
        "Today's Astronomical Begin": str(loc_beg_astronomical),
        "Next Astronomical End": str(loc_next_end_astronomical)
    }

    # Write twilight times cache file
    if getattr(sys, "frozen", False):  # frozen means that we are running from a bundled app
        twilight_times_file = os.path.abspath(os.path.join(sys._MEIPASS, "twilight_times.json"))
    else:
        twilight_times_file = os.path.join(os.path.dirname(__file__), "twilight_times.json")

    with open(twilight_times_file, "w") as outfile:
        logger.info(f"Twilight times: Writing cache file.")
        json.dump(twilight_times, outfile)

    return twilight_times


def get_twilight_times():
    current_date_formatted = str(datetime.now().strftime("%Y-%m-%d"))

    if getattr(sys, "frozen", False):  # frozen means that we are running from a bundled app
        twilight_times_file = os.path.abspath(os.path.join(sys._MEIPASS, "twilight_times.json"))
    else:
        twilight_times_file = os.path.join(os.path.dirname(__file__), "twilight_times.json")

    # Check to see if there is cached infromation for today
    if os.path.isfile(twilight_times_file):
        logger.info(f"Twilight times: Cache file exists.")

        with open(twilight_times_file, 'r') as openfile:
            twilight_times = json.load(openfile)

        # Check if cached data is for today.
        if (twilight_times["Today's Date"] == current_date_formatted):
            logger.info(f"Twilight times: Cache file is current, using cache file.")
        else:
            logger.info(f"Twilight times: Cache file out of date, updating cache file.")

            # Use lat and lon from the cache file
            latitude = str(twilight_times["Latitude"])
            longitude = str(twilight_times["Longitude"])

            # Update the cache file
            twilight_times = update_twilight_times(latitude, longitude)
    else:
        logger.info(f"Twilight times: Cache file doesn't exists, creating cache file.")
        # Update the cache file
        twilight_times = update_twilight_times()

    return twilight_times


def check_api_state(telescope_id):
    if telescope_id == 0:
        return True
    url = f"{base_url}/api/v1/telescope/{telescope_id}/connected?ClientID=1&ClientTransactionID=999"
    try:
        r = requests.get(url, timeout=Config.timeout)
        r.raise_for_status()
        response = r.json()
        if response.get("ErrorNumber") == 1031 or not response.get("Value"):
            logger.warn(f"Telescope {telescope_id} API is not connected. {url=}")
            return False
    except requests.exceptions.ConnectionError:
        logger.warn(f"Telescope {telescope_id} API is not online. (ConnectionError) {url=}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warn(f"Telescope {telescope_id} API is not online. (RequestException) {url=}")
        return False
    else:
        logger.debug(f"Telescope {telescope_id} API is online.")
        return True


def check_internet_connection():
    try:
        requests.get("https://github.com/smart-underworld/seestar_alp", timeout=2.0)
        logger.info(f"Internet connection detected.")
        return True
    except requests.exceptions.ConnectionError:
        logger.info(f"Unable to detect Internet connection or github is down.")  # or github is down...
        return False


def queue_action(dev_num, payload):
    global queue

    if dev_num not in queue:
        queue[dev_num] = []

    queue[dev_num].append(payload)

    return []


def do_action_device(action, dev_num, parameters, is_schedule=False):
    url = f"{base_url}/api/v1/telescope/{dev_num}/action"
    payload = {
        "Action": action,
        "Parameters": json.dumps(parameters),
        "ClientID": 1,
        "ClientTransactionID": 999
    }
    if check_api_state(dev_num):
        try:
            r = requests.put(url, json=payload, timeout=Config.timeout)
            return r.json()
        except Exception as e:
            logger.error(f"do_action_device: Failed to send action to device {dev_num}: {e}: message={payload}")

    if is_schedule:
        queue_action(dev_num, payload)


def do_schedule_action_device(action, parameters, dev_num):
    if parameters:
        return do_action_device("add_schedule_item", dev_num, {
            "action": action,
            "params": parameters
        }, True)
    else:
        return do_action_device("add_schedule_item", dev_num, {
            "action": action
        }, True)


def check_response(resp, response):
    v = response["Value"]
    if isinstance(v, str):
        flash(resp, v)
    elif response["ErrorMessage"] != '':
        flash(resp, response["ErrorMessage"])
        # flash("Schedule item added successfully", "success")
    else:
        flash(resp, "Item scheduled successfully")


def method_sync(method, telescope_id=1, **kwargs):
    out = do_action_device("method_sync", telescope_id, {"method": method, **kwargs})
    # print(f"method_sync {out=}")

    def err_extractor(obj):
        if obj and obj.get("error"):
            return obj["error"]
        elif obj:
            return obj["result"]

    if out:
        value = out.get("Value")
        if telescope_id == 0:
            results = {}
            for tel in get_telescopes():
                devnum = str(tel.get("device_num"))
                dev_value = value.get(devnum) if value else None
                results[devnum] = err_extractor(dev_value)
                if results[devnum] is None:
                    results[devnum] = "Offline"
        else:
            results = err_extractor(value) if value else "Offline"
        return results
    return None

def get_device_state(telescope_id):
    if check_api_state(telescope_id):
        # print("Device is online", telescope_id)
        result = method_sync("get_device_state", telescope_id)
        status = method_sync("get_view_state", telescope_id)
        wifi_status = method_sync("pi_station_state", telescope_id)
        view_state = "Idle"
        mode = ""
        stage = ""
        wifi_signal = ""
        device = ""
        focuser = ""
        settings = ""
        pi_status = ""
        free_storage = ""
        target = ""
        stacked = ""
        failed = ""
        if status is not None and status.get("View"):
            view_state = status["View"]["state"]
            mode = status["View"]["mode"]
            if view_state == "working":
                stage = status["View"]["stage"]           
                if stage == "Stack":
                    if status["View"]["Stack"]["state"] == "working":
                        target = status["View"]["target_name"]
                        stacked = status["View"]["Stack"]["stacked_frame"]
                        failed = status["View"]["Stack"]["dropped_frame"]
                 
        # Check for bad data
        if status is not None and result is not None:
            schedule = do_action_device("get_schedule", telescope_id, {})
            if result is not None:
                device = result.get("device",{})
                focuser = result.get("focuser",{})
                settings = result.get("setting",{})
                pi_status = result.get("pi_status",{})
                storage = result.get("storage", {}).get("storage_volume", [{}])[0]
                if storage.get("state") == "mounted":
                    free_storage = humanize.naturalsize(storage.get("freeMB",0) * 1024 * 1024)
                elif  storage.get("state") == "connected":
                    free_storage = "Unavailable while in USB storage mode."
            if wifi_status is not None:
                if wifi_status["server"]:  # sig_lev is only there while in station mode.
                    wifi_signal = f"{wifi_status['sig_lev']} dBm"
                else:
                    wifi_signal = f"Unavailable in AP mode."
            stats = {
                "Firmware Version": device["firmware_ver_string"],
                "Focal Position": focuser["step"],
                "Auto Power Off": settings["auto_power_off"],
                "Heater?": settings["heater_enable"],
                "Free Storage": free_storage,
                "Balance Sensor (angle)": result["balance_sensor"]["data"]["angle"],
                "Compass Sensor (direction)": result["compass_sensor"]["data"]["direction"],
                "Temperature Sensor": pi_status["temp"],
                "Charge Status": pi_status["charger_status"],
                "Battery %": pi_status["battery_capacity"],
                "Battery Temp": pi_status["battery_temp"],
                "Scheduler Status": schedule["Value"]["state"],
                "View State": view_state,
                "View Mode": mode,
                "View Stage": stage,
                "Target Name": target,
                "Succesful Frames": stacked,
                "Failed Frames": failed,
                "Wi-Fi Signal": wifi_signal,
            }
        else:
            logger.info(f"Stats: Unable to get data.")
            stats = {"Info": "Unable to get stats."}  # Display information for the stats page VS blank page.
    else:
        # print("Device is OFFLINE", telescope_id)
        stats = {}
    return stats


def get_device_settings(telescope_id):
    if telescope_id == 0:
        telescopes = get_telescopes()
        if len(telescopes) > 0:
            telescope_id = telescopes[0]["device_num"]

    settings_result = method_sync("get_setting", telescope_id)
    stack_settings_result = method_sync("get_stack_setting", telescope_id)

    settings = {
        "stack_dither_pix": settings_result["stack_dither"]["pix"],
        "stack_dither_interval": settings_result["stack_dither"]["interval"],
        "stack_dither_enable": settings_result["stack_dither"]["enable"],
        "exp_ms_stack_l": settings_result["exp_ms"]["stack_l"],
        "exp_ms_continuous": settings_result["exp_ms"]["continuous"],
        "save_discrete_ok_frame": stack_settings_result["save_discrete_ok_frame"],
        "save_discrete_frame": stack_settings_result["save_discrete_frame"],
        "light_duration_min": stack_settings_result["light_duration_min"],
        "auto_3ppa_calib": settings_result["auto_3ppa_calib"],
        "frame_calib": settings_result["frame_calib"],
        "stack_masic": settings_result["stack_masic"],
        # "rec_stablzn": settings_result["rec_stablzn"], # Unavailable for firmware 3.11
        "manual_exp": settings_result["manual_exp"],
        # "isp_exp_ms": settings_result["isp_exp_ms"],
        # "calib_location": settings_result["calib_location"],
        # "wide_cam": settings_result["wide_cam"],
        # "temp_unit": settings_result["temp_unit"],
        "focal_pos": settings_result["focal_pos"],
        # "factory_focal_pos": settings_result["factory_focal_pos"],
        "heater_enable": settings_result["heater_enable"],
        "auto_power_off": settings_result["auto_power_off"],
        "stack_lenhance": settings_result["stack_lenhance"]
    }

    return settings


def get_telescopes_state():
    telescopes = get_telescopes()

    return list(map(lambda telescope: telescope | {"stats": get_device_state(telescope["device_num"])}, telescopes))


def get_queue(telescope_id):
    parameters_list = []
    if telescope_id in queue:
        for item in queue[telescope_id]:
            parameters_list.append(json.loads(item['Parameters']))
        return parameters_list
    else:
        return []


def process_queue(resp, telescope_id):
    if check_api_state(telescope_id):
        parameters_list = []
        for command in queue[telescope_id]:
            parameters_list.append(json.loads(command['Parameters']))
        for param in parameters_list:
            action = param['action']
            if param['params']:
                params = param['params']
            else:
                params = None
            logger.info("POST scheduled request %s %s", action, params)
            response = do_schedule_action_device(action, params, telescope_id)
            logger.info("GET response %s", response)
    else:
        flash(resp,
              "ERROR: Seestar ALP API is Offline, Please ensure your Seestar is powered on and device/app.py is running.")


def check_ra_value(raString):
    valid = [
        r"^\d+h\s*\d+m\s*([0-9.]+s)?$",
        r"^\d+(\.\d+)?$",
        r"^\d+\s+\d+\s+[0-9.]+$",
        r"^[+-]?([0-9]*[.])?[0-9]+$"
    ]
    return any(re.search(pattern, raString) for pattern in valid)


def check_dec_value(decString):
    valid = [
        r"^[+-]?\d+d\s*\d+m\s*([0-9.]+s)?$",
        r"^[+-]?\d+(\.\d+)?$",
        r"^[+-]?\d+\s+\d+\s+[0-9.]+$",
        r"^[+-]?([0-9]*[.])?[0-9]+$"
    ]
    return any(re.search(pattern, decString) for pattern in valid)

def hms_to_sec(timeString):
    hms_search = re.search(r"^(?!\s*$)\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?\s*$", timeString.lower())

    # Check if convertion is needed.
    if hms_search:
        seconds = 0
        # Convert to sec
        hms_split = re.split(r"^(?!\s*$)\s*(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?\s*$", timeString.lower())
        if hms_split[1] is not None:
            # h
            seconds = int(hms_split[1]) * 3600
        if hms_split[2] is not None:
            # m
            seconds = seconds + int(hms_split[2]) * 60
        if hms_split[3] is not None:
            # s
            seconds = seconds + int(hms_split[3])
        return seconds
    else:
        return timeString
    


def do_create_mosaic(req, resp, schedule, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra, raPanels = form["ra"], form["raPanels"]
    dec, decPanels = form["dec"], form["decPanels"]
    panelOverlap = form["panelOverlap"]
    panelSelect = form["panelSelect"]
    useJ2000 = form.get("useJ2000") == "on"
    sessionTime = hms_to_sec(form["sessionTime"])
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec,
        "is_use_lp_filter": useLpfilter,
        "session_time_sec": int(sessionTime),
        "ra_num": int(raPanels),
        "dec_num": int(decPanels),
        "panel_overlap_percent": int(panelOverlap),
        "selected_panels": panelSelect,
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus
    }
    if telescope_id == 0:
        splitMosaic = form.get("array_mode")
        if splitMosaic:
            values["array_mode"] = splitMosaic
    if not check_ra_value(ra):
        flash(resp, "Invalid RA value")
        errors["ra"] = ra

    if not check_dec_value(dec):
        flash(resp, "Invalid DEC Value")
        errors["dec"] = dec

    if errors:
        flash(resp, "ERROR detected in Coordinates")
        return values, errors

    if schedule:
        response = do_schedule_action_device("start_mosaic", values, telescope_id)
        logger.info("POST scheduled request %s %s", values, response)
        if online:
            check_response(resp, response)
    else:
        response = do_action_device("start_mosaic", telescope_id, values, False)
        logger.info("POST immediate request %s %s", values, response)

    return values, errors


def do_create_image(req, resp, schedule, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra, raPanels = form["ra"], 1
    dec, decPanels = form["dec"], 1
    panelOverlap = 100
    panelSelect = ""
    useJ2000 = form.get("useJ2000") == "on"
    sessionTime = hms_to_sec(form["sessionTime"])
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec,
        "is_use_lp_filter": useLpfilter,
        "session_time_sec": int(sessionTime),
        "ra_num": int(raPanels),
        "dec_num": int(decPanels),
        "panel_overlap_percent": int(panelOverlap),
        "selected_panels": panelSelect,
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus
    }

    if not check_ra_value(ra):
        flash(resp, "Invalid RA value")
        errors["ra"] = ra

    if not check_dec_value(dec):
        flash(resp, "Invalid DEC Value")
        errors["dec"] = dec

    if errors:
        flash(resp, "ERROR detected in Coordinates")
        return values, errors

    # print("values:", values)
    if schedule:
        response = do_schedule_action_device("start_mosaic", values, telescope_id)
        logger.info("POST scheduled request %s %s", values, response)
        if online:
            check_response(resp, response)
    else:
        response = do_action_device("start_mosaic", telescope_id, values, False)
        logger.info("POST immediate request %s %s", values, response)

    return values, errors

def do_goto_target(req, resp, schedule, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra = form["ra"]
    dec = form["dec"]
    useJ2000 = form.get("useJ2000") == "on"
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec
    }

    if not check_ra_value(ra):
        flash(resp, "Invalid RA value")
        errors["ra"] = ra

    if not check_dec_value(dec):
        flash(resp, "Invalid DEC Value")
        errors["dec"] = dec

    if errors:
        flash(resp, "ERROR detected in Coordinates")
        return values, errors

    response = do_action_device("goto_target", telescope_id, values)
    logger.info("POST immediate request %s %s", values, response)

    return values, errors


def do_command(req, resp, telescope_id):
    form = req.media
    # print("Form: ", form)
    value = form.get("command","").strip()
    # print ("Selected command: ", value)
    match value:
        case "start_up_sequence":
            lat = form.get("lat","").strip()
            long = form.get("long","").strip()
            #print(f"action_start_up_sequence - Latitude {lat} Longitude {long}")
            if not lat or not long:
                output = do_action_device("action_start_up_sequence", telescope_id, {})
            else:
                output = do_action_device("action_start_up_sequence", telescope_id, {"lat": lat, "lon": long})
            return None
        case "scope_park":
            output = method_sync("scope_park", telescope_id)
            return None
        case "scope_move_to_horizon":
            output = method_sync("scope_move_to_horizon", telescope_id)
            return None
        case "pi_reboot":
            output = method_sync("pi_reboot", telescope_id)
            return None
        case "pi_shutdown":
            output = method_sync("pi_shutdown", telescope_id)
            return None
        case "start_auto_focus":
            output = method_sync("start_auto_focuse", telescope_id)
            return None
        case "stop_auto_focus":
            output = method_sync("stop_auto_focuse", telescope_id)
            return None
        case "get_focuser_position":
            output = method_sync("get_focuser_position", telescope_id)
            return output
        case "get_last_focuser_position":
            output = method_sync("get_focuser_position", telescope_id)
            return output
        case "start_solve":
            output = method_sync("start_solve", telescope_id)
            return None
        case "get_solve_result":
            output = method_sync("get_solve_result", telescope_id)
            return output
        case "get_last_solve_result":
            output = method_sync("get_last_solve_result", telescope_id)
            return output
        case "get_wheel_position":
            output = method_sync("get_wheel_position", telescope_id)
            return output
        case "get_wheel_state":
            output = method_sync("get_wheel_state", telescope_id)
            return output
        case "get_wheel_setting":
            output = method_sync("get_wheel_setting", telescope_id)
            return output
        case "set_wheel_position_LP":
            output = method_sync("set_wheel_position", telescope_id, params=[2])
            return output
        case "set_wheel_position_IR_Cut":
            output = method_sync("set_wheel_position", telescope_id, params=[1])
            return output
        case "set_wheel_position_Dark":
            output = method_sync("set_wheel_position", telescope_id, params=[0])
            return output
        case "start_polar_align":
            output = method_sync("start_polar_align", telescope_id)
            return output
        case "stop_polar_align":
            output = method_sync("stop_polar_align", telescope_id)
            return output
        case "start_create_dark":
            output = method_sync("start_create_dark", telescope_id)
            return output
        case "stop_create_dark":
            output = method_sync("stop_create_dark", telescope_id)
            return output
        case "pi_get_ap":
            output = method_sync("pi_get_ap", telescope_id)
            return output
        case "get_app_setting":
            output = method_sync("get_app_setting", telescope_id)
            return output
        case "iscope_get_app_state":
            output = method_sync("iscope_get_app_state", telescope_id)
            return output
        case "get_camera_exp_and_bin":
            output = method_sync("get_camera_exp_and_bin", telescope_id)
            return output
        case "get_camera_state":
            output = method_sync("get_camera_state", telescope_id)
            return output
        case "get_controls":
            output = method_sync("get_controls", telescope_id)
            return output
        case "get_disk_volume":
            output = method_sync("get_disk_volume", telescope_id)
            return output
        case "get_image_save_path":
            output = method_sync("get_image_save_path", telescope_id)
            return output
        case "get_img_name_field":
            output = method_sync("get_img_name_field", telescope_id)
            return output
        case "get_setting":
            output = method_sync("get_setting", telescope_id)
            return output
        case "get_stack_info":
            output = method_sync("get_stack_info", telescope_id)
            return output
        case "get_test_setting":
            output = method_sync("get_test_setting", telescope_id)
            return output
        case "get_user_location":
            output = method_sync("get_user_location", telescope_id)
            return output
        case "get_view_state":
            output = method_sync("get_view_state", telescope_id)
            return output
        case "scope_get_equ_coord":
            output = method_sync("scope_get_equ_coord", telescope_id)
            return output
        case "scope_get_horiz_coord":
            output = method_sync("scope_get_horiz_coord", telescope_id)
            return output
        case "scope_get_ra_dec":
            output = method_sync("scope_get_ra_dec", telescope_id)
            return output
        case _:
            logger.warn("No command found: %s", value)
    # print ("Output: ", output)

def do_support_bundle(req, telescope_id = 1):
    zip_buffer = io.BytesIO()
    desc = req.media["desc"]
    logger.debug("XXXXX getting logs (starting)")
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        # Add logs
        cwd = Path(os.getcwd())
        pfx = cwd.joinpath(Config.log_prefix)
        if pfx == "":
            pfx = "."
        for f in list(pfx.glob("alpyca.log*")):
            fstr=str(f)
            logger.debug(f"do_support_bundle: Adding {fstr} to zipfile")
            with open(str(fstr), "rb") as fh:
                buf = io.BytesIO(fh.read())
                zip_file.writestr(fstr, buf.getvalue())

        for f in list(pfx.joinpath("device").glob("config.toml*")):
            fstr=str(f)
            logger.debug(f"do_support_bundle: Adding {fstr} to zipfile")
            with open(str(fstr), "rb") as fh:
                buf = io.BytesIO(fh.read())
                zip_file.writestr(fstr, buf.getvalue())

        zip_file.writestr("problem_description.txt", desc)

        os_name = platform.system()
        zip_file.writestr("OS_name.txt", os_name)

        if os_name == "Linux":
            cmd_result = subprocess.check_output(['journalctl', '-u', 'seestar'])
            zip_file.writestr("service_journal.txt", cmd_result)
        if os_name == "Darwin" or os_name == "Linux":
            cmd_result = subprocess.check_output(['pip3', 'freeze'])
            zip_file.writestr("pip3_info.txt", cmd_result)
            cmd_result = subprocess.check_output(['python3', '--version'])
            zip_file.writestr("python_version.txt", cmd_result)
            cmd_result = subprocess.check_output(['env'])
            zip_file.writestr("env.txt", cmd_result)
            #if os.path.isdir('.git'):
            #    cmd_result = subprocess.check_output(['git', 'log', '-n', '1'])
            #    zip_file.writestr("git_version.txt", cmd_result)
        # TODO: Add Windows specific things here

        if telescope_id in telescope.seestar_logcollector:
            dev_log = telescope.get_seestar_logcollector(telescope_id)
            zip_data = dev_log.get_logs_sync()
            zip_file.writestr(f"seestar_{telescope_id}_logs.zip", zip_data)

    return zip_buffer


def redirect(location):
    raise HTTPFound(location)
    # raise HTTPTemporaryRedirect(location)


def fetch_template(template_name):
    if getattr(sys, "frozen", False):
        ## RWR Testing
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        logger.debug(template_dir)
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template(template_name)
        ## RWR
    else:
        template = Environment(
            loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates'))).get_template(template_name)
    return template


def render_template(req, resp, template_name, **context):
    template = fetch_template(template_name)
    resp.status = falcon.HTTP_200
    resp.content_type = 'text/html'
    webui_theme = Config.uitheme
    version = Version.app_version()

    resp.text = template.render(flashed_messages=get_flash_cookie(req, resp),
                                messages=get_messages(),
                                webui_theme=webui_theme,
                                version=version,
                                **context)


def render_schedule_tab(req, resp, telescope_id, template_name, tab, values, errors):
    if check_api_state(telescope_id):
        get_schedule = do_action_device("get_schedule", telescope_id, {})
        if get_schedule == None:
            return
        schedule = get_schedule["Value"]
    else:
        schedule = {"list": get_queue(telescope_id)}

    if (Config.twilighttimes):
        twilight_times = get_twilight_times()
    else:
        twilight_times = {}

    context = get_context(telescope_id, req)
    render_template(req, resp, template_name, schedule=schedule, tab=tab, errors=errors, values=values,
                    twilight_times=twilight_times, twilight_times_enabled=Config.twilighttimes, clear_sky_href=Config.clear_sky_href, clear_sky_img_src=Config.clear_sky_img_src,
                    **context)


FIXED_PARAMS_KEYS = ["local_time", "timer_sec", "try_count", "target_name", "is_j2000", "ra", "dec", "is_use_lp_filter",
                     "session_time_sec", "ra_num", "dec_num", "panel_overlap_percent", "gain", "is_use_autofocus", "heater", "nokey", "selected_panels"]


def export_schedule(telescope_id):
    if check_api_state(telescope_id):
        current = do_action_device("get_schedule", telescope_id, {})
        schedule = current["Value"]["list"]
    else:
        schedule = get_queue(telescope_id)

    # Parse the JSON data
    list_to_json = json.dumps(schedule)
    data = json.loads(list_to_json)

    # Define the fieldnames (column names)
    fieldnames = ['action'] + FIXED_PARAMS_KEYS

    # use an in-memory file-like object
    output = io.StringIO()

    # create writer object
    writer = csv.DictWriter(output, fieldnames=fieldnames)

    # Write the header
    writer.writeheader()

    # Write the rows
    for entry in data:
        row = OrderedDict({'action': entry['action']})
        if 'params' in entry and isinstance(entry['params'], dict):
            for key in FIXED_PARAMS_KEYS:
                row[key] = entry['params'].get(key, '')
        else:
            # If 'params' key is missing, ensure all fixed params are empty
            row['nokey'] = ''
        writer.writerow(row)

    output.seek(0)
    return output.getvalue()


def str2bool(v):
    return str(v).lower() in ("yes", "y", "true", "t", "1")


def import_schedule(input, telescope_id):
    for line in input:
        fields = line.split(',')
        
        # Check if the line has the expected number of fields
        if len(fields) != 18:
            continue
            
        (action, local_time, timer_sec, try_count, target_name, is_j2000, ra, dec, is_use_lp_filter, session_time_sec, ra_num, dec_num, panel_overlap_percent, gain, is_use_autofocus, heater, nokey, selected_panels) = fields
      
        match action:
            case "action":
                pass
            case "wait_until":
                do_schedule_action_device("wait_until", {"local_time": local_time}, telescope_id)
            case "wait_for":
                do_schedule_action_device("wait_for", {"timer_sec": int(timer_sec)}, telescope_id)
            case "auto_focus":
                do_schedule_action_device("auto_focus", {"try_count": int(try_count)}, telescope_id)
            case "start_mosaic":
                do_schedule_action_device("start_mosaic",
                                          {"target_name": target_name,
                                           "ra": ra,
                                           "dec": dec,
                                           "is_j2000": str2bool(is_j2000),
                                           "is_use_lp_filter": str2bool(is_use_lp_filter),
                                           "is_use_autofocus": str2bool(is_use_autofocus),
                                           "session_time_sec": int(session_time_sec),
                                           "ra_num": int(ra_num),
                                           "dec_num": int(dec_num),
                                           "panel_overlap_percent": int(panel_overlap_percent),
                                           "gain": int(gain), 
                                           "selected_panels": selected_panels}, int(telescope_id))
            case "shutdown":
                do_schedule_action_device("shutdown", "", telescope_id)
            case 'set_wheel_position':
                int_nokey = int(nokey[1])
                if int_nokey == 2:
                    cmd_vals = [2]
                else:
                    cmd_vals = [1]
                do_schedule_action_device("set_wheel_position", cmd_vals, telescope_id)
            case 'action_set_dew_heater':
                do_schedule_action_device("action_set_dew_heater", {"heater": int(heater)}, telescope_id)
            case '_':
                pass


class HomeResource:
    @staticmethod
    def on_get(req, resp):
        now = datetime.now()
        telescopes = get_telescopes_state()
        telescope = telescopes[0]  # We just force it to first telescope
        context = get_context(telescope['device_num'], req)
        del context["telescopes"]
        if len(telescopes) > 1:
            redirect(f"/{telescope['device_num']}/")
        else:
            root = get_root(telescope['device_num'])
            render_template(req, resp, 'index.html', now=now, telescopes=telescopes, **context) # pylint: disable=repeated-keyword


class HomeTelescopeResource:
    @staticmethod
    def on_get(req, resp, telescope_id):
        now = datetime.now()
        telescopes = get_telescopes_state()
        context = get_context(telescope_id, req)
        del context["telescopes"]
        render_template(req, resp, 'index.html', now=now, telescopes=telescopes, **context) # pylint: disable=repeated-keyword


class ImageResource:
    def on_get(self, req, resp, telescope_id=0):
        self.image(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_create_image(req, resp, False, telescope_id)
        self.image(req, resp, values, errors, telescope_id)

    @staticmethod
    def image(req, resp, values, errors, telescope_id):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]
            schedule = current["Value"]
        else:
            state = "Stopped"
            schedule = {"list": get_queue(telescope_id)}
        context = get_context(telescope_id, req)
        # remove values=values to stop remembering values
        render_template(req, resp, 'image.html', state=state, schedule=schedule, values=values, errors=errors,
                        action=f"/{telescope_id}/image", **context)

class GotoResource:  
    def on_get(self, req, resp, telescope_id=0):
        values = {}
        self.goto(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_goto_target(req, resp, True, telescope_id)
        self.goto(req, resp, values, errors, telescope_id)

    @staticmethod
    def goto(req, resp, values, errors, telescope_id):
        schedule = {}
        if check_api_state(telescope_id):            
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]
        else:
            state = "Stopped"
        context = get_context(telescope_id, req)
        # remove values=values to stop remembering values
        render_template(req, resp, 'goto.html', state=state, schedule=schedule, values=values, errors=errors, action=f"/{telescope_id}/goto", **context)


class CommandResource:
    def on_get(self, req, resp, telescope_id=0):
        self.command(req, resp, telescope_id, {})

    def on_post(self, req, resp, telescope_id=0):
        output = do_command(req, resp, telescope_id)
        self.command(req, resp, telescope_id, output)

    @staticmethod
    def command(req, resp, telescope_id, output):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            if current == None:
                return
            schedule = current["Value"]
            state = schedule["state"]
            
        else:
            schedule = {"list": get_queue(telescope_id)}
            state = "Stopped"

        context = get_context(telescope_id, req)

        render_template(req, resp, 'command.html', state=state, schedule=schedule, action=f"/{telescope_id}/command",
                        output=output, **context)


class MosaicResource:
    def on_get(self, req, resp, telescope_id=0):
        self.mosaic(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_create_mosaic(req, resp, False, telescope_id)
        self.mosaic(req, resp, values, errors, telescope_id)

    @staticmethod
    def mosaic(req, resp, values, errors, telescope_id):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]
            schedule = current["Value"]
        else:
            state = "Stopped"
            schedule = {"list": get_queue(telescope_id)}
        context = get_context(telescope_id, req)
        # remove values=values to stop remembering values
        render_template(req, resp, 'mosaic.html', state=state, schedule=schedule, values=values, errors=errors,
                        action=f"/{telescope_id}/mosaic", **context)


class ScheduleResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_until.html', 'wait-until', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_until.html', 'wait-until', {}, {})


class ScheduleListResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        if check_api_state(telescope_id):
            get_schedule = do_action_device("get_schedule", telescope_id, {})
            current_queue_list = get_queue(telescope_id)
            if get_schedule == None:
                #todo seems like SSC tries to connect to daemon before it is ready for the Federation device, and thus raise exception here. 
                # will return without any action for now
                return
            else:
                current_schedule_list = get_schedule["Value"]["list"]
            # Check to see if there are missing items on the schedule
            if len(current_queue_list) > 0 and len(current_schedule_list) == 0:
                logger.info(f"Telescope {telescope_id}: Queue has items but schedule does not, processing queue.")
                # Process missing items from schedule
                process_queue(resp, telescope_id)
                get_schedule = do_action_device("get_schedule", telescope_id, {})
            schedule = get_schedule["Value"]
        else:
            schedule = {"list": get_queue(telescope_id)}

        context = get_context(telescope_id, req)
        render_template(req, resp, 'schedule_list.html', schedule=schedule, **context)


class ScheduleWaitUntilResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_until.html', 'wait-until', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        waitUntil = req.media["waitUntil"]
        response = do_schedule_action_device("wait_until", {"local_time": waitUntil}, telescope_id)
        logger.info("POST scheduled request %s", response)
        if check_api_state(telescope_id):
            check_response(resp, response)
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_until.html', 'wait-until', {}, {})


class ScheduleWaitForResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_for.html', 'wait-for', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        waitFor = req.media["waitFor"]
        response = do_schedule_action_device("wait_for", {"timer_sec": int(waitFor)}, telescope_id)
        logger.info("POST scheduled request %s", response)
        if check_api_state(telescope_id):
            check_response(resp, response)
        render_schedule_tab(req, resp, telescope_id, 'schedule_wait_for.html', 'wait-for', {}, {})


class ScheduleAutoFocusResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_auto_focus.html', 'auto-focus', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        autoFocus = req.media["autoFocus"]
        response = do_schedule_action_device("auto_focus", {"try_count": int(autoFocus)}, telescope_id)
        logger.info("POST scheduled request %s", response)
        if check_api_state(telescope_id):
            check_response(resp, response)
        render_schedule_tab(req, resp, telescope_id, 'schedule_auto_focus.html', 'auto-focus', {}, {})


class ScheduleGoOnlineResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        referer = req.get_header('Referer')
        logger.info(f"Referer: {referer}")
        process_queue(resp, telescope_id)
        redirect(f"{referer}")


class ScheduleImageResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_image.html', 'image', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        values, errors = do_create_image(req, resp, True, telescope_id)
        render_schedule_tab(req, resp, telescope_id, 'schedule_image.html', 'image', values, errors)


class ScheduleMosaicResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_mosaic.html', 'mosaic', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        values, errors = do_create_mosaic(req, resp, True, telescope_id)
        render_schedule_tab(req, resp, telescope_id, 'schedule_mosaic.html', 'mosaic', values, errors)


class ScheduleShutdownResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_shutdown.html', 'shutdown', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        response = do_schedule_action_device("shutdown", "", telescope_id)
        if check_api_state(telescope_id):
            check_response(resp, response)
        render_schedule_tab(req, resp, telescope_id, 'schedule_shutdown.html', 'shutdown', {}, {})


class ScheduleLpfResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_lpf.html', 'lpf', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        form = req.media
        useLpfilter = form.get("lpf") == "on"
        if useLpfilter:
            cmd_vals = [2]
        else:
            cmd_vals = [1]
        response = do_schedule_action_device("set_wheel_position", cmd_vals, telescope_id)
        render_schedule_tab(req, resp, telescope_id, 'schedule_lpf.html', 'lpf', {}, {})


class ScheduleDewHeaterResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        render_schedule_tab(req, resp, telescope_id, 'schedule_dew_heater.html', 'dew-heater', {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        form = req.media
        dewHeaterValue = form.get("dewHeaterValue")

        response = do_schedule_action_device("action_set_dew_heater", {"heater": int(dewHeaterValue)}, telescope_id)
        render_schedule_tab(req, resp, telescope_id, 'schedule_dew_heater.html', 'dew-heater', {}, {})


class ScheduleToggleResource:
    def on_get(self, req, resp, telescope_id=0):
        self.display_state(req, resp, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        current = do_action_device("get_schedule", telescope_id, {})
        state = current["Value"]["state"]
        if state == "Stopped":
            do_action_device("start_scheduler", telescope_id, {})
        else:
            do_action_device("stop_scheduler", telescope_id, {})
        self.display_state(req, resp, telescope_id)

    @staticmethod
    def display_state(req, resp, telescope_id):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]
        else:
            state = "Stopped"
        context = get_context(telescope_id, req)
        render_template(req, resp, 'partials/schedule_state.html', state=state, **context)


class ScheduleClearResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]

            if state == "Running":
                do_action_device("stop_scheduler", telescope_id, {})
                flash(resp, "Stopping scheduler")

            do_action_device("create_schedule", telescope_id, {})
            flash(resp, "Created New Schedule")
            redirect(f"/{telescope_id}/schedule")
        else:
            global queue
            queue = {}

        flash(resp, "Created New Schedule")
        redirect(f"/{telescope_id}/schedule")


class ScheduleExportResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        filename = req.media["filename"]
        if filename[-3:] != 'csv':
            filename = f'{filename}.csv'
        file_content = export_schedule(telescope_id)

        if file_content:
            resp.content_type = 'application/octet-stream'
            resp.append_header('Content-Disposition', f'attachment; filename="{filename}"')
            resp.data = file_content.encode('utf-8')
            resp.status = falcon.HTTP_200
        else:
            flash(resp, "No schedule to export")
            redirect(f"/{telescope_id}/schedule")


class ScheduleImportResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.get_media()
        for part in data:
            string_data = part.data.decode('utf-8').splitlines()
            filename = part.filename
        import_schedule(string_data, telescope_id)
        flash(resp, f"Schedule imported from {filename}.")
        redirect(f"/{telescope_id}/schedule")


class LivePage:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        status = method_sync('get_view_state', telescope_id)
        logger.info(status)
        context = get_context(telescope_id, req)
        now = datetime.now()
        render_template(req, resp, 'live.html', now=now, **context)


class LiveModeResource:
    def on_delete(self, req, resp, telescope_id=1):
        # shut off watch
        do_action_device("method_async", telescope_id,
                         {"method": "iscope_stop_view"})
        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = 'none'

    def on_post(self, req, resp, telescope_id=1):
        mode = req.media["mode"]
        # xxx: If mode is none, need to cancel things
        response = do_action_device("method_async", telescope_id,
                                    {"method": "iscope_start_view", "params": {"mode": mode}})
        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = mode


class LiveExposureModeResource:
    def on_post(self, req, resp, telescope_id=1):
        mode = req.media["exposure_mode"]
        # xxx: If mode is none, need to cancel things
        # response = do_action_device("method_async", telescope_id,
        #                             {"method": "iscope_start_view", "params": {"mode": mode}})
        print("changing mode to", mode)

        dev = telescope.get_seestar_imager(telescope_id)
        dev.set_exposure_mode(mode)

        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = mode


class LiveStatusResource:
    def __init__(self):
        self.stage = None
        self.mode = None
        self.state = None

    def on_get(self, req, resp, telescope_id=1):
        status = method_sync('get_view_state', telescope_id, id=42)
        state = "Idle"
        mode = ""
        stage = ""
        target_name = None
        view = None
        # Values of potential interest:
        #   tracking: boolean
        #   planet<underscore>correction: boolean
        #   manual<underscore>exp: boolean
        #   AutoFocus:
        #      position
        if status is not None:
            view = status.get('View')
        if view is not None:
            state = view.get("state")
            mode = view.get("mode")
            stage = view.get("stage")
            target_name = view.get("target_name")
        tm = datetime.now().strftime("%H:%M:%S")
        changed = self.stage != stage or self.mode != mode or self.state != state
        self.stage = stage
        self.state = state
        self.mode = mode

        # logger.info(f"on_get view: {view=}")

        # If status changes, trigger reload
        resp.status = falcon.HTTP_200
        resp.content_type = 'text/html'

        trigger = {"statusUpdate": {"mode": mode, "stage": stage}}
        if changed:
            trigger = trigger | {"liveViewModeChange": mode}

        resp.set_header('HX-Trigger', json.dumps(trigger))
        # if star:
        # .  target_name, gain, stacked_frame, dropped_frame
        # .  Exposure: { lapse_ms, exp_ms }
        template = fetch_template('live_status.html')
        stats = None

        if state == 'working' and mode == 'star' and stage == 'Stack' and view.get("Stack"):
            stack = view.get("Stack")
            target_name = target_name or stack.get("target_name")
            stats = {
                "gain": stack.get("gain"),
                "stacked_frame": stack.get("stacked_frame"),
                "dropped_frame": stack.get("dropped_frame"),
                "elapsed": str(timedelta(milliseconds=stack["lapse_ms"]))[:-3],
            }
        resp.text = template.render(tm=tm, state=state, mode=mode, stage=stage, stats=stats, target_name=target_name)
        # 'Annotate': {'state': 'complete', 'lapse_ms': 3370, 'result': {'image_size': [1080, 1920], 'annotations': [
        #    {'type': 'ngc', 'names': ['NGC 6992', 'C 33'], 'pixelx': 394.698, 'pixely': 611.487, 'radius': 757.869}],


# def status():
#     while True:
#         yield 'this is a test' + "\r\n"
#         time.sleep(5)


# class LiveStateResource:
#     def on_get(self, req, resp, telescope_id=1):
#         resp.content_type = 'text/plain'
#         resp.stream = status()


class SearchObjectResource:
    @staticmethod
    def on_post(req, resp):
        result_table = Simbad.query_object(req.media["q"])
        logger.info(result_table)
        if result_table and len(result_table) > 0:
            row = result_table[0]
            resp.media = {
                "name": row.get("MAIN_ID"),
                "ra": row.get("RA"),
                "dec": row.get("DEC"),
            }
        else:
            resp.media = {}


class SettingsResource:
    def on_get(self, req, resp, telescope_id=0):
        self.render_settings(req, resp, telescope_id, {})

    def on_post(self, req, resp, telescope_id=0):
        PostedSettings = req.media

        # Convert the form names back into the required format
        FormattedNewSettings = {
            "stack_lenhance": str2bool(PostedSettings["stack_lenhance"]),
            "stack_dither": {"pix": int(PostedSettings["stack_dither_pix"]),
                             "interval": int(PostedSettings["stack_dither_interval"]),
                             "enable": str2bool(PostedSettings["stack_dither_enable"])},
            "exp_ms": {"stack_l": int(PostedSettings["exp_ms_stack_l"]),
                       "continuous": int(PostedSettings["exp_ms_continuous"])},
            "focal_pos": int(PostedSettings["focal_pos"]),
            # "factory_focal_pos": int(PostedSettings["factory_focal_pos"]),
            "auto_power_off": str2bool(PostedSettings["auto_power_off"]),
            "auto_3ppa_calib": str2bool(PostedSettings["auto_3ppa_calib"]),
            "frame_calib": str2bool(PostedSettings["frame_calib"]),
            "stack_masic": str2bool(PostedSettings["stack_masic"]),
            # "rec_stablzn": str2bool(PostedSettings["rec_stablzn"]),
            "manual_exp": str2bool(PostedSettings["manual_exp"])
        }

        FormattedNewStackSettings = {
            "save_discrete_frame": str2bool(PostedSettings["save_discrete_frame"]),
            "save_discrete_ok_frame": str2bool(PostedSettings["save_discrete_ok_frame"]),
            "light_duration_min": int(PostedSettings["light_duration_min"])
        }

        # Dew Heater is wierd
        if (str2bool(PostedSettings["heater_enable"])):
            do_action_device("method_sync", telescope_id,
                             {'method': 'pi_output_set2', 'params': {'heater': {'state': True, 'value': 90}}})
        else:
            do_action_device("method_sync", telescope_id,
                             {'method': 'pi_output_set2', 'params': {'heater': {'state': False, 'value': 90}}})

        settings_output = do_action_device("method_async", telescope_id,
                                           {"method": "set_setting", "params": FormattedNewSettings})
        stack_settings_output = do_action_device("method_async", telescope_id,
                                                 {"method": "set_stack_setting", "params": FormattedNewStackSettings})

        if (settings_output["ErrorNumber"] or stack_settings_output["ErrorNumber"]):
            output = "Error Updating Settings."
        else:
            output = "Successfully Updated Settings."

        # Delay for LP filter on (off doesn't need a delay), this is helpful for rendering the current status on page refresh.
        if (FormattedNewSettings["stack_lenhance"]):
            wheel_state = method_sync("get_wheel_state", telescope_id)
            if wheel_state is not None:
                while wheel_state["state"] != "idle":
                    time.sleep(0.1)  # Wait for the filter wheel to complete
                    wheel_state = method_sync("get_wheel_state", telescope_id)

        self.render_settings(req, resp, telescope_id, output)

    @staticmethod
    def render_settings(req, resp, telescope_id, output):
        settings = {}
        context = get_context(telescope_id, req)
        if telescope_id == 0:
            telescopes = get_telescopes()
            for tel in telescopes:
                tel_id = tel["device_num"]
                if check_api_state(tel_id):
                    settings = get_device_settings(tel_id)
                    break
        else:
            if check_api_state(telescope_id):
                settings = get_device_settings(telescope_id)
        # Maybe we can store this better?
        settings_friendly_names = {
            "stack_dither_pix": "Stack Dither Pixels",
            "stack_dither_interval": "Stack Dither Interval",
            "stack_dither_enable": "Stack Dither",
            "exp_ms_stack_l": "Stacking Exposure Length (ms)",
            "exp_ms_continuous": "Continuous Preview Exposure Length (ms)",
            "save_discrete_ok_frame": "Save Sub Frames",
            "save_discrete_frame": "Save Failed Sub Frames",
            "light_duration_min": "Light Duration Min",
            "auto_3ppa_calib": "Auto 3 Point Calibration",
            "frame_calib": "Frame Calibration",
            "stack_masic": "Stack Mosaic",
            "rec_stablzn": "Record Stabilization",
            "manual_exp": "Manual Exposure",
            "isp_exp_ms": "isp_exp_ms",
            "calib_location": "calib_location",
            "wide_cam": "Wide Cam",
            "temp_unit": "Temperature Unit",
            "focal_pos": "Focal Position - User Defined",
            "factory_focal_pos": "Default Focal Position",
            "heater_enable": "Dew Heater",
            "auto_power_off": "Auto Power Off",
            "stack_lenhance": "Light Pollution (LP) Filter"
        }
        # Maybe we can store this better?
        settings_helper_text = {
            "stack_dither_pix": "Dither by (x) pixels. Reset apon Seestar reboot.",
            "stack_dither_interval": "Dither every (x) sub frames. Reset apon Seestar reboot.",
            "stack_dither_enable": "Enable or disable dither. Reset apon Seestar reboot.",
            "exp_ms_stack_l": "Stacking Exposure Lenght (ms).",
            "exp_ms_continuous": "Continuous Preview Exposure Length (ms), used in the live view.",
            "save_discrete_ok_frame": "Save sub frames. (Doesn't include failed.)",
            "save_discrete_frame": "Save failed sub frames. (Failed sub frames will have \"_failed\" added to their filename.)",
            "light_duration_min": "Light Duration Min.",
            "auto_3ppa_calib": "Enable or disable 3 point calibration.",
            "frame_calib": "Frame Calibration",
            "stack_masic": "Stack Mosaic",
            "rec_stablzn": "Record Stabilization",
            "manual_exp": "Manual Exposure",
            "isp_exp_ms": "isp_exp_ms",
            "calib_location": "calib_location",
            "wide_cam": "Wide Cam",
            "temp_unit": "Temperature Unit",
            "focal_pos": "Focal Position - User Defined",
            "factory_focal_pos": "Default focal position on startup.",
            "heater_enable": "Enable or disable dew heater.",
            "auto_power_off": "Enable or disable auto power off",
            "stack_lenhance": "Enable or disable light pollution (LP) Filter."
        }
        render_template(req, resp, 'settings.html', settings=settings, settings_friendly_names=settings_friendly_names,
                        settings_helper_text=settings_helper_text, output=output, **context)


class StatsResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        if telescope_id == 0:
            stats = {}
        else:
            stats = get_device_state(telescope_id)
        now = datetime.now()
        context = get_context(telescope_id, req)

        render_template(req, resp, 'stats.html', stats=stats, now=now, **context)

class SupportResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        context = get_context(telescope_id, req)
        render_template(req, resp, 'support.html', **context)

class ReloadResource:
    @staticmethod
    def on_put(req, resp):
        pid = os.getpid()
        os.kill(pid, signal.SIGHUP)
        resp.status = falcon.HTTP_200

# stackoverflow-fu
Object = lambda **kwargs: type("Object", (), kwargs)


class SystemResource:
    def if_null(self, thread, name):
        if thread is None:
            return Object(name=name, is_alive=lambda:"n/a")
        else:
            return thread

    def on_get(self, req, resp, telescope_id=1):
        now = datetime.now()
        context = get_context(telescope_id, req)
        threads = []
        for tel in get_telescopes():
            telescope_id = tel["device_num"]
            telescope_name = tel["name"]
            imager = telescope.get_seestar_imager(telescope_id)
            dev = telescope.get_seestar_device(telescope_id)
            for t in (self.if_null(dev.get_msg_thread, f"ALPReceiveMessageThread.{telescope_name}"),
                      self.if_null(dev.heartbeat_msg_thread, f"ALPHeartbeatMessageThread.{telescope_name}"),
                      self.if_null(dev.scheduler_thread, f"SchedulerThread.{telescope_name}"),
                      self.if_null(dev.mosaic_thread, f"MosaicThread.{telescope_name}"),
                      self.if_null(imager.heartbeat_msg_thread, f"ImagingHeartbeatMessageThread.{telescope_name}"),
                      self.if_null(imager.get_stream_thread, f"ImagingStreamThread.{telescope_name}"),
                      self.if_null(imager.get_image_thread, f"ImagingReceiveImageThread.{telescope_name}"),
                      ):
                threads.append({
                    "name": t.name,
                    "running": t.is_alive(),
                    "last_run": getattr(t, "last_run", "n/a")
                })
        #for t in threading.enumerate():
        #    threads.append({
        #        "name": t.name,
        #        "running": t.is_alive(),
        #    })
        render_template(req, resp, 'system.html', now=now, threads=threads, **context)


class SimbadResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        objName = req.get_param('name')  # get the name to lookup from the request
        try:
            r = requests.get(simbad_url + objName)
        except:
            resp.status = falcon.HTTP_500
            resp.content_type = 'application/text'
            resp.text = 'Request had communications error.'
            return

        html_content = r.text

        # Find the start of the RA/Dec (J2000.0) information
        start_index = html_content.find("Coordinates(ICRS,ep=J2000,eq=2000):")

        # Find the end of the RA/Dec (J2000.0) information (end of the line)
        end_index = html_content.find("(", start_index + 13)  # "Coordinates(IC".count)   # skip past the first (

        ra_dec_j2000 = html_content[start_index:end_index]

        # Clean up the extracted information
        ra_dec_j2000 = ra_dec_j2000.replace("Coordinates(ICRS,ep=J2000,eq=2000):", "").strip()
        elements = re.split(r'\s+', ra_dec_j2000.strip())

        if (len(elements) < 6):
            resp.status = falcon.HTTP_404
            resp.content_type = 'application/text'
            resp.text = 'Object not found'
            return

        elements[2] = round(float(elements[2]),1)
        elements[5] = round(float(elements[5]),1)
        ra_dec_j2000 = f"{elements[0]}h{elements[1]}m{elements[2]}s {elements[3]}d{elements[4]}m{elements[5]}s"

        # see if we should recommand the LP Filter
        substrings = ["---  ISM  ---", "---  HII  ---", "---  SNR  ---", "---  PN  ---"]

        lpFilter = False
        for substring in substrings:
            if substring in html_content:
                lpFilter = True
                break
        lpStr = " off"
        if (lpFilter == True):
            lpStr = " on"

        ra_dec_j2000 += lpStr

        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = ra_dec_j2000
        return

class StellariumResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        try:
            r = requests.get(stellarium_url + '?format=json')
            html_content = r.text
        except:
            resp.status = falcon.HTTP_404
            resp.content_type = 'application/text'
            resp.text = 'Requst had communications error.'
            return
        StelJSON = json.loads(html_content)
        ra_j2000 = round(StelJSON['raJ2000'],3)
        dec_J2000 = round(StelJSON['decJ2000'],3)
        if (StelJSON['localized-name'] != "" ):
            objName = StelJSON['localized-name']
        elif (StelJSON['name'] != "" and objName != ""):
            objname = StelJSON['localized-name']
        else:
            tmpObj = StelJSON['designations']
            objName = tmpObj.split(" - ")[0]
        
        lpFilter = "off"
        objType = StelJSON['type']
        filterTypes = ["HII region", "emission nebula", "supernova remnant", "planetary nebula"]
        if objType in filterTypes:
            lpFilter = "on"
        
        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = str(ra_j2000) + "/" + str(dec_J2000) + "/" + lpFilter + "/" + objName


# class StellariumResource:
#     @staticmethod
#     def on_get(req, resp, telescope_id=1):
#         try:
#             r = requests.get(stellarium_url)
#             html_content = r.text
#         except:
#             resp.status = falcon.HTTP_404
#             resp.content_type = 'application/text'
#             resp.text = 'Requst had communications error.'
#             return

#         # Find the start of the RA/Dec (J2000.0) information
#         start_index = html_content.find("RA/Dec (J2000.0):")

#         # Find the end of the RA/Dec (J2000.0) information (end of the line)
#         end_index = html_content.find("<br/>", start_index)

#         # Extract the RA/Dec (J2000.0) information
#         ra_dec_j2000 = html_content[start_index:end_index]
#         ra_dec_j2000 = ra_dec_j2000.replace("Â°", "d").strip()
#         ra_dec_j2000 = ra_dec_j2000.replace("'", "m")
#         ra_dec_j2000 = ra_dec_j2000.replace('"', "s")

#         # Clean up the extracted information
#         ra_dec_j2000 = ra_dec_j2000.replace("RA/Dec (J2000.0):", "").strip()

#         substrings = ["Type: <b>HII region", "Type: <b>emission nebula", "Type: <b>supernova remnant",
#                       "Type: <b>planetary nebula"]

#         lpFilter = False
#         for substring in substrings:
#             if substring in html_content:
#                 lpFilter = True
#                 break
#         lpStr = "/off"
#         if (lpFilter == True):
#             lpStr = "/on"

#         ra_dec_j2000 += lpStr

#         resp.status = falcon.HTTP_200
#         resp.content_type = 'application/text'
#         resp.text = ra_dec_j2000


class TelescopePositionResource:
    def on_post(self, req, resp, telescope_id=1):
        form = req.media
        # print("position", form)

        distance = form.get('distance', 0)
        angle = form.get('angle', 0)
        force = form.get('force', 0)
        if distance == 0:
            do_action_device('method_sync', telescope_id,
                             {'method': 'scope_speed_move', 'params': {"speed": 0, "angle": 0, "dur_sec": 3}})
        else:
            speed = min(distance * 14.4 * force, 1440.0)
            # print("speed", speed)
            do_action_device('method_sync', telescope_id,
                             {'method': 'scope_speed_move',
                              'params': {"speed": speed, "angle": int(angle), "dur_sec": 3}})
            # do_action_device('scope_speed_move', telescope_id, {
            #     "speed": int(distance * 5), "angle": angle, "dur_sec": 1
            # })

        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = "Ok"


class ToggleUIThemeResource:
    @staticmethod
    def on_get(req, resp):
        if getattr(sys, "frozen", False):  # frozen means that we are running from a bundled app
            config_file = os.path.abspath(os.path.join(sys._MEIPASS, "config.toml"))
        else:
            config_file = os.path.join(os.path.dirname(__file__), "../device/config.toml")
        f = open(config_file, "r")
        fread = f.read()

        # Current uitheme value in memory
        Current_Theme = Config.uitheme
        if Current_Theme == "light":
            # Update variable that's stored in memory
            Config.uitheme = "dark"

            # Update uitheme in config.toml
            uitheme = fread.replace('uitheme = "light"', 'uitheme = "dark"')
        else:
            # Update variable that's stored in memory
            Config.uitheme = "light"

            # Update uitheme in config.toml
            uitheme = fread.replace('uitheme = "dark"', 'uitheme = "light"')

        # Write the updated config.toml file
        with open(config_file, "w") as f:
            f.write(uitheme)


class UpdateTwilightTimesResource:
    @staticmethod
    def on_post(req, resp):
        referer = req.get_header('Referer')
        PostedForm = req.media
        PostedLat = PostedForm["Latitude"]  # TODO: This should have some type of input check
        PostedLon = PostedForm["Longitude"]  # TODO: This should have some type of input check
        update_twilight_times(PostedLat, PostedLon)
        redirect(f"{referer}")

class GetBalanceSensorResource:
    @staticmethod
    def on_get(req, resp):
        referer = req.get_header('Referer')
        referersplit = referer.split("/")[-2:]
        telescope_id = int(referersplit[0])
        result = method_sync("get_device_state", telescope_id)
        if result is not None:
            balance_sensor = {
                "x": result["balance_sensor"]["data"]["x"],
                "y": result["balance_sensor"]["data"]["y"],
            }
            resp.status = falcon.HTTP_200
            resp.content_type = 'application/json'
            resp.text = json.dumps(balance_sensor)

class GenSupportBundleResource:
    @staticmethod
    def on_post(req, resp, telescope_id=1):
        zip_io = do_support_bundle(req, telescope_id)
        resp.content_type = 'application/zip'
        resp.status = falcon.HTTP_200
        resp.text = zip_io.getvalue()
        zip_io.close()

class LoggingWSGIRequestHandler(WSGIRequestHandler):
    """Subclass of  WSGIRequestHandler allowing us to control WSGI server's logging"""

    def log_message(self, format: str, *args):
        # if args[1] != '200':  # Log this only on non-200 responses
        logger.debug(f'{datetime.now()} {self.client_address[0]} <- {format % args}')


class GetPlanetCoordinates():
    @staticmethod
    def on_get(req, resp):
        # Load planetary ephemeris data
        pDataFile = load('de440s.bsp')
        earth = pDataFile['earth']

        planetName = req.get_param('planetname')

        # Load the current time
        ts = load.timescale()
        t = ts.now()
        # Choose the planet you want to observe
        planet = pDataFile[planetName]
        # Calculate the astrometric position
        astrometric = earth.at(t).observe(planet)
        # Using 'date' forces JNOW rather than ICRS or J2000
        ra, dec, distance = astrometric.radec('date')
        resp.status = falcon.HTTP_200
        resp.content_type = 'application/text'
        resp.text = (f"{ra}, {dec}")


class FrontMain:
    def __init__(self):
        self.httpd = None

    def start(self):
        """ Application startup"""

        app = falcon.App()
        app.add_route('/', HomeResource())
        app.add_route('/command', CommandResource())
        app.add_route('/goto', GotoResource())
        app.add_route('/image', ImageResource())
        app.add_route('/live', LivePage())
        app.add_route('/mosaic', MosaicResource())
        app.add_route('/position', TelescopePositionResource())
        app.add_route('/search', SearchObjectResource())
        app.add_route('/settings', SettingsResource())
        app.add_route('/schedule', ScheduleResource())
        app.add_route('/schedule/auto-focus', ScheduleAutoFocusResource())
        app.add_route('/schedule/clear', ScheduleClearResource())
        app.add_route('/schedule/export', ScheduleExportResource())
        app.add_route('/schedule/image', ScheduleImageResource())
        app.add_route('/schedule/import', ScheduleImportResource())
        app.add_route('/schedule/list', ScheduleListResource())
        app.add_route('/schedule/mosaic', ScheduleMosaicResource())
        app.add_route('/schedule/online', ScheduleGoOnlineResource())
        app.add_route('/schedule/shutdown', ScheduleShutdownResource())
        app.add_route('/schedule/lpf', ScheduleLpfResource())
        app.add_route('/schedule/dew-heater', ScheduleDewHeaterResource())
        app.add_route('/schedule/state', ScheduleToggleResource())
        app.add_route('/schedule/wait-until', ScheduleWaitUntilResource())
        app.add_route('/schedule/wait-for', ScheduleWaitForResource())
        app.add_route('/stats', StatsResource())
        app.add_route('/support', SupportResource())
        app.add_route('/reload', ReloadResource())
        app.add_route('/{telescope_id:int}/', HomeTelescopeResource())
        app.add_route('/{telescope_id:int}/goto', GotoResource())
        app.add_route('/{telescope_id:int}/command', CommandResource())
        app.add_route('/{telescope_id:int}/image', ImageResource())
        app.add_route('/{telescope_id:int}/live', LivePage())
        app.add_route('/{telescope_id:int}/live/status', LiveStatusResource())
        app.add_route('/{telescope_id:int}/live/mode', LiveModeResource())
        app.add_route('/{telescope_id:int}/live/exposure_mode', LiveExposureModeResource())
        # app.add_route('/{telescope_id:int}/live/state', LiveStateResource())
        app.add_route('/{telescope_id:int}/mosaic', MosaicResource())
        app.add_route('/{telescope_id:int}/position', TelescopePositionResource())
        app.add_route('/{telescope_id:int}/search', SearchObjectResource())
        app.add_route('/{telescope_id:int}/settings', SettingsResource())
        app.add_route('/{telescope_id:int}/schedule', ScheduleResource())
        app.add_route('/{telescope_id:int}/schedule/auto-focus', ScheduleAutoFocusResource())
        app.add_route('/{telescope_id:int}/schedule/clear', ScheduleClearResource())
        app.add_route('/{telescope_id:int}/schedule/export', ScheduleExportResource())
        app.add_route('/{telescope_id:int}/schedule/image', ScheduleImageResource())
        app.add_route('/{telescope_id:int}/schedule/import', ScheduleImportResource())
        app.add_route('/{telescope_id:int}/schedule/list', ScheduleListResource())
        app.add_route('/{telescope_id:int}/schedule/mosaic', ScheduleMosaicResource())
        app.add_route('/{telescope_id:int}/schedule/online', ScheduleGoOnlineResource())
        app.add_route('/{telescope_id:int}/schedule/shutdown', ScheduleShutdownResource())
        app.add_route('/{telescope_id:int}/schedule/lpf', ScheduleLpfResource())
        app.add_route('/{telescope_id:int}/schedule/dew-heater', ScheduleDewHeaterResource())
        app.add_route('/{telescope_id:int}/schedule/state', ScheduleToggleResource())
        app.add_route('/{telescope_id:int}/schedule/wait-until', ScheduleWaitUntilResource())
        app.add_route('/{telescope_id:int}/schedule/wait-for', ScheduleWaitForResource())
        app.add_route('/{telescope_id:int}/schedule', ScheduleResource())
        app.add_route('/{telescope_id:int}/stats', StatsResource())
        app.add_route('/{telescope_id:int}/support', SupportResource())
        app.add_route('/{telescope_id:int}/system', SystemResource())
        app.add_route('/{telescope_id:int}/gensupportbundle', GenSupportBundleResource())
        app.add_static_route("/public", f"{os.path.dirname(__file__)}/public")
        app.add_route('/simbad', SimbadResource())
        app.add_route('/stellarium', StellariumResource())
        app.add_route('/toggleuitheme', ToggleUIThemeResource())
        app.add_route('/updatetwilighttimes', UpdateTwilightTimesResource())
        app.add_route('/getbalancesensor', GetBalanceSensorResource())
        app.add_route('/gensupportbundle', GenSupportBundleResource())
        app.add_route('/getplanetcoordinates', GetPlanetCoordinates() )

        try:
            self.httpd = make_server(Config.ip_address, Config.uiport, app, handler_class=LoggingWSGIRequestHandler)
            logger.info(f'==STARTUP== Serving on {Config.ip_address}:{Config.uiport}. Time stamps are UTC.')

            # Print listening IP:Port to the console
            logger.info(f'SSC Started: http://{get_listening_ip()}:{Config.uiport}')

            # Check for internet connection
            global internet_connection
            internet_connection = check_internet_connection()

            # Serve until process is killed
            self.httpd.serve_forever()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt. Shutting down SSC.")
            # for dev in Config.seestars:
            #     telescope.end_seestar_device(dev['device_num'])
            if self.httpd:
                self.httpd.shutdown()

    def stop(self):
        # for dev in Config.seestars:
        #    telescope.end_seestar_device(dev['device_num'])
        if self.httpd:
            self.httpd.shutdown()


class style():
    YELLOW = '\033[33m'
    RESET = '\033[0m'


if __name__ == '__main__':
    print(style.YELLOW + "WARN")
    print(style.YELLOW + "WARN" + style.RESET + ": Deprecated app launch detected.")
    print(
        style.YELLOW + "WARN" + style.RESET + ": We recommend launching from the top level root_app.py, instead of ./front/app.py")
    print(style.YELLOW + "WARN" + style.RESET)
    app = FrontMain()
    app.start()
