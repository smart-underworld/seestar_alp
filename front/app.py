import time
from datetime import datetime, timedelta

import tzlocal

import falcon
from falcon import (
    HTTPFound,
    HTTPInternalServerError,
    HTTPNotFound,
)
from astroquery.simbad import Simbad
from jinja2 import Environment, FileSystemLoader
from wsgiref.simple_server import WSGIRequestHandler, make_server
from pathlib import Path
import urllib.parse
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
import zipfile
import subprocess
import platform
import shutil
import signal
import math
import numpy as np
import sqlite3

from skyfield.api import Loader
from skyfield.data import mpc
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN

from device.config import Config  # type: ignore
from device.log import init_logging, get_logger  # type: ignore
from device.version import Version  # type: ignore
from device import telescope
import threading
import pydash

logger = init_logging()
load = Loader("data/")
_last_context_get_time = {}
_context_cached = {}
_last_api_state_get_time = {}
_api_state_cached = {}


def get_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(("10.254.254.254", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP


def get_listening_ip() -> str | None:
    if Config.ip_address == "0.0.0.0":
        # Find the ip
        ip_address = get_ip()
    else:
        ip_address = Config.ip_address
    return ip_address


def get_platform():
    plat = platform.system()
    if plat == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as cpuinfo_file:
                cpuinfo = cpuinfo_file.read()
                if "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo:
                    plat = "raspberry_pi"
        except FileNotFoundError:
            pass

        # Check for Raspberry Pi-specific files
        if os.path.exists("/sys/firmware/devicetree/base/model"):
            try:
                with open("/sys/firmware/devicetree/base/model", "r") as model_file:
                    model_info = model_file.read().lower()
                    if "raspberry pi" in model_info:
                        plat = "raspberry_pi"
            except FileNotFoundError:
                pass

    return plat


base_url = "http://" + get_listening_ip() + ":" + str(Config.port)
simbad_url = "https://simbad.cds.unistra.fr/simbad/sim-id?output.format=ASCII&obj.bibsel=off&Ident="
messages: list[str] = []
online = None
client_master = True
queue = {}
os_platform = get_platform()

#
# Globally turned off IPv6 on requests.  This was causing incredible slowness
#   on Windows
#
requests.packages.urllib3.util.connection.HAS_IPV6 = False


def flash(resp, message):
    # todo : set to internal state so it can be used!
    resp.set_cookie("flash_cookie", message, path="/")
    messages.append(message)


def get_messages() -> list[str]:
    if len(messages) > 0:
        # Return a snapshot to avoid returning a reference to the cleared list
        out = messages[:]
        messages.clear()
        return out
    return []


def get_telescopes():
    telescopes = Config.seestars
    return list(telescopes)


def get_telescope(telescope_id):
    telescopes = get_telescopes()
    return list(
        filter(lambda telescope: telescope["device_num"] == telescope_id, telescopes)
    )[0]


def get_root(telescope_id):
    if telescope_id == 0:
        root = "/0"
        return root
    else:
        telescopes = get_telescopes()
        # if len(telescopes) == 1:
        #     return ""
        telescope = list(
            filter(lambda tel: tel["device_num"] == telescope_id, telescopes)
        )[0]
        if telescope:
            root = f"/{telescope['device_num']}"
            return root
    return ""


def get_imager_root(telescope_id, req):
    if telescope_id > 0:
        telescopes = get_telescopes()
        # if len(telescopes) == 1:
        #     return ""

        telescope = list(
            filter(lambda tel: tel["device_num"] == telescope_id, telescopes)
        )[0]
        if telescope:
            root = f"http://{req.host}:{Config.imgport}/{telescope['device_num']}"
            return root
    return ""


def _get_context_real(telescope_id, req):
    # probably a better way of doing this...
    telescopes = get_telescopes()
    root = get_root(telescope_id)
    imager_root = get_imager_root(telescope_id, req)
    online = check_api_state(telescope_id)
    client_master = get_client_master(telescope_id)
    segments = req.relative_uri.lstrip("/").split("/", 1)
    partial_path = segments[1] if len(segments) > 1 else segments[0]
    experimental = Config.experimental
    confirm = Config.confirm
    uitheme = Config.uitheme
    defgain = Config.init_gain
    if telescope_id > 0:
        telescope = get_telescope(telescope_id)
    else:
        telescope = {
            "device_num": 0,
            "name": "Seestar Federation",
            "ip_address": get_ip(),
        }

    current_item = None
    is_stacking = False
    scheduler_state = do_action_device(
        "get_event_state", telescope_id, {"event_name": "scheduler"}
    )
    if scheduler_state:
        current_item = (
            scheduler_state.get("Value", {}).get("result", {}).get("cur_scheduler_item")
        )
        is_stacking = bool(
            scheduler_state.get("Value", {}).get("result", {}).get("is_stacking")
        )

    current_stack = None
    stack_state = do_action_device(
        "get_event_state", telescope_id, {"event_name": "Stack"}
    )
    if stack_state:
        current_stack = stack_state.get("Value", {}).get("result", {})

    current_exp = None
    if telescope_id > 0:
        if is_stacking:
            exp_value = method_sync("get_camera_exp_and_bin", telescope_id)
            if exp_value:
                current_exp = exp_value.get("exposure")
                if current_exp is not None:
                    current_exp = int(current_exp) / 1000000
                else:  # in case we are dealing with federation with device id 0
                    current_exp = 0

    return {
        "telescope": telescope,
        "telescopes": telescopes,
        "root": root,
        "partial_path": partial_path,
        "online": online,
        "imager_root": imager_root,
        "experimental": experimental,
        "confirm": confirm,
        "uitheme": uitheme,
        "client_master": client_master,
        "current_item": current_item,
        "current_stack": current_stack,
        "platform": os_platform,
        "defgain": defgain,
        "current_exp": current_exp,
    }


def get_context(telescope_id, req):
    if (
        telescope_id not in _context_cached
        or time.time() - _last_context_get_time[telescope_id] > 1.0
    ):
        _last_context_get_time[telescope_id] = time.time()
        _context_cached[telescope_id] = _get_context_real(telescope_id, req)
    return _context_cached[telescope_id]


def get_flash_cookie(req, resp):
    cookie = req.get_cookie_values("flash_cookie")
    if cookie:
        resp.unset_cookie("flash_cookie", path="/")
        return cookie
    return []


def update_twilight_times(latitude=None, longitude=None):
    observer = ephem.Observer()
    observer.date = datetime.now()
    local_timezone = tzlocal.get_localzone()
    sun = ephem.Sun()
    current_date_formatted = str(datetime.now().strftime("%Y-%m-%d"))

    if latitude is None and longitude is None:
        if internet_connection:
            geo = geocoder.ip("me")
            latitude = str(geo.latlng[0])
            longitude = str(geo.latlng[1])
            observer.lat = str(geo.latlng[0])  # ephem likes str
            observer.lon = str(geo.latlng[1])  # ephem likes str
        else:
            twilight_times = {
                "Info": "No internet connection detected on the device running SSC. Please set Latitude and Longitude.",
                "Latitude": "",
                "Longitude": "",
            }

            # Don't update the cache file.
            return twilight_times
    else:
        observer.lat = str(latitude)  # ephem likes str
        observer.lon = str(longitude)  # ephem likes str

    # ephim lib erroneously raises an exception at times saying the Sun is above horizon
    # when it is not.  This is a bug in the ephem library.  This is a workaround.

    # Sunrise & Sunset
    try:
        loc_sunset = pytz.utc.localize(
            observer.next_setting(sun).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_sunset = "Error"
    try:
        loc_next_sunrise = pytz.utc.localize(
            observer.next_rising(sun).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_next_sunrise = "Error"

    # Civil Beginning and End
    observer.horizon = "-6"  # -6=civil twilight, -12=nautical, -18=astronomical
    try:
        loc_end_civil = pytz.utc.localize(
            observer.next_setting(sun, use_center=True).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_end_civil = "Error"
    try:
        loc_next_beg_civil = pytz.utc.localize(
            observer.next_rising(sun, use_center=True).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_next_beg_civil = "Error"

    # Astronomical Beginning and End
    observer.horizon = "-18"  # -6=civil twilight, -12=nautical, -18=astronomical
    try:
        loc_beg_astronomical = pytz.utc.localize(
            observer.next_setting(sun, use_center=True).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_beg_astronomical = "Error"
    try:
        loc_next_end_astronomical = pytz.utc.localize(
            observer.next_rising(sun, use_center=True).datetime()
        ).astimezone(local_timezone)
    except Exception:
        loc_next_end_astronomical = "Error"

    twilight_times = {
        "Today's Date": current_date_formatted,
        "Latitude": str(latitude),
        "Longitude": str(longitude),
        "Today's Sunset": str(loc_sunset),
        "Next Sunrise": str(loc_next_sunrise),
        "Today's Civil End": str(loc_end_civil),
        "Next Civil Begin": str(loc_next_beg_civil),
        "Today's Astronomical Begin": str(loc_beg_astronomical),
        "Next Astronomical End": str(loc_next_end_astronomical),
    }

    # Write twilight times cache file
    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        twilight_times_file = os.path.abspath(
            os.path.join(sys._MEIPASS, "twilight_times.json")
        )
    else:
        twilight_times_file = os.path.join(
            os.path.dirname(__file__), "twilight_times.json"
        )

    with open(twilight_times_file, "w") as outfile:
        logger.info("Twilight times: Writing cache file.")
        json.dump(twilight_times, outfile)

    return twilight_times


def get_twilight_times():
    current_date_formatted = str(datetime.now().strftime("%Y-%m-%d"))

    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        twilight_times_file = os.path.abspath(
            os.path.join(sys._MEIPASS, "twilight_times.json")
        )
    else:
        twilight_times_file = os.path.join(
            os.path.dirname(__file__), "twilight_times.json"
        )

    # Check to see if there is cached infromation for today
    if os.path.isfile(twilight_times_file):
        logger.info("Twilight times: Cache file exists.")

        with open(twilight_times_file, "r") as openfile:
            twilight_times = json.load(openfile)

        # Check if cached data is for today.
        if twilight_times["Today's Date"] == current_date_formatted:
            logger.info("Twilight times: Cache file is current, using cache file.")
        else:
            logger.info("Twilight times: Cache file out of date, updating cache file.")

            # Use lat and lon from the cache file
            latitude = str(twilight_times["Latitude"])
            longitude = str(twilight_times["Longitude"])

            # Update the cache file
            twilight_times = update_twilight_times(latitude, longitude)
    else:
        logger.info("Twilight times: Cache file doesn't exists, creating cache file.")
        # Update the cache file
        twilight_times = update_twilight_times()

    return twilight_times


def get_planning_cards():
    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        card_state_file_location = os.path.abspath(
            os.path.join(sys._MEIPASS, "planning.json")
        )
    else:
        card_state_file_location = os.path.join(
            os.path.dirname(__file__), "planning.json"
        )

    # Check to see if there is cached planning.json, if not create it.
    if not os.path.isfile(card_state_file_location):
        if getattr(
            sys, "frozen", False
        ):  # frozen means that we are running from a bundled app
            card_state_example_file_location = os.path.abspath(
                os.path.join(sys._MEIPASS, "planning.json.example")
            )
        else:
            card_state_example_file_location = os.path.join(
                os.path.dirname(__file__), "planning.json.example"
            )
        shutil.copyfile(card_state_example_file_location, card_state_file_location)

    with open(card_state_file_location, "r") as card_state_file:
        state_data = json.load(card_state_file)
        return state_data


def get_planning_card_state(card_name):
    # Get's the state of a card via planning.json
    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        planning_state_file_location = os.path.abspath(
            os.path.join(sys._MEIPASS, "planning.json")
        )
    else:
        planning_state_file_location = os.path.join(
            os.path.dirname(__file__), "planning.json"
        )

    with open(planning_state_file_location, "r") as planning_state_file:
        state_data = json.load(planning_state_file)

    for card in state_data:
        # print (card['card_name'])
        if card["card_name"] == card_name:
            return card


def update_planning_card_state(card_name, var, value):
    # Update planning.json with current card state
    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        planning_state_file_location = os.path.abspath(
            os.path.join(sys._MEIPASS, "planning.json")
        )
    else:
        planning_state_file_location = os.path.join(
            os.path.dirname(__file__), "planning.json"
        )

    with open(planning_state_file_location, "r") as planning_state_file:
        state_data = json.load(planning_state_file)

    for card in state_data:
        if card["card_name"] == card_name:
            if var in card:
                card[var] = value
                break
            else:
                logger.info(
                    f"Planning Card: Variable '{var}' not found in card {card}."
                )

    with open(planning_state_file_location, "w") as planning_state_file:
        json.dump(state_data, planning_state_file, indent=4)


def _check_api_state_cached(telescope_id):
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
        logger.warn(
            f"Telescope {telescope_id} API is not online. (ConnectionError) {url=}"
        )
        return False
    except requests.exceptions.RequestException:
        logger.warn(
            f"Telescope {telescope_id} API is not online. (RequestException) {url=}"
        )
        return False
    else:
        logger.debug(f"Telescope {telescope_id} API is online.")
        return True


def check_api_state(telescope_id):
    if (
        telescope_id not in _api_state_cached
        or time.time() - _last_api_state_get_time[telescope_id] > 1.0
    ):
        _last_api_state_get_time[telescope_id] = time.time()
        _api_state_cached[telescope_id] = _check_api_state_cached(telescope_id)
    return _api_state_cached[telescope_id]


def check_internet_connection():
    remote_server = "www.google.com"
    port = 80
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect((remote_server, port))
        logger.info("Internet connection detected.")
        return True
    except socket.error:
        logger.info("Unable to detect Internet connection.")  # or google is down...
        return False
    finally:
        sock.close()


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
        "ClientTransactionID": 999,
    }
    if check_api_state(dev_num):
        try:
            r = requests.put(url, json=payload, timeout=Config.timeout)
            out = r.json()
            return out
        except Exception as e:
            logger.error(
                f"do_action_device: Failed to send action to device {dev_num}: {e}: message={payload}"
            )

    if is_schedule:
        queue_action(dev_num, payload)


def do_schedule_action_device(action, parameters, dev_num):
    if parameters:
        return do_action_device(
            "add_schedule_item", dev_num, {"action": action, "params": parameters}, True
        )
    else:
        return do_action_device(
            "add_schedule_item", dev_num, {"action": action, "params": {}}, True
        )


def do_insert_schedule_item(action, parameters, before_id, dev_num):
    if parameters:
        return do_action_device(
            "insert_schedule_item_before",
            dev_num,
            {"before_id": before_id, "action": action, "params": parameters},
            False,
        )
    else:
        return do_action_device(
            "insert_schedule_item_before",
            dev_num,
            {"before_id": before_id, "action": action, "params": {}},
            False,
        )


def method_sync(method, telescope_id=1, **kwargs):
    out = do_action_device("method_sync", telescope_id, {"method": method, **kwargs})

    # print(f"method_sync {out=}")

    def err_extractor(obj):
        if obj and obj.get("error"):
            logger.warn(f"method_sync: {method} - {obj['error']}")
            result = {"command": method, "status": "error", "result": obj["error"]}
            return result
        elif obj:
            result = {"command": method, "status": "success", "result": obj["result"]}
            return result

    if out:
        value = out.get("Value")
        if telescope_id == 0:
            results = {}
            for tel in get_telescopes():
                devnum = str(tel.get("device_num"))
                if check_api_state(devnum) is False:
                    continue
                dev_value = value.get(devnum) if value else None
                results[devnum] = err_extractor(dev_value) or "Offline"
                if results[devnum] is None:
                    results[devnum] = "Offline"
                else:
                    if (
                        results[devnum]["status"] == "success"
                        and results[devnum]["result"] != 0
                    ):
                        results[devnum] = results[devnum]["result"]
        else:
            if not value:
                return "Offline"
            results = err_extractor(value)
            if results.get("status", {}) == "error":
                return results
            if results.get("result", {}) == 0:
                return results
            else:
                return results.get("result", {})
        return results
    return None


def get_client_master(telescope_id):
    client_master = True  # Assume master for older firmware
    if telescope_id > 0:
        event_state = do_action_device("get_event_state", telescope_id, {})
        if event_state is not None:
            result = event_state["Value"]["result"]
            if "Client" in result:
                client_master = result["Client"].get("is_master", True)

    return client_master


def get_guestmode_state(telescope_id):
    state = {}
    if check_api_state(telescope_id):
        guestmode = False
        is_master = False
        master_idx = -1
        client_list = []
        fw = 0

        result = method_sync("get_device_state", telescope_id)
        if result is not None:
            device = result.get("device", {})
            fw = device.get("firmware_ver_int", 0)

            if fw >= 2300:
                settings = result.get("setting", {})
                if fw >= 2400:
                    guestmode = settings.get("guest_mode", False)
                else:
                    guestmode = True

                if guestmode:
                    is_master = result.get("client", {"is_master": is_master}).get(
                        "is_master", is_master
                    )
                    master_idx = result.get("client", {"master_index": master_idx}).get(
                        "master_index", master_idx
                    )
                    client_list = result.get("client", {"connected": client_list}).get(
                        "connected", client_list
                    )

    state = {
        "firmware_ver_int": fw,
        "guest_mode": guestmode,
        "client_master": is_master,
        "master_index": master_idx,
        "client_list": client_list,
    }

    return state


def get_device_state(telescope_id):
    if check_api_state(telescope_id):
        result = method_sync("get_device_state", telescope_id)
        status = method_sync("get_view_state", telescope_id)
        wifi_status = method_sync("pi_station_state", telescope_id)

        # Initialize variables with defaults using pydash.get
        view_state = pydash.get(status, "View.state", "Idle")
        mode = pydash.get(status, "View.mode", "")
        stage = pydash.get(status, "View.stage", "")
        target = pydash.get(status, "View.target_name", "")

        # Simplify stack info access
        stack_state = pydash.get(status, "View.Stack.state")
        stacked = (
            pydash.get(status, "View.Stack.stacked_frame", "")
            if stack_state == "working"
            else ""
        )
        failed = (
            pydash.get(status, "View.Stack.dropped_frame", "")
            if stack_state == "working"
            else ""
        )

        wifi_signal = ""
        free_storage = "Unknown"
        guestmode = False
        is_master = False
        client_master = True
        client_list = ""
        mount_mode = "Unknown"

        # Check for bad data
        if status is not None and result is not None:
            schedule = do_action_device("get_schedule", telescope_id, {})

            if result is not None:
                # Get Mount Mode
                eq_mode = pydash.get(result, "mount.equ_mode", False)
                mount_mode = "Equatorial" if eq_mode else "Alt Azimuth"

                # Get storage information directly
                storage_state = pydash.get(
                    result, "storage.storage_volume[0].state", ""
                )

                if storage_state == "mounted":
                    free_mb = pydash.get(result, "storage.storage_volume[0].freeMB", 0)
                    free_storage = humanize.naturalsize(free_mb * 1024 * 1024)
                elif storage_state == "connected":
                    free_storage = "Unavailable while in USB storage mode."

                # Get firmware version directly
                fw = pydash.get(result, "device.firmware_ver_int", 0)

                if fw > 2300:
                    # Get guest mode setting directly
                    guestmode = (
                        pydash.get(result, "setting.guest_mode", False)
                        if fw >= 2400
                        else True
                    )

                    if guestmode:
                        # Get client information directly
                        client_master = pydash.get(result, "client.is_master", False)
                        clients = pydash.get(result, "client.connected", [])
                        master_idx = pydash.get(result, "client.master_index", -1)

                        if 0 <= master_idx < len(clients):
                            clients[master_idx] = "master:" + clients[master_idx]
                        client_list = "<br>".join(clients)

            # Safely access wifi_status
            if wifi_status is not None:
                is_server = pydash.get(wifi_status, "server", False)
                sig_lev = pydash.get(wifi_status, "sig_lev", "N/A")

                if (is_server and not guestmode) or (guestmode and is_master):
                    wifi_signal = f"{sig_lev} dBm"
                elif guestmode:
                    wifi_signal = "Unavailable in Guest mode."
                else:
                    wifi_signal = "Unavailable in AP mode."

            # Build stats dictionary using direct pydash.get access
            stats = {
                "Firmware Version": pydash.get(
                    result, "device.firmware_ver_string", ""
                ),
                "Focal Position": pydash.get(result, "focuser.step", ""),
                "Auto Power Off": pydash.get(result, "setting.auto_power_off", ""),
                "Heater?": pydash.get(result, "setting.heater_enable", ""),
                "Free Storage": free_storage,
                "Balance Sensor (angle)": pydash.get(
                    result, "balance_sensor.data.angle"
                ),
                "Compass Sensor (direction)": pydash.get(
                    result, "compass_sensor.data.direction"
                ),
                "Temperature Sensor": pydash.get(result, "pi_status.temp", ""),
                "Charge Status": pydash.get(result, "pi_status.charger_status", ""),
                "Battery %": pydash.get(result, "pi_status.battery_capacity", ""),
                "Battery Temp": pydash.get(result, "pi_status.battery_temp", ""),
                "Mount Mode": mount_mode,
                "Scheduler Status": pydash.get(schedule, "Value.state"),
                "View State": view_state,
                "View Mode": mode,
                "View Stage": stage,
                "Target Name": target,
                "Successful Frames": stacked,
                "Failed Frames": failed,
                "Wi-Fi Signal": wifi_signal,
            }

            # Add guest mode stats if firmware supports it
            if fw > 2300:
                stats["Master client"] = client_master
                stats["Client list"] = client_list

        else:
            logger.info("Stats: Unable to get data.")
            stats = {"Info": "Unable to get stats."}
    else:
        stats = {}
    return stats


def get_device_settings(telescope_id):
    if telescope_id == 0:
        telescopes = get_telescopes()
        if len(telescopes) > 0:
            telescope_id = telescopes[0]["device_num"]

    settings = None
    if get_client_master(telescope_id):
        settings_result = method_sync("get_setting", telescope_id)
        stack_settings_result = method_sync("get_stack_setting", telescope_id)

        settings = {
            "stack_dither_pix": pydash.get(settings_result, "stack_dither.pix"),
            "stack_dither_interval": pydash.get(
                settings_result, "stack_dither.interval"
            ),
            "stack_dither_enable": pydash.get(settings_result, "stack_dither.enable"),
            "exp_ms_stack_l": pydash.get(settings_result, "exp_ms.stack_l"),
            "exp_ms_continuous": pydash.get(settings_result, "exp_ms.continuous"),
            "save_discrete_ok_frame": pydash.get(
                stack_settings_result, "save_discrete_ok_frame"
            ),
            "save_discrete_frame": pydash.get(
                stack_settings_result, "save_discrete_frame"
            ),
            "light_duration_min": pydash.get(
                stack_settings_result, "light_duration_min"
            ),
            "auto_3ppa_calib": pydash.get(settings_result, "auto_3ppa_calib"),
            "frame_calib": pydash.get(settings_result, "frame_calib"),
            "manual_exp": pydash.get(settings_result, "manual_exp"),
            "focal_pos": pydash.get(settings_result, "focal_pos"),
            "heater_enable": pydash.get(settings_result, "heater_enable"),
            "auto_power_off": pydash.get(settings_result, "auto_power_off"),
            "stack_lenhance": pydash.get(settings_result, "stack_lenhance"),
            "dark_mode": pydash.get(settings_result, "dark_mode"),
            "stack_cont_capt": pydash.get(settings_result, "stack.cont_capt"),
            "stack_drizzle2x": pydash.get(settings_result, "stack.drizzle2x"),
        }
    return settings


def get_telescopes_state():
    telescopes = get_telescopes()

    return list(
        map(
            lambda telescope: telescope
            | {"stats": get_device_state(telescope["device_num"])},
            telescopes,
        )
    )


def get_queue(telescope_id):
    parameters_list = []
    if telescope_id in queue:
        for item in queue[telescope_id]:
            parameters_list.append(json.loads(item["Parameters"]))
        return parameters_list
    else:
        return []


def process_queue(resp, telescope_id):
    if check_api_state(telescope_id):
        parameters_list = []
        for command in queue[telescope_id]:
            parameters_list.append(json.loads(command["Parameters"]))
        for param in parameters_list:
            action = param["action"]
            if param["params"]:
                params = param["params"]
            else:
                params = None
            logger.info("POST scheduled request %s %s", action, params)
            response = do_schedule_action_device(action, params, telescope_id)
            logger.info("GET response %s", response)
    else:
        flash(
            resp,
            "ERROR: Seestar ALP API is Offline, Please ensure your Seestar is powered on and device/app.py is running.",
        )


def check_ra_value(raString):
    valid = [
        r"^\d+h\s*\d+m\s*([0-9.]+s)?$",
        r"^\d+(\.\d+)?$",
        r"^\d+\s+\d+\s+[0-9.]+$",
        r"^[+-]?([0-9]*[.])?[0-9]+$",
    ]
    return any(re.search(pattern, raString) for pattern in valid)


def check_dec_value(decString):
    valid = [
        r"^[+-]?\d+d\s*\d+m\s*([0-9.]+s)?$",
        r"^[+-]?\d+(\.\d+)?$",
        r"^[+-]?\d+\s+\d+\s+[0-9.]+$",
        r"^[+-]?([0-9]*[.])?[0-9]+$",
    ]
    return any(re.search(pattern, decString) for pattern in valid)


def hms_to_sec(timeString):
    timeString = timeString.strip().lower()

    # Case 1: Pure number (int or float) = seconds
    if re.fullmatch(r"\d+(\.\d+)?", timeString):
        return int(float(timeString))  # Convert to float then int

    # Case 2: Match h/m/s with optional decimals
    match = re.match(
        r"""^
            (?:(\d+(?:\.\d+)?)\s*h\s*)?   # Hours (optional)
            (?:(\d+(?:\.\d+)?)\s*m\s*)?   # Minutes (optional)
            (?:(\d+(?:\.\d+)?)\s*s\s*)?   # Seconds (optional)
        $""",
        timeString,
        re.VERBOSE,
    )

    if match:
        hours = float(match.group(1)) if match.group(1) else 0
        minutes = float(match.group(2)) if match.group(2) else 0
        seconds = float(match.group(3)) if match.group(3) else 0
        return int(hours * 3600 + minutes * 60 + seconds)

    # Case 3: Invalid format
    return timeString


def lat_lng_distance_in_km(lat1, lng1, lat2, lng2):
    """
    Based off of https://github.com/BGCastro89/nearest_csc
    """
    """Calculate distance between two latitude-longitide points on sphere in kilometres.

    args: Float lat/lng for two points on Earth
    returns: Float representing distance in kilometres
    """
    R = 6371  # Earth Radius in kilometres (assume perfect sphere)

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) * math.sin(d_phi / 2) + math.cos(phi1) * math.cos(
        phi2
    ) * math.sin(d_lambda / 2) * math.sin(d_lambda / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    d = R * c

    return round(d, 1)  # Assume Accurate within ~0.1km due to Idealized Sphere Earth


def get_nearest_csc():
    """
    Based off of https://github.com/BGCastro89/nearest_csc
    """
    """Nearest Clear Sky Chart from A. Danko's site: https://www.cleardarksky.com/

    All 5000+ sities are binned by 1x1 degree lat/lng. Only check the
    distance to sites within current bin +/- 1 degree, searching 9 bins total.

    args: request object w/ args for lat/lng
    returns: String, either with json representation of nearest site information or an error message
    """

    lat = Config.init_lat
    lng = Config.init_long

    if getattr(
        sys, "frozen", False
    ):  # frozen means that we are running from a bundled app
        csc_file = os.path.abspath(os.path.join(sys._MEIPASS, "csc_sites.json"))
    else:
        csc_file = os.path.join(os.path.dirname(__file__), "./csc_sites.json")

    closest_site = {}

    # Get list of all csc site locations
    with open(csc_file, "r") as f:
        data = json.load(f)
        nearby_csc = []

        # Get list of all sites within same or adjacent 1 degree lat/lng bin
        try:
            for x in range(-1, 2):
                for y in range(-1, 2):
                    lat_str = str(int(lat) + x)
                    lng_str = str(int(lng) + y)
                    if lat_str in data:
                        if lng_str in data[lat_str]:
                            sites_in_bin = data[lat_str][lng_str]
                            for site in sites_in_bin:
                                nearby_csc.append(site)
        except:
            # API returns error
            closest_site = {
                "status_msg": "ERROR parsing coordinates or reading from list of CSC sites"
            }

        curr_closest_km = 1000

        # Find the closest site in Clear Dark Sky database within bins
        for site in nearby_csc:
            dist = lat_lng_distance_in_km(lat, lng, site["lat"], site["lng"])

            if dist < curr_closest_km:
                curr_closest_km = dist
                closest_site = site

        # Grab site url and return site data if within 100 km
        if curr_closest_km < 1000:
            closest_site["status_msg"] = "SUCCESS"
            closest_site["dist_km"] = curr_closest_km
            closest_site["full_img"] = (
                "https://www.cleardarksky.com/c/" + closest_site["id"] + "csk.gif"
            )
            closest_site["mini_img"] = (
                "https://www.cleardarksky.com/c/" + closest_site["id"] + "cs0.gif"
            )
            closest_site["href"] = (
                "https://www.cleardarksky.com/c/" + closest_site["id"] + "key.html"
            )
        else:
            closest_site = {
                "status_msg": "No sites within 100 km. CSC sites are only available in the Continental US, Canada, and Northern Mexico"
            }

        return closest_site


def do_create_mosaic(req, resp, schedule, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra, raPanels = form["ra"], form["raPanels"]
    dec, decPanels = form["dec"], form["decPanels"]
    panelOverlap = form["panelOverlap"]
    panelSelect = form["panelSelect"]
    useJ2000 = form.get("useJ2000") == "on"
    panelTime = hms_to_sec(form["panelTime"])
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    num_tries = form.get("num_tries")
    retry_wait_s = form.get("retry_wait_s")
    action = form.get("action", "")
    selected_items = form.get("selected_items", "")
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec,
        "is_use_lp_filter": useLpfilter,
        "panel_time_sec": int(panelTime),
        "ra_num": int(raPanels),
        "dec_num": int(decPanels),
        "panel_overlap_percent": int(panelOverlap),
        "selected_panels": panelSelect,
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus,
        "num_tries": int(num_tries) if num_tries else 1,
        "retry_wait_s": int(retry_wait_s) if retry_wait_s else 300,
    }

    if telescope_id == 0:
        fedMode = form.get("federation_mode")
        if fedMode:
            values["federation_mode"] = fedMode
        maxDev = form.get("max_devices")
        if maxDev:
            values["max_devices"] = maxDev

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
        if action == "append":
            response = do_schedule_action_device("start_mosaic", values, telescope_id)
        else:
            response = do_insert_schedule_item(
                "start_mosaic", values, selected_items, telescope_id
            )

        logger.info("POST scheduled request %s %s", values, response)
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
    panelTime = hms_to_sec(form["panelTime"])
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    num_tries = form.get("num_tries")
    retry_wait_s = form.get("retry_wait_s")
    action = form.get("action", "")
    selected_items = form.get("selected_items", "")
    errors = {}
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": ra,
        "dec": dec,
        "is_use_lp_filter": useLpfilter,
        "panel_time_sec": int(panelTime),
        "ra_num": int(raPanels),
        "dec_num": int(decPanels),
        "panel_overlap_percent": int(panelOverlap),
        "selected_panels": panelSelect,
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus,
        "num_tries": int(num_tries) if num_tries else 1,
        "retry_wait_s": int(retry_wait_s) if retry_wait_s else 300,
    }

    if telescope_id == 0:
        fedMode = form.get("federation_mode")
        if fedMode:
            values["federation_mode"] = fedMode
        maxDev = form.get("max_devices")
        if maxDev:
            values["max_devices"] = maxDev

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
        if action == "append":
            response = do_schedule_action_device("start_mosaic", values, telescope_id)
        else:
            response = do_insert_schedule_item(
                "start_mosaic", values, selected_items, telescope_id
            )

        logger.info("POST scheduled request %s %s", values, response)
    else:
        response = do_action_device("start_mosaic", telescope_id, values, False)
        logger.info("POST immediate request %s %s", values, response)

    return values, errors


def do_goto_target(req, resp, telescope_id):
    form = req.media
    targetName = form["targetName"]
    ra = form["ra"]
    dec = form["dec"]
    useJ2000 = form.get("useJ2000") == "on"
    errors = {}
    values = {"target_name": targetName, "is_j2000": useJ2000, "ra": ra, "dec": dec}

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
    value = form.get("command", "").strip()
    # print ("Selected command: ", value)
    match value:
        case "adjust_mag_declination":
            adjust_mag_dec = form.get("adjust_mag_dec", "False").strip() == "on"
            fudge_angle = form.get("fudge_angle", "").strip()
            if adjust_mag_dec:
                if fudge_angle:
                    output = do_action_device(
                        "adjust_mag_declination",
                        telescope_id,
                        {
                            "adjust_mag_dec": adjust_mag_dec,
                            "fudge_angle": float(fudge_angle),
                        },
                    )
                else:
                    output = do_action_device(
                        "adjust_mag_declination",
                        telescope_id,
                        {"adjust_mag_dec": adjust_mag_dec},
                    )
            else:
                output = "Adjust Mag Dec not selected. No action taken."
            return output
        case "get_event_state":
            output = do_action_device("get_event_state", telescope_id, {})
            return output
        case "reset_scheduler_cur_item":
            output = do_action_device("reset_scheduler_cur_item", telescope_id, {})
        case "scope_park":
            output = method_sync("scope_park", telescope_id)
            return output
        case "scope_move_to_horizon":
            output = method_sync("scope_move_to_horizon", telescope_id)
            return output
        case "pi_reboot":
            output = method_sync("pi_reboot", telescope_id)
            return output
        case "pi_shutdown":
            output = method_sync("pi_shutdown", telescope_id)
            return output
        case "start_auto_focus":
            output = method_sync("start_auto_focuse", telescope_id)
            return output
        case "stop_auto_focus":
            output = method_sync("stop_auto_focuse", telescope_id)
            return output
        case "get_focuser_position":
            output = method_sync("get_focuser_position", telescope_id)
            return output
        case "get_last_focuser_position":
            output = method_sync("get_focuser_position", telescope_id)
            return output
        case "start_solve":
            output = method_sync("start_solve", telescope_id)
            return output
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
        case "start_create_calib_frame":
            output = method_sync("start_create_calib_frame")
            return output
        case "start_create_hpc":
            output = method_sync("start_create_hpc")
            return output
        case "pi_get_ap":
            output = method_sync("pi_get_ap", telescope_id)
            return output
        case "get_app_setting":
            output = method_sync("get_app_setting", telescope_id)
            print(f"{output}")
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
        case "iscope_start_stack":
            output = method_sync("iscope_start_stack", telescope_id)
            return output
        case "iscope_stop_view":
            output = method_sync("iscope_stop_view", telescope_id)
            return output
        case "grab_control":
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"master_cli": True}},
            )
            return output
        case "release_control":
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"master_cli": False}},
            )
            return output
        case "set_eq_mode":
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "scope_park", "params": {"equ_mode": True}},
            )
            return output
        case "set_alt_az_mode":
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "scope_park", "params": {"equ_mode": False}},
            )
            return output
        case _:
            logger.warn("No command found: %s", value)
    # print ("Output: ", output)


def do_support_bundle(req, telescope_id=1):
    zip_buffer = io.BytesIO()
    desc = req.media["desc"]
    getSeestarLogs = req.media.get("getSeestarLogs") == "on"
    logger.debug("do_support_bundle: getting logs (starting)")
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        # Add logs
        cwd = Path(os.getcwd())
        pfx = cwd.joinpath(Config.log_prefix)
        if pfx == "":
            pfx = "."
        for f in list(pfx.glob("alpyca.log*")):
            fstr = f.name
            logger.debug(f"do_support_bundle: Adding {fstr} to zipfile")
            with open(str(f), "rb") as fh:
                buf = io.BytesIO(fh.read())
                zip_file.writestr(fstr, buf.getvalue())

        for f in list(pfx.joinpath("device").glob("config.toml*")):
            fstr = f.name
            logger.debug(f"do_support_bundle: Adding {fstr} to zipfile")
            with open(str(f), "rb") as fh:
                buf = io.BytesIO(fh.read())
                zip_file.writestr(fstr, buf.getvalue())

        zip_file.writestr("problem_description.txt", desc)

        os_name = platform.system()
        zip_file.writestr("OS_name.txt", os_name)

        if os_name == "Linux":
            cmd_result = subprocess.check_output(["journalctl", "-b", "-u", "seestar"])
            zip_file.writestr("seestar_service_journal.txt", cmd_result)
            cmd_result = subprocess.check_output(["journalctl", "-b", "-u", "INDI"])
            zip_file.writestr("INDI_service_journal.txt", cmd_result)
        # if os.path.isdir('.git'):
        #    cmd_result = subprocess.check_output(['git', 'log', '-n', '1'])
        #    zip_file.writestr("git_version.txt", cmd_result)
        path = shutil.which("pip")
        if path is not None:
            cmd_result = subprocess.check_output(["pip", "freeze"])
            zip_file.writestr("pip_info.txt", cmd_result)
        else:
            path = shutil.which("pip3")
            if path is not None:
                cmd_result = subprocess.check_output(["pip3", "freeze"])
                zip_file.writestr("pip3_info.txt", cmd_result)
        path = shutil.which("python")
        if path is not None:
            cmd_result = subprocess.check_output(["python", "--version"])
            zip_file.writestr("python_version.txt", cmd_result)
        else:
            path = shutil.which("python3")
            if path is not None:
                cmd_result = subprocess.check_output(["python3", "--version"])
                zip_file.writestr("python3_version.txt", cmd_result)

        env_vars = os.environ
        env_content = "\n".join(f"{key}={value}" for key, value in env_vars.items())
        zip_file.writestr("env.txt", env_content)

        online = check_api_state(telescope_id)

        if online and getSeestarLogs and telescope_id in telescope.seestar_logcollector:
            dev_log = telescope.get_seestar_logcollector(telescope_id)
            zip_data = dev_log.get_logs_sync()
            zip_file.writestr(f"seestar_{telescope_id}_logs.zip", zip_data)

    return zip_buffer


def redirect(location):
    raise HTTPFound(location)
    # raise HTTPTemporaryRedirect(location)


template_dir = os.path.join(os.path.dirname(__file__), "templates")
env = Environment(loader=FileSystemLoader(template_dir))


def seconds_to_hms(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


env.globals["seconds_to_hms"] = seconds_to_hms


def fetch_template(template_name):
    try:
        if getattr(sys, "frozen", False):
            template_path = os.path.join(os.path.dirname(__file__), "templates")
            env.loader = FileSystemLoader(template_path)
        return env.get_template(template_name)
    except Exception as e:
        print(f"Error fetching template {template_name}: {e}")
        raise


def render_template(req, resp, template_name, **context):
    template = fetch_template(template_name)
    resp.status = falcon.HTTP_200
    resp.content_type = "text/html"
    webui_theme = Config.uitheme
    version = Version.app_version()

    resp.text = template.render(
        flashed_messages=get_flash_cookie(req, resp),
        messages=get_messages(),
        webui_theme=webui_theme,
        version=version,
        **context,
    )


def render_schedule_tab(req, resp, telescope_id, template_name, tab, values, errors):
    directory = os.path.join(os.getcwd(), "schedule")
    Path(directory).mkdir(parents=True, exist_ok=True)
    files = [
        f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))
    ]

    context = get_context(telescope_id, req)
    if context["online"]:
        get_schedule = do_action_device("get_schedule", telescope_id, {})
        if get_schedule is None:
            schedule = {}
            state = "stopped"
        else:
            schedule = get_schedule["Value"]
            state = schedule.get("state", "stopped")
    else:
        get_schedule = do_action_device("get_schedule", 0, {})
        if get_schedule is None:
            schedule = {}
            state = "stopped"
        else:
            schedule = get_schedule["Value"]
            state = schedule.get("state", "stopped")
    nearest_csc = get_nearest_csc()
    if nearest_csc["status_msg"] != "SUCCESS":
        nearest_csc["href"] = ""
        nearest_csc["full_img"] = ""
    render_template(
        req,
        resp,
        template_name,
        schedule=schedule,
        tab=tab,
        errors=errors,
        values=values,
        files=files,
        state=state,
        **context,
    )


def str2bool(v):
    return str(v).lower() in ("yes", "y", "true", "t", "1")


def import_csv_schedule(input, telescope_id):
    if isinstance(input, list):
        input_content = "\n".join(input)
        input = io.StringIO(input_content)

    input.seek(0)
    input_content = input.read()

    if input_content.startswith("\ufeff"):
        input_content = input_content[1:]

    cleaned_input = io.StringIO(input_content)

    reader = csv.DictReader(cleaned_input)

    for row in reader:
        row = {key: value.strip() for key, value in row.items()}
        action = row.pop("action", None)

        if not action:
            logger.warn("Skipping row without an action.")
            continue

        params = {key: value for key, value in row.items() if value.strip()}

        for key, value in params.items():
            if "," in value:
                params[key] = list(map(int, value.split(",")))
            elif value.lower() in {"true", "false"}:
                params[key] = value.lower() == "true"
            elif value.isdigit():
                params[key] = int(value)

        if action == "start_up_sequence":
            if "3ppa" in params:
                params["polar_align"] = params.pop("3ppa")

        match action:
            case "wait_until":
                do_schedule_action_device(
                    "wait_until", {"local_time": params.get("local_time")}, telescope_id
                )
            case "wait_for":
                do_schedule_action_device(
                    "wait_for", {"timer_sec": params.get("timer_sec", 0)}, telescope_id
                )
            case "auto_focus":
                do_schedule_action_device(
                    "auto_focus",
                    {"try_count": params.get("try_count", 0)},
                    telescope_id,
                )
            case "start_mosaic":
                required_params = [
                    "target_name",
                    "ra",
                    "dec",
                    "is_j2000",
                    "is_use_lp_filter",
                    "is_use_autofocus",
                    "panel_time_sec",
                    "ra_num",
                    "dec_num",
                    "panel_overlap_percent",
                    "gain",
                    "selected_panels",
                    "num_tries",
                    "retry_wait_s",
                    "array_mode",
                ]
                if "session_time_sec" in params:
                    session_time_sec = params.pop("session_time_sec")
                    ra_num = params.get("ra_num")
                    dec_num = params.get("dec_num")
                    panels = ra_num * dec_num
                    panel_time_sec = session_time_sec / panels
                    params["panel_time_sec"] = round(panel_time_sec)
                mosaic_params = {
                    key: value
                    for key, value in params.items()
                    if key in required_params
                }
                do_schedule_action_device("start_mosaic", mosaic_params, telescope_id)
            case "shutdown":
                do_schedule_action_device("shutdown", "", telescope_id)
            case "scope_park":
                do_schedule_action_device("scope_park", {}, telescope_id)
            case "set_wheel_position":
                wheel_positions = params.get("params")
                if wheel_positions:
                    if not isinstance(wheel_positions, list):
                        wheel_positions = [wheel_positions]
                    for position in wheel_positions:
                        try:
                            position = int(position)
                            do_schedule_action_device(
                                "set_wheel_position", [position], telescope_id
                            )
                        except ValueError:
                            logger.warn(
                                f"Invalid wheel position value: {position}. Skipping."
                            )
                else:
                    logger.warn("Missing 'params' for set_wheel_position.")
            case "action_set_dew_heater":
                heater_value = int(params.get("heater", 0))
                do_schedule_action_device(
                    "action_set_dew_heater", {"heater": heater_value}, telescope_id
                )
            case "start_up_sequence":
                startup_params = {
                    "auto_focus": params.get("auto_focus"),
                    "3ppa": params.get("polar_align"),
                    "dark_frames": params.get("dark_frames"),
                }
                do_schedule_action_device(
                    "start_up_sequence", startup_params, telescope_id
                )
            case "_":
                logger.warn(f"Unknown action '{action}' encountered; skipping.")


def get_live_status(telescope_id: int):
    dev = telescope.get_seestar_device(telescope_id)
    imager = telescope.get_seestar_imager(telescope_id)
    template = fetch_template("live_status.html")

    previous_state = pydash.get(dev.view_state, "state")
    previous_stage = pydash.get(dev.view_state, "stage")
    previous_mode = pydash.get(dev.view_state, "mode")

    def human_ts(elapsed):
        if elapsed is None:
            return ""
        return str(timedelta(seconds=int(elapsed / 1000)))

    while True:
        imager.update_live_status()
        method_sync(
            "get_view_state", telescope_id, id=42
        )  # don't call this if event is less than 5 seconds?
        # print("event_state", dev.event_state)
        # print("view_state", dev.view_state)
        substage = None
        substage_count = None
        substage_elapsed = None
        substage_position = None
        substage_percent = None
        stats = None
        state = pydash.get(dev.view_state, "state")
        stage = pydash.get(dev.view_state, "stage")
        mode = pydash.get(dev.view_state, "mode")
        stack = pydash.get(dev.view_state, "Stack")

        changed = (
            previous_stage != stage or previous_mode != mode or previous_state != state
        )
        previous_stage = stage
        previous_mode = mode
        previous_state = state

        if stage:
            substage = pydash.get(dev.view_state, f"{stage}.stage")
            substage_count = pydash.get(dev.view_state, f"{stage}.count")
            substage_elapsed = human_ts(pydash.get(dev.view_state, f"{stage}.lapse_ms"))
            substage_position = pydash.get(dev.view_state, f"{stage}.position")
            substage_percent = pydash.get(dev.view_state, f"{stage}.percent")
            # print("stage", stage, substage, dev.view_state.get(stage))

        if stack:
            stats = {
                "gain": stack.get("gain"),
                "integration_time": str(
                    timedelta(
                        seconds=stack.get("stacked_frame", 0)
                        * (int(pydash.get(stack, "Exposure.exp_ms", 10_000)) / 1000)
                    )
                ),
                "stacked_frame": stack.get("stacked_frame"),
                "dropped_frame": stack.get("dropped_frame"),
                "elapsed": human_ts(stack["lapse_ms"]),
            }

        response = {
            "target_name": pydash.get(dev.view_state, "target_name"),
            "state": state,
            "stage": stage,
            "substage": substage,
            "substage_count": substage_count,
            "substage_elapsed": substage_elapsed,
            "substage_position": substage_position,
            "substage_percent": substage_percent,
            "stats": stats,
            "mode": mode,
            "snr": imager.snr,
            "lapse_ms": human_ts(pydash.get(dev.view_state, "lapse_ms")),
            "ra": dev.ra,
            "dec": dev.dec,
        }

        status_update_frame = (
            "event: statusUpdate\ndata: "
            + json.dumps({"mode": mode, "stage": stage})
            + "\n\n"
        )

        mode_change_frame = ""
        if changed:
            mode_change_frame = (
                "event: liveViewModeChange\ndata: "
                + json.dumps({"mode": mode})
                + "\n\n"
            )

        frame = ""
        avi_record = pydash.get(dev.view_state, "AviRecord")
        if not avi_record:
            avi_record = {"state": "stopped"}
        frame += "event: capture_status\ndata: " + json.dumps(avi_record) + "\n\n"

        rtsp = pydash.get(dev.view_state, "RTSP")
        if rtsp and pydash.get(rtsp, "state") == "working":
            roi = pydash.get(rtsp, "roi_index", 0)
            match roi:
                case 0:
                    zoom = "1x"
                case 1:
                    zoom = "2x"
                case 2:
                    zoom = "4x"
                case _:
                    zoom = "1x"
            frame += "event: zoom\ndata: " + zoom + "\n\n"

        status = template.render(state=response).replace("\n", "")
        status_frame = "data: " + status + "\n\n"

        # print sending...
        yield (
            status_update_frame.encode("utf-8")
            + mode_change_frame.encode("utf-8")
            + status_frame.encode("utf-8")
            + frame.encode("utf-8")
        )
        time.sleep(0.5)


def determine_file_type(file_path):
    """Determines if a file is CSV or JSON."""
    try:
        with open(file_path, "r") as file:
            json.load(file)
        return "json"
    except json.JSONDecodeError:
        try:
            with open(file_path, "r") as file:
                csv.Sniffer().sniff(file.read(1024))
            return "csv"
        except csv.Error:
            return "unknown"


class BaseResource:
    def on_get(
        self, req: falcon.Request, resp: falcon.Response, telescope_id: int = 1
    ) -> None:
        self.send_text(req, resp, telescope_id, "placeholder on_get")

    def on_post(
        self, req: falcon.Request, resp: falcon.Response, telescope_id: int = 1
    ):
        self.send_text(req, resp, telescope_id, "placeholder on_post")

    def on_delete(
        self, req: falcon.Request, resp: falcon.Response, telescope_id: int = 1
    ):
        self.send_text(req, resp, telescope_id, "placeholder on_delete")

    def send_text(
        self, req: falcon.Request, resp: falcon.Response, telescope_id: int, text: str
    ):
        print(f"send_text {telescope_id=}: {text}")
        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = text


class HomeResource:
    @staticmethod
    def on_get(req, resp):
        now = datetime.now()
        telescopes = get_telescopes_state()
        telescope = telescopes[0]  # We just force it to first telescope
        context = get_context(telescope["device_num"], req)
        del context["telescopes"]
        if len(telescopes) > 1:
            redirect(f"/{telescope['device_num']}/")
        else:
            render_template(
                req, resp, "index.html", now=now, telescopes=telescopes, **context
            )


class HomeTelescopeResource:
    @staticmethod
    def on_get(req, resp, telescope_id):
        now = datetime.now()
        telescopes = get_telescopes_state()
        context = get_context(telescope_id, req)
        if "telescopes" in context:
            del context["telescopes"]
        render_template(
            req, resp, "index.html", now=now, telescopes=telescopes, **context
        )


class ImageResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.image(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_create_image(req, resp, False, telescope_id)
        self.image(req, resp, values, errors, telescope_id)

    @staticmethod
    def image(req, resp, values, errors, telescope_id):
        context = get_context(telescope_id, req)

        if not context["online"]:
            telescope_id = 0

        current = do_action_device("get_schedule", telescope_id, {})
        if current is None:
            return
        state = current["Value"]["state"]
        schedule = current["Value"]

        # remove values=values to stop remembering values
        render_template(
            req,
            resp,
            "image.html",
            state=state,
            schedule=schedule,
            values=values,
            errors=errors,
            action=f"/{telescope_id}/image",
            **context,
        )


class GotoResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.goto(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_goto_target(req, resp, telescope_id)
        self.goto(req, resp, values, errors, telescope_id)

    @staticmethod
    def goto(req, resp, values, errors, telescope_id):
        schedule = {}
        state = {}
        context = get_context(telescope_id, req)

        if context["online"]:
            current = do_action_device("get_schedule", telescope_id, {})
            if current is not None:
                state = current["Value"]["state"]

                if state == "working":
                    flash(resp, "Scheduler is running. Cannot perform goto.")

        # remove values=values to stop remembering values
        render_template(
            req,
            resp,
            "goto.html",
            state=state,
            schedule=schedule,
            values=values,
            errors=errors,
            action=f"/{telescope_id}/goto",
            **context,
        )


class CommandResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.command(req, resp, telescope_id, {})

    def on_post(self, req, resp, telescope_id=0):
        output = do_command(req, resp, telescope_id)
        self.command(req, resp, telescope_id, output)

    @staticmethod
    def command(req, resp, telescope_id, output):
        context = get_context(telescope_id, req)
        if not context["online"]:
            telescope_id = 0

        current = do_action_device("get_schedule", telescope_id, {})
        if current is not None:
            schedule = current["Value"]
            state = schedule["state"]
        else:
            schedule = {}
            state = "stopped"

        render_template(
            req,
            resp,
            "command.html",
            state=state,
            schedule=schedule,
            action=f"/{telescope_id}/command",
            output=output,
            **context,
        )


class ConsoleResource(BaseResource):
    def on_get(self, req, resp, telescope_id=1):
        context = get_context(telescope_id, req)
        render_template(req, resp, "console.html", **context)

    def on_post(self, req, resp, telescope_id=1):
        resp.status = falcon.HTTP_200
        resp.content_type = "application/json"
        print(type(req.media), req.media)
        resp.text = json.dumps(do_action_device("method_sync", telescope_id, req.media))


class MosaicResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.mosaic(req, resp, {}, {}, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        values, errors = do_create_mosaic(req, resp, False, telescope_id)
        self.mosaic(req, resp, values, errors, telescope_id)

    @staticmethod
    def mosaic(req, resp, values, errors, telescope_id):
        context = get_context(telescope_id, req)
        if not context["online"]:
            telescope_id = 0

        current = do_action_device("get_schedule", telescope_id, {})
        if current is None:
            return
        state = current["Value"]["state"]
        schedule = current["Value"]

        # remove values=values to stop remembering values
        render_template(
            req,
            resp,
            "mosaic.html",
            state=state,
            schedule=schedule,
            values=values,
            errors=errors,
            action=f"/{telescope_id}/mosaic",
            **context,
        )


class ScheduleResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_startup.html", "startup", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_startup.html", "startup", {}, {}
        )


class ScheduleWaitUntilResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_wait_until.html", "wait-until", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        waitUntil = data.get("waitUntil", "")
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            response = do_schedule_action_device(
                "wait_until", {"local_time": waitUntil}, telescope_id
            )
        else:
            response = do_insert_schedule_item(
                "wait_until", {"local_time": waitUntil}, selected_items, telescope_id
            )

        logger.info("POST scheduled request %s", response)
        render_schedule_tab(
            req, resp, telescope_id, "schedule_wait_until.html", "wait-until", {}, {}
        )


class ScheduleWaitForResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_wait_for.html", "wait-for", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        waitFor = data.get("waitFor", "")
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            response = do_schedule_action_device(
                "wait_for", {"timer_sec": int(waitFor)}, telescope_id
            )
        else:
            response = do_insert_schedule_item(
                "wait_for", {"timer_sec": int(waitFor)}, selected_items, telescope_id
            )

        logger.info("POST scheduled request %s", response)
        render_schedule_tab(
            req, resp, telescope_id, "schedule_wait_for.html", "wait-for", {}, {}
        )


class ScheduleAutoFocusResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_auto_focus.html", "auto-focus", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        autoFocus = data.get("autoFocus", "")
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            response = do_schedule_action_device(
                "auto_focus", {"try_count": int(autoFocus)}, telescope_id
            )
        else:
            response = do_insert_schedule_item(
                "auto_focus",
                {"try_count": int(autoFocus)},
                selected_items,
                telescope_id,
            )

        logger.info("POST scheduled request %s", response)
        render_schedule_tab(
            req, resp, telescope_id, "schedule_auto_focus.html", "auto-focus", {}, {}
        )


class ScheduleFocusResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_focus.html", "focus", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        focus_steps = data.get("focusSteps", "")
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            response = do_schedule_action_device(
                "adjust_focus", {"steps": int(focus_steps)}, telescope_id
            )
        else:
            response = do_insert_schedule_item(
                "adjust_focus",
                {"steps": int(focus_steps)},
                selected_items,
                telescope_id,
            )

        logger.info("POST scheduled request %s", response)
        render_schedule_tab(
            req, resp, telescope_id, "schedule_focus.html", "focus", {}, {}
        )


class ScheduleImageResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_image.html", "image", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        values, errors = do_create_image(req, resp, True, telescope_id)
        render_schedule_tab(
            req, resp, telescope_id, "schedule_image.html", "image", values, errors
        )


class ScheduleMosaicResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_mosaic.html", "mosaic", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        values, errors = do_create_mosaic(req, resp, True, telescope_id)
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_mosaic.html", "mosaic", values, errors
        )


class ScheduleStartupResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_startup.html", "startup", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        auto_focus = data.get("auto_focus") == "on"
        polar_align = data.get("polar_align") == "on"
        dark_frames = data.get("dark_frames") == "on"
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])

        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device(
                "start_up_sequence",
                {
                    "auto_focus": auto_focus,
                    "dark_frames": dark_frames,
                    "3ppa": polar_align,
                },
                telescope_id,
            )
        else:
            do_insert_schedule_item(
                "start_up_sequence",
                {
                    "auto_focus": auto_focus,
                    "dark_frames": dark_frames,
                    "3ppa": polar_align,
                },
                selected_items,
                telescope_id,
            )

        render_schedule_tab(
            req, resp, telescope_id, "schedule_startup.html", "startup", {}, {}
        )


class ScheduleShutdownResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_shutdown.html", "shutdown", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device("shutdown", {}, telescope_id)
        else:
            do_insert_schedule_item("shutdown", {}, selected_items, telescope_id)

        render_schedule_tab(
            req, resp, telescope_id, "schedule_shutdown.html", "shutdown", {}, {}
        )


class ScheduleParkResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_park.html", "park", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        online = check_api_state(telescope_id)

        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device("scope_park", {}, telescope_id)
        else:
            do_insert_schedule_item("scope_park", {}, selected_items, telescope_id)

        render_schedule_tab(
            req, resp, telescope_id, "schedule_park.html", "park", {}, {}
        )


class ScheduleLpfResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(req, resp, telescope_id, "schedule_lpf.html", "lpf", {}, {})

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])
        useLpfilter = data.get("lpf") == "on"
        if useLpfilter:
            cmd_vals = [2]
        else:
            cmd_vals = [1]

        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device("set_wheel_position", cmd_vals, telescope_id)
        else:
            do_insert_schedule_item(
                "set_wheel_position", cmd_vals, selected_items, telescope_id
            )

        render_schedule_tab(req, resp, telescope_id, "schedule_lpf.html", "lpf", {}, {})


class ScheduleDewHeaterResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0
        render_schedule_tab(
            req, resp, telescope_id, "schedule_dew_heater.html", "dew-heater", {}, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        dewHeaterValue = data.get("dewHeaterValue")
        action = data.get("action", "")
        selected_items = data.get("selected_items", [])

        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device(
                "action_set_dew_heater", {"heater": int(dewHeaterValue)}, telescope_id
            )
        else:
            do_insert_schedule_item(
                "action_set_dew_heater",
                {"heater": int(dewHeaterValue)},
                selected_items,
                telescope_id,
            )

        render_schedule_tab(
            req, resp, telescope_id, "schedule_dew_heater.html", "dew-heater", {}, {}
        )


class ScheduleExposureResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0

        settings = method_sync("get_setting", telescope_id)
        defexp = pydash.get(settings, "exp_ms.stack_l", Config.init_expo_stack_ms)
        values = {"defexp": int(defexp)}
        render_schedule_tab(
            req, resp, telescope_id, "schedule_exposure.html", "exposure", values, {}
        )

    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        expValue = pydash.get(data, "exposure", 10000)
        action = pydash.get(data, "action", "")
        selected_items = pydash.get(data, "selected_items", [])

        online = check_api_state(telescope_id)
        if not online:
            telescope_id = 0

        if action == "append":
            do_schedule_action_device(
                "action_set_exposure", {"exp": int(expValue)}, telescope_id
            )
        else:
            do_insert_schedule_item(
                "action_set_exposure",
                {"exp": int(expValue)},
                selected_items,
                telescope_id,
            )

        render_schedule_tab(
            req, resp, telescope_id, "schedule_exposure.html", "exposure", {}, {}
        )


class ScheduleToggleResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.display_state(req, resp, telescope_id)

    def on_post(self, req, resp, telescope_id=0):
        current = do_action_device("get_schedule", telescope_id, {})
        value = current.get("Value", {})
        action = req.media.get("action")
        state = value.get("state")
        if action == "toggle":
            if state == "stopped" or state == "complete":
                do_action_device("start_scheduler", telescope_id, {})
            else:
                do_action_device("stop_scheduler", telescope_id, {})
        elif action == "pause":
            paused = value.get("is_stacking_paused")
            if state == "working":
                if paused:
                    print("RESUMING")
                    do_action_device("continue_scheduler", telescope_id, {})
                else:
                    print("PAUSING")
                    do_action_device("pause_scheduler", telescope_id, {})

        elif action == "skip":
            current_item_id = value.get("current_item_id")
            if current_item_id:
                do_action_device("skip_scheduler_cur_item", telescope_id, {})
        else:
            pass
        self.display_state(req, resp, telescope_id)

    @staticmethod
    def display_state(req, resp, telescope_id):
        context = get_context(telescope_id, req)
        current = do_action_device("get_schedule", telescope_id, {})
        if current.get("Value"):
            state = current["Value"]["state"]
        else:
            state = "stopped"
        render_template(
            req, resp, "partials/schedule_state.html", state=state, **context
        )


class ScheduleDeleteResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        data = req.media
        selected_items = data.get("selected_items", [])

        if isinstance(selected_items, list):
            for item in selected_items:
                do_action_device(
                    "remove_schedule_item", telescope_id, {"schedule_item_id": item}
                )
        else:
            do_action_device(
                "remove_schedule_item",
                telescope_id,
                {"schedule_item_id": selected_items},
            )

        render_schedule_tab(
            req, resp, telescope_id, "schedule_startup.html", "startup", {}, {}
        )


class ScheduleClearResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        if check_api_state(telescope_id):
            current = do_action_device("get_schedule", telescope_id, {})
            state = current["Value"]["state"]

            if state == "working":
                do_action_device("stop_scheduler", telescope_id, {})
                flash(resp, "Stopping scheduler")

            do_action_device("create_schedule", telescope_id, {})
            flash(resp, "Created New Schedule")
            redirect(f"/{telescope_id}/schedule")
        else:
            # global queue
            # queue = {}
            do_action_device("create_schedule", 0, {})
            flash(resp, "Created New Schedule")
            redirect("/0/schedule")

        flash(resp, "Created New Schedule")
        redirect(f"/{telescope_id}/schedule")


class ScheduleDownloadSchedule:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        print("Download schedule")
        filename = req.media.get("filename")
        if not filename:
            raise HTTPInternalServerError(description="Filename is required.")
        if not filename.lower().endswith(".json"):
            filename = filename + ".json"

        directory = os.path.join(os.getcwd(), "schedule")
        file_path = os.path.join(directory, filename)

        # Ensure the file is created
        do_action_device("export_schedule", telescope_id, {"filepath": file_path})

        # Check if the file exists
        if not os.path.isfile(file_path):
            raise HTTPNotFound(description="Schedule file not found.")

        try:
            resp.content_type = "application/json"
            resp.downloadable_as = filename
            with open(file_path, "r", encoding="utf-8") as file:
                resp.text = file.read()
        except Exception as e:
            raise HTTPInternalServerError(description="Error reading file.") from e
        finally:
            if os.path.isfile(file_path):
                os.remove(file_path)


class ScheduleExportResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        filename = req.media["filename"]
        if not filename.lower().endswith(".json"):
            filename = filename + ".json"
        directory = os.path.join(os.getcwd(), "schedule")
        file_path = os.path.join(directory, filename)

        do_action_device("export_schedule", telescope_id, {"filepath": file_path})
        redirect(f"/{telescope_id}/schedule")


class ScheduleImportResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        form = req.media
        selected_file = form.get("schedule_file")

        if not selected_file:
            raise falcon.HTTPBadRequest("Missing Parameter", "No file selected")

        directory = os.path.join(os.getcwd(), "schedule")
        file_path = os.path.join(directory, selected_file)
        file_type = determine_file_type(file_path)

        if file_type == "csv":
            with open(file_path, "r", encoding="utf-8") as file:
                string_data = file.read().splitlines()
            import_csv_schedule(string_data, telescope_id)

        elif file_type == "json":
            do_action_device(
                "import_schedule",
                telescope_id,
                {"filepath": file_path, "is_retain_state": False},
            )

        else:
            flash(
                resp,
                f"Invalid file type for {selected_file}. Only .csv or .json are allowed",
            )
            return redirect(f"/{telescope_id}/schedule")

        flash(resp, f"Schedule imported from {selected_file}.")
        redirect(f"/{telescope_id}/schedule")


class ScheduleUploadResource:
    @staticmethod
    def on_post(req, resp, telescope_id=0):
        directory = os.path.join(os.getcwd(), "schedule")

        data = req.get_media()
        part = None
        for part in data:
            filename = part.filename
            file_path = os.path.join(directory, filename)

            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(part.data.decode("utf-8"))

                file_type = determine_file_type(file_path)
                if file_type == "csv":
                    with open(file_path, "r", encoding="utf-8") as file:
                        string_data = file.read().splitlines()
                    import_csv_schedule(string_data, telescope_id)

                elif file_type == "json":
                    do_action_device(
                        "import_schedule",
                        telescope_id,
                        {"filepath": file_path, "is_retain_state": False},
                    )

                else:
                    flash(
                        resp,
                        f"Invalid file type for {filename}. Only .csv or .json are allowed",
                    )
                    return redirect(f"/{telescope_id}/schedule")

                flash(resp, f"Schedule imported from {filename}.")

            except Exception as e:
                flash(resp, f"An error occured while saving the file: {str(e)}.")

            finally:
                if os.path.isfile(file_path):
                    os.remove(file_path)

        redirect(f"/{telescope_id}/schedule")


class ScheduleReStartResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        do_action_device("reset_scheduler_cur_item", telescope_id, {})
        context = get_context(telescope_id, req)
        current = do_action_device("get_schedule", telescope_id, {})
        context.get("current_item")["schedule_item_id"] = (
            ""  # context may have been cached, so reset current item id
        )
        if current is not None:
            schedule = current.get("Value", {})
            state = schedule.get("state", "")
        else:
            schedule = {}
            state = "stopped"

        html = self.render_schedule_list_html(req, resp, schedule, context)
        state_html = self.render_schedule_state_html(req, resp, state, context)
        resp.media = {"state": state, "html": html, "state_html": state_html}
        resp.content_type = "application/json"
        resp.status = falcon.HTTP_200

    def render_schedule_list_html(self, req, resp, schedule, context):
        template = fetch_template("partials/schedule_list.html")
        webui_theme = Config.uitheme
        version = Version.app_version()

        html = template.render(
            flashed_messages=get_flash_cookie(req, resp),
            messages=get_messages(),
            webui_theme=webui_theme,
            version=version,
            schedule=schedule,
            **context,
        )

        return html

    def render_schedule_state_html(self, req, resp, state, context):
        template = fetch_template("partials/schedule_state.html")
        webui_theme = Config.uitheme
        version = Version.app_version()

        html = template.render(
            flashed_messages=get_flash_cookie(req, resp),
            messages=get_messages(),
            webui_theme=webui_theme,
            version=version,
            state=state,
            **context,
        )

        return html


class ScheduleRefreshResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        context = get_context(telescope_id, req)
        current = do_action_device("get_schedule", telescope_id, {})
        if current is not None:
            schedule = current.get("Value", {})
            state = schedule.get("state", "")
        else:
            schedule = {}
            state = "stopped"

        html = self.render_schedule_list_html(req, resp, schedule, context)
        resp.media = {"state": state, "html": html}
        resp.content_type = "application/json"
        resp.status = falcon.HTTP_200

    def render_schedule_list_html(self, req, resp, schedule, context):
        template = fetch_template("partials/schedule_list.html")
        webui_theme = Config.uitheme
        version = Version.app_version()
        open_accordion_id = req.get_param("open_accordion_id", default="")

        html = template.render(
            flashed_messages=get_flash_cookie(req, resp),
            messages=get_messages(),
            webui_theme=webui_theme,
            version=version,
            schedule=schedule,
            open_accordion_id=open_accordion_id,
            **context,
        )

        return html


class EventStatus:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        results = []
        action = req.get_param("action")
        if action == "command":
            eventlist = [
                "WheelMove",
                "AutoFocus",
                "DarkLibrary",
                "3PPA",
                "PlateSolve",
                "Scheduler",
            ]
        elif action == "goto":
            eventlist = ["WheelMove", "AutoGoto", "PlateSolve"]
        elif action == "image" or action == "mosaic":
            eventlist = [
                "WheelMove",
                "AutoGoto",
                "PlateSolve",
                "DarkLibrary",
                "AutoFocus",
                "Stack",
            ]
        else:
            eventlist = ["WheelMove", "AutoFocus", "AutoGoto", "PlateSolve"]
        context = get_context(telescope_id, req)
        now = datetime.now()
        event_state = do_action_device("get_event_state", telescope_id, {})

        if event_state is None:
            event_state = {}
            events = {}

        if "Value" in event_state:
            events = event_state["Value"]
            if "result" in events:
                if isinstance(events, dict):
                    result_info = events["result"]
                    if isinstance(result_info, dict):
                        for event_key, event_value in result_info.items():
                            if isinstance(event_value, dict):
                                results.append(event_value)
            else:
                if events:
                    for device_id, device_info in events.items():
                        # Ensure device_info contains "result" and it is a dictionary
                        if isinstance(device_info, dict) and "result" in device_info:
                            result_info = device_info["result"]
                            if isinstance(result_info, dict):
                                for event_key, event_value in result_info.items():
                                    if isinstance(event_value, dict):
                                        # Add the device ID to each event
                                        event_value["DeviceID"] = device_id
                                        results.append(event_value)

        render_template(
            req,
            resp,
            "eventstatus.html",
            results=results,
            events=eventlist,
            now=now,
            **context,
        )


class LivePage:
    @staticmethod
    def on_get(req, resp, telescope_id=1, mode=None):
        status = method_sync("get_view_state", telescope_id)
        context = get_context(telescope_id, req)
        now = datetime.now()
        if status is None:
            render_template(
                req,
                resp,
                "live.html",
                now=now,
                action=f"/{telescope_id}/goto",
                **context,
            )
            return
        logger.info(status)
        view = pydash.get(status, "View")
        match mode:
            case "solar_sys":
                render_template(
                    req, resp, "live_solarsys.html", now=now, view=view, **context
                )

            case "moon":
                render_template(req, resp, "live_moon.html", now=now, **context)

            case "planet":
                render_template(req, resp, "live_planet.html", now=now, **context)

            case "scenery":
                render_template(req, resp, "live_scenery.html", now=now, **context)

            case "star":
                render_template(req, resp, "live_star.html", now=now, **context)

            case "sun":
                render_template(req, resp, "live_sun.html", now=now, **context)

            case _:
                # If status has a view mode, redirect first
                current_mode = status.get("View", {}).get("mode", {})
                if current_mode in ["moon", "planet", "scenery", "star", "sun"]:
                    redirect(f"/{telescope_id}/live/{current_mode}")
                else:
                    render_template(req, resp, "live.html", now=now, **context)


class LiveModeResource:
    def on_delete(self, req, resp, telescope_id=1):
        # Disabled watch mode.  Stop schedule if there's a schedule
        schedule = do_action_device("get_schedule", telescope_id, {})
        scheduler_status = pydash.get(schedule, "Value.state")
        if scheduler_status in ["running", "working"]:
            do_action_device("stop_scheduler", telescope_id, {})
        else:
            do_action_device(
                "method_async", telescope_id, {"method": "iscope_stop_view"}
            )
        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = "none"

    def on_post(self, req, resp, telescope_id=1):
        mode = req.media["mode"]
        params = req.media
        # xxx: If mode is none, need to cancel things
        do_action_device(
            "method_async",
            telescope_id,
            {"method": "iscope_start_view", "params": params},
        )
        # match mode:
        #     case 'moon':
        #         response = do_action_device("method_async", telescope_id, {
        #             "method": "start_scan_planet",
        #         })
        #         print("Moon response:", response)

        # {  "id" : 111, "method" : "start_scan_planet"}

        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = mode


class LiveGotoResource(BaseResource):
    def on_post(self, req, resp, telescope_id=1):
        target = req.media["target"]

        if target in ["moon", "Moon", "sun", "Sun"]:
            # This will go to the current "planet"
            response = do_action_device(
                "method_async",
                telescope_id,
                {
                    "method": "start_scan_planet",
                },
            )
            print(f"{target} response:", response)

        self.send_text(req, resp, telescope_id, target)


# deprecated!
# class LiveExposureModeResource:
#     def on_post(self, req, resp, telescope_id=1):
#         mode = req.media["exposure_mode"]
#         # xxx: If mode is none, need to cancel things
#         # response = do_action_device("method_async", telescope_id,
#         #                             {"method": "iscope_start_view", "params": {"mode": mode}})
#         print("changing mode to", mode)
#
#         dev = telescope.get_seestar_imager(telescope_id)
#         dev.set_exposure_mode(mode)
#
#         resp.status = falcon.HTTP_200
#         resp.content_type = 'application/text'
#         resp.text = mode


class LiveExposureRecordResource:
    def on_post(self, req, resp, telescope_id=1):
        logger.info("Starting to record")
        response = do_action_device(
            "method_async",
            telescope_id,
            {"method": "iscope_start_stack", "params": {"restart": True}},
        )
        print(f"LiveExposureRecordResource: {response=}")
        # Note: streaming should stop automatically in imaging system...

        resp.status = falcon.HTTP_200
        resp.content_type = "application/text"
        resp.text = "Ok"


class LiveGainResource:
    def on_get(self, req, resp, telescope_id: int = 1):
        output = do_action_device(
            "method_sync", telescope_id, {"method": "get_setting"}
        )

        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = str(math.trunc(pydash.get(output, "Value.result.isp_gain")))

    def on_post(self, req, resp, telescope_id: int = 1):
        gain = int(req.media["gain"])
        # print("LiveFocusResource.post", increment)

        if 0 <= gain <= 300:
            do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"manual_exp": True}},
            )
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"isp_gain": gain}},
            )
            print("LiveGainResource.post return", output, "gain:", gain)

        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = str(gain)


class LiveExposureResource:
    def on_get(self, req, resp, telescope_id: int = 1):
        output = do_action_device(
            "method_sync", telescope_id, {"method": "get_setting"}
        )

        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = str(math.trunc(pydash.get(output, "Value.result.isp_exp_ms")))

    def on_post(self, req, resp, telescope_id: int = 1):
        exposure = int(req.media["exposure"])
        # print("LiveFocusResource.post", increment)

        if 1 <= exposure <= 200:
            do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"manual_exp": True}},
            )
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "set_setting", "params": {"isp_exp_ms": exposure}},
            )
            print("LiveExposureResource.post return", output, "gain:", exposure)

        resp.status = falcon.HTTP_200
        resp.content_type = "text/plain"
        resp.text = str(exposure)


class LivePhotoResource(BaseResource):
    pass


class LiveZoomResource(BaseResource):
    def on_post(self, req, resp, telescope_id: int = 1):
        zoom = int(req.media.get("zoom", 0))
        output = method_sync("set_setting", params={"rtsp_roi_index": zoom})
        method_sync(
            "get_view_state", telescope_id, id=42
        )  # don't call this if event is less than 5 seconds?
        print(f"Zoom response: {output}")
        self.send_text(req, resp, telescope_id, "done")


class LiveVideoResource(BaseResource):
    def on_get(self, req, resp, telescope_id: int = 1):
        # print("LiveViewResource.on_get telescope_id:", telescope_id)
        dev = telescope.get_seestar_device(telescope_id)
        method_sync(
            "get_view_state", telescope_id, id=42
        )  # don't call this if event is less than 5 seconds?

        state = pydash.get(dev.view_state, "AviRecord.state")
        if not state:
            state = "stopped"

        context = get_context(telescope_id, req)
        if state == "working":
            render_template(
                req, resp, "partials/live_video_stop.html", state=state, **context
            )
        else:
            render_template(
                req, resp, "partials/live_video_record.html", state=state, **context
            )

    def on_post(self, req, resp, telescope_id: int = 1):
        # If status is stopped, start recording, otherwise stop
        dev = telescope.get_seestar_device(telescope_id)

        # previous_state = pydash.get(dev.view_state, "state")
        # previous_stage = pydash.get(dev.view_state, "stage")
        # previous_mode = pydash.get(dev.view_state, "mode")
        # {'state': 'working', 'lapse_ms': 9741094, 'mode': 'solar_sys', 'target_type': 'sun', 'cam_id': 0,
        #  'lp_filter': False, 'planet_correction': True, 'scan_planet_tip': False, 'manual_exp': False,
        #  'RTSP': {'state': 'working', 'lapse_ms': 9738925, 'roi_index': 0, 'port': 4554}, 'stage': 'RTSP',
        #  'AutoFocus': {'state': 'complete', 'lapse_ms': 8858, 'center_xy': [894, 1183],
        #                'FocuserMove': {'state': 'complete', 'lapse_ms': 121, 'position': 1616}, 'stage': 'FocuserMove'},
        #  'AviRecord': {'state': 'working', 'lapse_ms': 228259, 'timelapse': {'enable': False}, 'note': 'mp4 record',
        #                'saved_frames': 6773, 'raw': False, 'file_saved': False}}

        print("ViewState:", dev.view_state)
        avi_status = pydash.get(dev.view_state, "AviRecord.state")
        if avi_status == "working":
            output = method_sync("stop_record_avi")
        else:
            raw = req.media.get("raw", None) is not None
            params = {
                "raw": raw,
            }
            timelapse = int(req.media.get("timelapse", "0"))
            if timelapse > 0:
                params["timelapse"] = {"enable": True, "delay_sec": timelapse}
            output = method_sync("start_record_avi", telescope_id, params=params)

        self.send_text(
            req, resp, telescope_id, f"LiveVideoResource.on_post return {output}"
        )


class LiveFocusResource(BaseResource):
    def __init__(self):
        self.focus = {}

    def on_get(self, req, resp, telescope_id: int = 1):
        output = self.current_focus(telescope_id)
        # print("Current focus:", output)

        self.send_text(req, resp, telescope_id, str(output))

    def on_post(self, req, resp, telescope_id: int = 1):
        focus = self.current_focus(telescope_id)
        increment = int(req.media["inc"])
        # print("LiveFocusResource.post", increment)

        if -50 <= increment <= 50:
            focus += increment
            ts = time.time()
            output = do_action_device(
                "method_sync",
                telescope_id,
                {"method": "move_focuser", "params": {"step": focus, "ret_step": True}},
            )
            te = time.time()
            print(f"move_focuser elapsed {te - ts:2.4f} seconds")
            focus = pydash.get(output, "Value.result.step")
            self.focus[telescope_id] = focus

        # print("LiveFocusResource.post return", focus)

        self.send_text(req, resp, telescope_id, str(focus))

    def current_focus(self, telescope_id):
        focus = pydash.get(self.focus, telescope_id)

        if focus is None:
            # ts = time.time()
            focus = method_sync("get_focuser_position", telescope_id)
            # te = time.time()
            # print(f'get_focuser_position elapsed {te - ts:2.4f} seconds')

            self.focus[telescope_id] = focus

        return focus


class LiveStatusResource(BaseResource):
    # deprecate?
    def __init__(self):
        self.stage = None
        self.mode = None
        self.state = None

    def on_get(self, req, resp, telescope_id=1):
        status = method_sync("get_view_state", telescope_id, id=42)
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
            view = status.get("View")
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
        resp.content_type = "text/html"

        trigger = {"statusUpdate": {"mode": mode, "stage": stage}}
        if changed:
            trigger = trigger | {"liveViewModeChange": mode}

        resp.set_header("HX-Trigger", json.dumps(trigger))
        # if star:
        # .  target_name, gain, stacked_frame, dropped_frame
        # .  Exposure: { lapse_ms, exp_ms }
        template = fetch_template("live_status.html")
        stats = None

        if (
            state == "working"
            and mode == "star"
            and stage == "Stack"
            and view.get("Stack")
        ):
            stack = view.get("Stack")
            target_name = target_name or stack.get("target_name")
            stats = {
                "gain": stack.get("gain"),
                "stacked_frame": stack.get("stacked_frame"),
                "dropped_frame": stack.get("dropped_frame"),
                "elapsed": str(timedelta(milliseconds=stack["lapse_ms"]))[:-3],
            }
        resp.text = template.render(
            tm=tm,
            state=state,
            mode=mode,
            stage=stage,
            stats=stats,
            target_name=target_name,
        )
        # 'Annotate': {'state': 'complete', 'lapse_ms': 3370, 'result': {'image_size': [1080, 1920], 'annotations': [
        #    {'type': 'ngc', 'names': ['NGC 6992', 'C 33'], 'pixelx': 394.698, 'pixely': 611.487, 'radius': 757.869}],


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


class SettingsResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.render_settings(req, resp, telescope_id, {})

    def on_post(self, req, resp, telescope_id=0):
        PostedSettings = req.media

        # Convert the form names back into the required format
        FormattedNewSettings = {
            "stack_lenhance": str2bool(PostedSettings["stack_lenhance"]),
            "stack_dither": {
                "pix": int(PostedSettings["stack_dither_pix"]),
                "interval": int(PostedSettings["stack_dither_interval"]),
                "enable": str2bool(PostedSettings["stack_dither_enable"]),
            },
            "exp_ms": {
                "stack_l": int(PostedSettings["exp_ms_stack_l"]),
                "continuous": int(PostedSettings["exp_ms_continuous"]),
            },
            "focal_pos": int(PostedSettings["focal_pos"]),
            "auto_power_off": str2bool(PostedSettings["auto_power_off"]),
            "auto_3ppa_calib": str2bool(PostedSettings["auto_3ppa_calib"]),
            "frame_calib": str2bool(PostedSettings["frame_calib"]),
            "manual_exp": str2bool(PostedSettings["manual_exp"]),
        }

        FormattedNewStackSettings = {
            "save_discrete_frame": str2bool(PostedSettings["save_discrete_frame"]),
            "save_discrete_ok_frame": str2bool(
                PostedSettings["save_discrete_ok_frame"]
            ),
            "light_duration_min": int(PostedSettings["light_duration_min"]),
        }

        # Dew Heater is wierd
        if str2bool(PostedSettings["heater_enable"]):
            do_action_device(
                "method_sync",
                telescope_id,
                {
                    "method": "pi_output_set2",
                    "params": {"heater": {"state": True, "value": 90}},
                },
            )
        else:
            do_action_device(
                "method_sync",
                telescope_id,
                {
                    "method": "pi_output_set2",
                    "params": {"heater": {"state": False, "value": 90}},
                },
            )

        settings_output = do_action_device(
            "method_sync",
            telescope_id,
            {"method": "set_setting", "params": FormattedNewSettings},
        )
        # For some stupid reason known only to ZWO, dark_mode is returned by get_setting as a boolean.
        # However when you set_setting it expects an integer representation of that boolean
        # Also, it doesn't like to be lumped in with the rest of the set_setting values.
        # It needs to be on its own.
        dark_mode_bool = str2bool(PostedSettings["dark_mode"])
        dark_mode_value = int(dark_mode_bool)
        dark_mode_output = do_action_device(
            "method_async",
            telescope_id,
            {"method": "set_setting", "params": {"dark_mode": dark_mode_value}},
        )
        # Live Stack Mode is another one like dark_mode.
        cont_capt = str2bool(PostedSettings["stack_cont_capt"])
        LiveModeSettings = {"stack": {"cont_capt": cont_capt}}
        live_mode_output = do_action_device(
            "method_sync",
            telescope_id,
            {"method": "set_setting", "params": LiveModeSettings},
        )
        # 4k Mode is another one like cont_capt
        drizzle2x = str2bool(PostedSettings["stack_drizzle2x"])
        DrizzleModeSettings = {"stack": {"drizzle2x": drizzle2x}}
        drizzle_mode_output = do_action_device(
            "method_sync",
            telescope_id,
            {"method": "set_setting", "params": DrizzleModeSettings},
        )
        stack_settings_output = do_action_device(
            "method_sync",
            telescope_id,
            {"method": "set_stack_setting", "params": FormattedNewStackSettings},
        )

        if (
            settings_output["ErrorNumber"]
            or stack_settings_output["ErrorNumber"]
            or live_mode_output["ErrorNumber"]
            or dark_mode_output["ErrorNumber"]
            or drizzle_mode_output["ErrorNumber"]
        ):
            output = "Error Updating Settings."
        else:
            output = "Successfully Updated Settings."

        # Delay for LP filter on (off doesn't need a delay), this is helpful for rendering the current status on page refresh.
        if FormattedNewSettings["stack_lenhance"]:
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
            if context["online"]:
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
            "auto_3ppa_calib": "Horizontal Calibration",
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
            "stack_lenhance": "Light Pollution (LP) Filter",
            "dark_mode": "Dark Mode",
            "stack_cont_capt": "Continuous Capture Mode",
            "stack_drizzle2x": "4k Live Stack Mode (2x Drizzle)",
        }
        # Maybe we can store this better?
        settings_helper_text = {
            "stack_dither_pix": "Dither by (x) pixels. Reset upon Seestar reboot.",
            "stack_dither_interval": "Dither every (x) sub frames. Reset upon Seestar reboot.",
            "stack_dither_enable": "Enable or disable dither. Reset upon Seestar reboot.",
            "exp_ms_stack_l": "Stacking Exposure Length (ms).",
            "exp_ms_continuous": "Continuous Preview Exposure Length (ms), used in the live view.",
            "save_discrete_ok_frame": "Save sub frames. (Doesn't include failed.)",
            "save_discrete_frame": 'Save failed sub frames. (Failed sub frames will have "_failed" added to their filename.)',
            "light_duration_min": "Light Duration Min.",
            "auto_3ppa_calib": "In AltAz mode, enable/disable automatic horizontal calibration at the start of an imaging session",
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
            "stack_lenhance": "Enable or disable light pollution (LP) Filter.",
            "dark_mode": "Enable or disable LEDs while imaging.",
            "stack_cont_capt": "Enabling continuous capture mode disables live stacking",
            "stack_drizzle2x": "Enables 2x drizzle on Live Stack for 4k Mode",
        }
        render_template(
            req,
            resp,
            "settings.html",
            settings=settings,
            settings_friendly_names=settings_friendly_names,
            settings_helper_text=settings_helper_text,
            output=output,
            **context,
        )


class PlanningResource:
    @staticmethod
    def on_get(req, resp, telescope_id=0):
        context = get_context(telescope_id, req)
        twilight_times = get_twilight_times()
        nearest_csc = get_nearest_csc()
        if nearest_csc["status_msg"] != "SUCCESS":
            nearest_csc["href"] = ""
            nearest_csc["full_img"] = ""

        planning_cards = get_planning_cards()
        local_timezone = tzlocal.get_localzone()
        current_time = datetime.now(local_timezone)
        utc_offset = current_time.utcoffset()
        utc_offset = int(
            utc_offset.total_seconds() / 3600
        )  # Convert the offset to hours, used for astromosaic

        config_lat = round(
            Config.init_lat, 2
        )  # Some of the 3rd party api's/embeds want rounded down.
        config_long = round(
            Config.init_long, 2
        )  # Some of the 3rd party api's/embeds want rounded down.
        render_template(
            req,
            resp,
            "planning.html",
            twilight_times=twilight_times,
            config_lat=config_lat,
            config_long=config_long,
            clear_sky_href=nearest_csc["href"],
            clear_sky_img_src=nearest_csc["full_img"],
            planning_cards=planning_cards,
            utc_offset=utc_offset,
            **context,
        )


class StatsResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        if telescope_id == 0:
            stats = {}
        else:
            stats = get_device_state(telescope_id)
        now = datetime.now()
        context = get_context(telescope_id, req)

        render_template(req, resp, "stats.html", stats=stats, now=now, **context)


class StartupResource(BaseResource):
    def on_get(self, req, resp, telescope_id=0):
        self.startup(req, resp, telescope_id, {})

    def on_post(self, req, resp, telescope_id=0):
        form = req.media
        action = form.get("action")
        output = None
        if action == "start":
            lat = form.get("lat", "").strip()
            long = form.get("long", "").strip()
            auto_focus = form.get("auto_focus", "False").strip() == "on"
            dark_frames = form.get("dark_frames", "False").strip() == "on"
            polar_align = form.get("polar_align", "False").strip() == "on"
            dec_pos_index = form.get("dec-offset", Config.dec_pos_index)

            params = {
                "auto_focus": auto_focus,
                "dark_frames": dark_frames,
                "3ppa": polar_align,
                "dec_pos_index": int(dec_pos_index),
            }

            if lat and long:
                params["lat"] = float(lat)
                params["lon"] = float(long)

            output = do_action_device("action_start_up_sequence", telescope_id, params)
        elif action == "stop":
            output = do_action_device("stop_scheduler", telescope_id, {})

        self.startup(req, resp, telescope_id, output)

    @staticmethod
    def startup(req, resp, telescope_id, output):
        context = get_context(telescope_id, req)
        if not context["online"]:
            telescope_id = 0

        current = do_action_device("get_schedule", telescope_id, {})
        if current is None:
            schedule = {}
            state = "stopped"
        else:
            schedule = current["Value"]
            state = schedule["state"]

        render_template(
            req,
            resp,
            "startup.html",
            state=state,
            schedule=schedule,
            action=f"/{telescope_id}/startup",
            output=output,
            **context,
        )


class GuestModeResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        context = get_context(telescope_id, req)
        if telescope_id == 0 or not context["online"]:
            state = {}
        else:
            state = get_guestmode_state(telescope_id)
        now = datetime.now()

        render_template(
            req,
            resp,
            "guestmode.html",
            state=state,
            now=now,
            action=f"/{telescope_id}/guestmode",
            **context,
        )

    def on_post(self, req, resp, telescope_id=0):
        do_command(req, resp, telescope_id)
        self.on_get(req, resp, telescope_id)


class SupportResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        context = get_context(telescope_id, req)
        render_template(req, resp, "support.html", **context)


class ReloadResource:
    @staticmethod
    def on_put(req, resp):
        pid = os.getpid()
        os.kill(pid, signal.SIGHUP)
        resp.status = falcon.HTTP_200


def Object(**kwargs):
    return type("Object", (), kwargs)


class SystemResource(BaseResource):
    def if_null(self, thread, name):
        if thread is None:
            return Object(name=name, is_alive=lambda: "n/a")
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
            for t in (
                self.if_null(
                    dev.get_msg_thread, f"ALPReceiveMessageThread.{telescope_name}"
                ),
                self.if_null(
                    dev.heartbeat_msg_thread,
                    f"ALPHeartbeatMessageThread.{telescope_name}",
                ),
                self.if_null(dev.scheduler_thread, f"SchedulerThread.{telescope_name}"),
                self.if_null(dev.mosaic_thread, f"MosaicThread.{telescope_name}"),
                self.if_null(
                    imager.heartbeat_msg_thread,
                    f"ImagingHeartbeatMessageThread.{telescope_name}",
                ),
                self.if_null(
                    imager.get_stream_thread, f"ImagingStreamThread.{telescope_name}"
                ),
                self.if_null(
                    imager.get_image_thread,
                    f"ImagingReceiveImageThread.{telescope_name}",
                ),
            ):
                threads.append(
                    {
                        "name": t.name,
                        "running": t.is_alive(),
                        "last_run": getattr(t, "last_run", "n/a"),
                    }
                )
        # for t in threading.enumerate():
        #    threads.append({
        #        "name": t.name,
        #        "running": t.is_alive(),
        #    })
        render_template(req, resp, "system.html", now=now, threads=threads, **context)


class SimbadResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        objName = urllib.parse.quote_plus(
            req.get_param("name")
        )  # get the name to lookup from the request
        try:
            r = requests.get(simbad_url + objName, timeout=10)
        except:
            resp.status = falcon.HTTP_500
            resp.content_type = "application/text"
            resp.text = "Request had communications error."
            return

        html_content = r.text

        # Find the start of the RA/Dec (J2000.0) information
        start_index = html_content.find("Coordinates(ICRS,ep=J2000,eq=2000):")

        # Find the end of the RA/Dec (J2000.0) information (end of the line)
        end_index = html_content.find(
            "(", start_index + 13
        )  # "Coordinates(IC".count)   # skip past the first (

        ra_dec_j2000 = html_content[start_index:end_index]

        # Clean up the extracted information
        ra_dec_j2000 = ra_dec_j2000.replace(
            "Coordinates(ICRS,ep=J2000,eq=2000):", ""
        ).strip()
        elements = re.split(r"\s+", ra_dec_j2000.strip())

        if len(elements) < 6:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Object not found"
            return

        elements[2] = round(float(elements[2]), 1)
        elements[5] = round(float(elements[5]), 1)
        ra_dec_j2000 = f"{elements[0]}h{elements[1]}m{elements[2]}s {elements[3]}d{elements[4]}m{elements[5]}s"

        # see if we should recommand the LP Filter
        substrings = ["---  ISM  ---", "---  HII  ---", "---  SNR  ---", "---  PN  ---"]

        lpFilter = False
        for substring in substrings:
            if substring in html_content:
                lpFilter = True
                break
        lpStr = " off"
        if lpFilter:
            lpStr = " on"

        ra_dec_j2000 += lpStr

        resp.status = falcon.HTTP_200
        resp.content_type = "application/text"
        resp.text = ra_dec_j2000
        return


# convert decimal RA into HMS format
def decimal_RA_to_Sexagesimal(deg: float) -> str:
    # Normalize the degree value
    total_hours = deg / 15.0  # Convert degrees to total hours
    total_hours = total_hours % 24  # Wrap around to stay within 0-24 hours

    hours = int(total_hours)
    minutes = int((total_hours - hours) * 60)
    seconds = (total_hours - hours - minutes / 60) * 3600

    # Ensure minutes and seconds are positive
    if minutes < 0:
        minutes += 60
        hours -= 1
    if seconds < 0:
        seconds += 60
        minutes -= 1

    return f"{hours}h{minutes:02}m{abs(seconds):.2f}s"


# Convert decimal DEC into DMS format
def decimal_DEC_to_Sexagesimal(deg: float) -> str:
    sign = "+" if deg >= 0 else "-"
    abs_deg = abs(deg)
    degrees = int(abs_deg)
    minutes = int((abs_deg - degrees) * 60)
    seconds = (abs_deg - degrees - minutes / 60) * 3600
    return f"{sign}{degrees}d{minutes:02}m{seconds:.2f}s"


def vector_to_ra_dec(vector):
    x, y, z = vector

    # Calculate declination (δ)
    dec = np.arcsin(z)
    dec_deg = np.degrees(dec)

    # Calculate right ascension (α)
    ra = np.arctan2(y, x)
    ra_deg = np.degrees(ra) % 360
    return ra_deg, dec_deg


class StellariumResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        stellarium_url = (
            "http://"
            + str(Config.sthost)
            + ":"
            + str(Config.stport)
            + "/api/objects/info"
        )
        try:
            r = requests.get(stellarium_url + "?format=json")
            html_content = r.text
        except:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Requst had communications error."
            return

        # Check if object is selected
        if html_content == "no current selection, and no name parameter given":
            stellarium_url = (
                "http://"
                + str(Config.sthost)
                + ":"
                + str(Config.stport)
                + "/api/main/view?coord=j2000"
            )
            try:
                r = requests.get(stellarium_url)
                html_content = r.text
            except:
                resp.status = falcon.HTTP_404
                resp.content_type = "application/text"
                resp.text = "Requst had communications error."
                return
            # {"jNow":"[-0.924712, -0.0336335, -0.428692]"}
            StelJSON = json.loads(html_content)
            ra_j2000, dec_J2000 = vector_to_ra_dec(json.loads(StelJSON["j2000"]))
            objName = "Unknown"
            lpFilter = False

        else:
            StelJSON = json.loads(html_content)
            ra_j2000 = StelJSON["raJ2000"]
            dec_J2000 = StelJSON["decJ2000"]
            objName = "Unknown"
            if StelJSON["object-type"] == "star" and StelJSON["name"] == "":
                objName = "Unnamed Star"
            else:
                if StelJSON["localized-name"] != "":
                    objName = StelJSON["localized-name"]
                elif StelJSON["name"] != "":
                    objName = StelJSON["localized-name"]
                elif StelJSON["designations"] != "":
                    tmpObj = StelJSON["designations"]
                    objName = tmpObj.split(" - ")[0]
                else:
                    # Should never get here but whatever
                    objName = "Unknown"

            lpFilter = False
            objType = StelJSON["type"]
            filterTypes = [
                "HII region",
                "emission nebula",
                "supernova remnant",
                "planetary nebula",
            ]
            if objType in filterTypes:
                lpFilter = True

        resp.status = falcon.HTTP_200
        resp.content_type = "application/text"
        tmpText = json.dumps(
            {
                "ra": decimal_RA_to_Sexagesimal(ra_j2000),
                "dec": decimal_DEC_to_Sexagesimal(dec_J2000),
                "lp": lpFilter,
                "name": objName,
            }
        )
        resp.text = tmpText


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


class TelescopePositionResource(BaseResource):
    def on_post(self, req, resp, telescope_id=1):
        form = req.media
        # print("position", form)

        distance = form.get("distance", 0)
        angle = form.get("angle", 0)
        force = form.get("force", 0)
        if distance == 0:
            do_action_device(
                "method_sync",
                telescope_id,
                {
                    "method": "scope_speed_move",
                    "params": {"speed": 0, "angle": 0, "dur_sec": 3},
                },
            )
        else:
            speed = min(distance * 14.4 * force, 1440.0)
            # print("speed", speed)
            do_action_device(
                "method_sync",
                telescope_id,
                {
                    "method": "scope_speed_move",
                    "params": {"speed": speed, "angle": int(angle), "dur_sec": 3},
                },
            )
            method_sync("scope_get_equ_coord", telescope_id, id=420)
            # do_action_device('scope_speed_move', telescope_id, {
            #     "speed": int(distance * 5), "angle": angle, "dur_sec": 1
            # })
        # xxx: Get current Alt-Az position?
        dev = telescope.get_seestar_device(telescope_id)

        resp.status = falcon.HTTP_200
        resp.content_type = "application/text"
        resp.text = f'<div class="row"><div class="col">RA</div><div class="col">{dev.ra}</div></div> <div class="row"><div class="col">Dec</div><div class="col">{dev.dec}</div></div>'


class ToggleUIThemeResource:
    @staticmethod
    def on_get(req, resp):
        if getattr(
            sys, "frozen", False
        ):  # frozen means that we are running from a bundled app
            config_file = os.path.abspath(os.path.join(sys._MEIPASS, "config.toml"))
        else:
            config_file = os.path.join(
                os.path.dirname(__file__), "../device/config.toml"
            )
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


class TogglePlanningCardResource:
    @staticmethod
    def on_post(req, resp):
        PostedForm = req.media
        card_name = str(PostedForm["card_name"])
        # Get current card state
        current_card_state = get_planning_card_state(card_name)
        if current_card_state["planning_page_enable"]:
            update_planning_card_state(card_name, "planning_page_enable", False)
        else:
            update_planning_card_state(card_name, "planning_page_enable", True)


class CollapsePlanningCardResource:
    @staticmethod
    def on_post(req, resp):
        PostedForm = req.media
        card_name = str(PostedForm["card_name"])
        # Get current card state
        current_card_state = get_planning_card_state(card_name)
        if current_card_state["planning_page_collapsed"]:
            update_planning_card_state(card_name, "planning_page_collapsed", False)
        else:
            update_planning_card_state(card_name, "planning_page_collapsed", True)


class UpdateTwilightTimesResource:
    @staticmethod
    def on_post(req, resp):
        referer = req.get_header("Referer")
        PostedForm = req.media
        PostedLat = PostedForm[
            "Latitude"
        ]  # TODO: This should have some type of input check
        PostedLon = PostedForm[
            "Longitude"
        ]  # TODO: This should have some type of input check
        update_twilight_times(PostedLat, PostedLon)
        redirect(f"{referer}")


class GetBalanceSensorResource:
    @staticmethod
    def on_get(req, resp):
        referer = req.get_header("Referer")
        referersplit = referer.split("/")[-2:]
        telescope_id = int(referersplit[0])
        result = method_sync("get_device_state", telescope_id)
        if result is not None:
            balance_sensor = {
                "x": result["balance_sensor"]["data"]["x"],
                "y": result["balance_sensor"]["data"]["y"],
            }
            resp.status = falcon.HTTP_200
            resp.content_type = "application/json"
            resp.text = json.dumps(balance_sensor)


class GenSupportBundleResource:
    @staticmethod
    def on_post(req, resp, telescope_id=1):
        zip_io = do_support_bundle(req, telescope_id)
        resp.content_type = "application/zip"
        resp.status = falcon.HTTP_200
        resp.text = zip_io.getvalue()
        zip_io.close()


class ConfigResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        now = datetime.now()
        context = get_context(telescope_id, req)
        render_template(req, resp, "config.html", now=now, config=Config, **context)

    @staticmethod
    def on_post(req, resp, telescope_id=1):
        now = datetime.now()
        context = get_context(telescope_id, req)

        logger.info(f"GOT POST config: {req.media}")
        Config.load_from_form(req)
        Config.save_toml()

        render_template(req, resp, "config.html", now=now, config=Config, **context)


class BlindPolarAlignResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        now = datetime.now()
        context = get_context(telescope_id, req)
        render_template(req, resp, "pa_refine.html", now=now, **context)

    @staticmethod
    def on_post(req, resp, telescope_id=1):
        context = get_context(telescope_id, req)
        referer = req.get_header("Referer")
        referersplit = referer.split("/")[-2:]
        telescope_id = int(referersplit[0])
        PostedForm = req.media
        action = PostedForm["action"]
        if action == "start":
            result = do_action_device("start_plate_solve_loop", telescope_id, {})
            value = result.get("Value", {})
            resp.status = falcon.HTTP_200
            resp.content_type = "application/json"
            resp.text = json.dumps(value)
        elif action == "stop":
            result = do_action_device("stop_plate_solve_loop", telescope_id, {})
            value = result.get("Value", {})
            resp.status = falcon.HTTP_200
            resp.content_type = "application/json"
            resp.text = json.dumps(value)
        elif action == "data":
            result = do_action_device("get_pa_error", telescope_id, {})
            if result is not None:
                value = result.get("Value", {})
                pa_data = {
                    "error_az": value["pa_error_az"],
                    "error_alt": value["pa_error_alt"],
                }
                resp.status = falcon.HTTP_200
                resp.content_type = "application/json"
                resp.text = json.dumps(pa_data)
        elif action == "runpa":
            polar_align = PostedForm.get("polar_align", "False").strip() == "on"
            do_action_device(
                "action_start_up_sequence",
                telescope_id,
                {"3ppa": polar_align},
            )
            render_template(req, resp, "pa_refine.html", **context)


class PlatformRpiResource:
    @staticmethod
    def on_get(req, resp, telescope_id=1):
        now = datetime.now()
        context = get_context(telescope_id, req)
        render_template(
            req,
            resp,
            "platform_rpi.html",
            now=now,
            config=Config,
            display=None,
            **context,
        )

    @staticmethod
    def on_post(req, resp, telescope_id=1):
        form = req.media
        value = form.get("command", "").strip()
        now = datetime.now()
        context = get_context(telescope_id, req)

        def background_run(args):
            time.sleep(2)
            subprocess.run(args, capture_output=False, text=True)

        match value:
            case "restart_alp":
                render_template(
                    req,
                    resp,
                    "platform_rpi.html",
                    now=now,
                    config=Config,
                    display="SSC/Alp service restarting.",
                    **context,
                )
                threading.Thread(
                    target=lambda: background_run(
                        ["sudo", "systemctl", "restart", "seestar.service"]
                    )
                ).start()

            case "restart_indi":
                render_template(
                    req,
                    resp,
                    "platform_rpi.html",
                    now=now,
                    config=Config,
                    display="INDI service restarting.",
                    **context,
                )
                threading.Thread(
                    target=lambda: background_run(
                        ["sudo", "systemctl", "restart", "INDI.service"]
                    )
                ).start()

            case "reboot_rpi":
                render_template(
                    req,
                    resp,
                    "platform_rpi.html",
                    now=now,
                    config=Config,
                    display="System rebooting.",
                    **context,
                )
                threading.Thread(
                    target=lambda: background_run(["sudo", "reboot"])
                ).start()

            case "shutdown_rpi":
                render_template(
                    req,
                    resp,
                    "platform_rpi.html",
                    now=now,
                    config=Config,
                    display="System shutting down.",
                    **context,
                )
                threading.Thread(
                    target=lambda: background_run(["sudo", "shutdown", "-h", "now"])
                ).start()


class LoggingWSGIRequestHandler(WSGIRequestHandler):
    """Subclass of  WSGIRequestHandler allowing us to control WSGI server's logging"""

    def log_message(self, format: str, *args):
        # if args[1] != '200':  # Log this only on non-200 responses
        logger.debug(f"{datetime.now()} {self.client_address[0]} <- {format % args}")


class GetPlanetCoordinates:
    @staticmethod
    def on_get(req, resp):
        # Load planetary ephemeris data
        pDataFile = load("de440s.bsp")
        earth = pDataFile["earth"]

        planetName = req.get_param("planetname")

        # Load the current time
        ts = load.timescale()
        t = ts.now()
        # Choose the planet you want to observe
        planet = pDataFile[planetName]
        # Calculate the astrometric position
        astrometric = earth.at(t).observe(planet)
        # Using 'date' forces JNOW rather than ICRS or J2000
        ra, dec, distance = astrometric.radec("date")
        resp.status = falcon.HTTP_200
        resp.content_type = "application/text"
        resp.text = f"{ra}, {dec}"


def checkFileAge():
    if not os.path.exists("data/CometEls.txt"):
        redownload = True
    else:
        creation_date = datetime.fromtimestamp(os.path.getctime("data/CometEls.txt"))
        today = datetime.today()
        delta = today - creation_date
        if delta.days > 7:
            redownload = True
        else:
            redownload = False
    return redownload


def get_UTC_Time():
    local_time = datetime.now(tzlocal.get_localzone())
    utc_time = local_time - local_time.utcoffset()  # Manually adjust to UTC
    return (
        utc_time.year,
        utc_time.month,
        utc_time.day,
        utc_time.hour,
        utc_time.minute,
        utc_time.second,
    )


def searchComet(name):
    with load.open(mpc.COMET_URL, reload=checkFileAge()) as f:
        comets = mpc.load_comets_dataframe(f)

    # Keep only the most recent orbit for each comet,
    # and index by designation for fast lookup.
    comets = (
        comets.sort_values("reference")
        .groupby("designation", as_index=False)
        .last()
        .set_index("designation", drop=False)
    )

    regex = re.compile(r"{}".format(re.escape(name)), re.IGNORECASE)

    row = comets[comets["designation"].str.contains(regex)]
    match len(row):
        case 0:  # Nothing returned
            return ""
        case 1:  # Single record returned
            ts = load.timescale()
            eph = load("de440s.bsp")
            sun, earth = eph["sun"], eph["earth"]
            comet = sun + mpc.comet_orbit(row.iloc[0], ts, GM_SUN)
            Y, M, D, h, m, s = get_UTC_Time()
            t = ts.utc(Y, M, D, h, m, s)
            ra, dec, distance = earth.at(t).observe(comet).radec()
            data = {
                "ra": str(ra).replace(" ", ""),
                "dec": str(dec)
                .replace("deg", "d")
                .replace("'", "m")
                .replace('"', "s")
                .replace(" ", ""),
                "cometName": str(comet.target),
            }
            return json.dumps(data, indent=4)

        case r if r > 1:  # Multiple records returned
            ts = load.timescale()
            eph = load("de440s.bsp")
            sun, earth = eph["sun"], eph["earth"]
            Y, M, D, h, m, s = get_UTC_Time()
            t = ts.utc(Y, M, D, h, m, s)

            data = []
            for index, r in row.iterrows():
                comet = sun + mpc.comet_orbit(r, ts, GM_SUN)  # Use `r`, the current row
                ra, dec, distance = earth.at(t).observe(comet).radec()

                data.append(
                    {
                        "ra": str(ra).replace(" ", ""),
                        "dec": str(dec)
                        .replace("deg", "d")
                        .replace("'", "m")
                        .replace('"', "s")
                        .replace(" ", ""),
                        "cometName": str(comet.target),
                    }
                )
            return json.dumps(data, indent=4)


def searchMinorPlanet(name):
    if os.path.exists("data/mpn-01.txt"):
        mpcFile = "mpn-01.txt"
    else:
        mpcFile = "http://dss.stellarium.org/MPC/mpn-01.txt"

    with load.open(mpcFile) as f:
        minor_planets = mpc.load_mpcorb_dataframe(f)

    bad_orbits = minor_planets.semimajor_axis_au.isnull()
    minor_planets = minor_planets[~bad_orbits]

    regex = re.compile(r"\b{}\b".format(name), re.IGNORECASE)
    # Example: Filter for a specific asteroid by designation
    row = minor_planets[minor_planets["designation"].str.contains(regex)]

    if row.empty:
        return ""

    ts = load.timescale()
    eph = load("de440s.bsp")
    sun, earth = eph["sun"], eph["earth"]

    object = sun + mpc.mpcorb_orbit(row.iloc[0], ts, GM_SUN)
    Y, M, D, h, m, s = get_UTC_Time()
    t = ts.utc(Y, M, D, h, m, s)
    ra, dec, distance = earth.at(t).observe(object).radec()

    data = {
        "ra": str(ra).replace(" ", ""),
        "dec": str(dec)
        .replace("deg", "d")
        .replace("'", "m")
        .replace('"', "s")
        .replace(" ", ""),
    }
    return json.dumps(data, indent=4)


def searchLocal(object):
    try:
        con = sqlite3.connect("data/alp.dat")
    except:
        return

    cursor = con.cursor()
    search = f"SELECT ra, dec, objectType, commonNames, identifiers FROM objects where identifiers like '%{object}%' or commonNames like '%{object}%' COLLATE NOCASE"
    result = cursor.execute(search)
    sqlReturn = result.fetchall()

    if len(sqlReturn) > 0:
        data = []
        for row in sqlReturn:
            objectType = row[2]
            if (
                objectType == "Planetary Nebula"
                or objectType == "Nebula"
                or objectType == "Star cluster + Nebula"
                or objectType == "HII Ionized region"
                or objectType == "Supernova remnant"
            ):
                lp = "true"
            else:
                lp = "false"

            if row[3]:  # We searched for a name so lets send back the full name
                name = row[3]
            else:
                name = row[4]

            data.append({"ra": row[0], "dec": row[1], "lp": lp, "objectName": name})
        con.close()
        return json.dumps(data, indent=4)
    return ""


class GetCometCoordinates:
    @staticmethod
    def on_get(req, resp):
        cometName = urllib.parse.quote_plus(req.get_param("cometname"))
        rtn = searchComet(cometName)
        if len(rtn) == 0:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Object not found"
            return
        else:
            resp.status = falcon.HTTP_200
            resp.content_type = "application/text"
            resp.text = rtn


class GetMinorPlanetCoordinates:
    @staticmethod
    def on_get(req, resp):
        minorname = urllib.parse.quote_plus(req.get_param("minorname"))
        rtn = searchMinorPlanet(minorname)
        if len(rtn) == 0:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Object not found"
            return
        else:
            resp.status = falcon.HTTP_200
            resp.content_type = "application/text"
            resp.text = rtn


class GetLocalSearch:
    @staticmethod
    def on_get(req, resp):
        searchText = urllib.parse.quote_plus(req.get_param("target"))
        rtn = searchLocal(searchText)
        if len(rtn) == 0:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Object not found"
            return
        else:
            resp.status = falcon.HTTP_200
            resp.content_type = "application/text"
            resp.text = rtn


class GetAAVSOSearch:
    @staticmethod
    def on_get(req: falcon.Request, resp: falcon.Response) -> None:
        objName = urllib.parse.quote_plus(req.get_param("target"))
        aavso_URL = (
            "https://www.aavso.org/vsx/index.php?view=api.object&format=json&ident="
        )
        rtn = requests.get(aavso_URL + objName, timeout=10)
        rtnJson = json.loads(rtn.text)
        if len(rtnJson["VSXObject"]) == 0:
            resp.status = falcon.HTTP_404
            resp.content_type = "application/text"
            resp.text = "Object not found"
            return
        else:
            resp.status = falcon.HTTP_200
            resp.content_type = "application/json"

            ra = decimal_RA_to_Sexagesimal(float(rtnJson["VSXObject"]["RA2000"]))
            dec = decimal_DEC_to_Sexagesimal(
                float(rtnJson["VSXObject"]["Declination2000"])
            )

            resp.text = json.dumps({"ra": ra, "dec": dec})


class FrontMain:
    def __init__(self):
        self.httpd = None

    def start(self):
        """Application startup"""

        app = falcon.App(
            middleware=falcon.CORSMiddleware(allow_origins="*", allow_credentials="*")
        )
        app.add_route("/", HomeResource())
        app.add_route("/command", CommandResource())
        app.add_route("/goto", GotoResource())
        app.add_route("/image", ImageResource())
        app.add_route("/live", LivePage())
        app.add_route("/live/{mode}", LivePage())
        app.add_route("/mosaic", MosaicResource())
        app.add_route("/position", TelescopePositionResource())
        app.add_route("/search", SearchObjectResource())
        app.add_route("/settings", SettingsResource())
        app.add_route("/schedule", ScheduleResource())
        app.add_route("/schedule/auto-focus", ScheduleAutoFocusResource())
        app.add_route("/schedule/clear", ScheduleClearResource())
        app.add_route("/schedule/delete", ScheduleDeleteResource())
        app.add_route("/schedule/download", ScheduleDownloadSchedule())
        app.add_route("/schedule/export", ScheduleExportResource())
        app.add_route("/schedule/exposure", ScheduleExposureResource())
        app.add_route("/schedule/focus", ScheduleFocusResource())
        app.add_route("/schedule/image", ScheduleImageResource())
        app.add_route("/schedule/import", ScheduleImportResource())
        app.add_route("/schedule/mosaic", ScheduleMosaicResource())
        app.add_route("/schedule/refresh", ScheduleRefreshResource())
        app.add_route("/schedule/startup", ScheduleStartupResource())
        app.add_route("/schedule/shutdown", ScheduleShutdownResource())
        app.add_route("/schedule/park", ScheduleParkResource())
        app.add_route("/schedule/lpf", ScheduleLpfResource())
        app.add_route("/schedule/dew-heater", ScheduleDewHeaterResource())
        app.add_route("/schedule/state", ScheduleToggleResource())
        app.add_route("/schedule/wait-until", ScheduleWaitUntilResource())
        app.add_route("/schedule/wait-for", ScheduleWaitForResource())
        app.add_route("/schedule/upload", ScheduleUploadResource())
        app.add_route("/startup", StartupResource())
        app.add_route("/stats", StatsResource())
        app.add_route("/guestmode", GuestModeResource())
        app.add_route("/support", SupportResource())
        app.add_route("/eventstatus", EventStatus())
        app.add_route("/reload", ReloadResource())
        app.add_route("/{telescope_id:int}/", HomeTelescopeResource())
        app.add_route("/{telescope_id:int}/goto", GotoResource())
        app.add_route("/{telescope_id:int}/command", CommandResource())
        app.add_route("/{telescope_id:int}/console", ConsoleResource())
        app.add_route("/{telescope_id:int}/image", ImageResource())
        app.add_route("/{telescope_id:int}/live", LivePage())
        # app.add_route('/{telescope_id:int}/live/status', LiveStatusResource())
        app.add_route("/{telescope_id:int}/live/goto", LiveGotoResource())
        app.add_route("/{telescope_id:int}/live/mode", LiveModeResource())
        # app.add_route('/{telescope_id:int}/live/exposure_mode', LiveExposureModeResource())
        app.add_route("/{telescope_id:int}/live/record", LiveExposureRecordResource())
        # app.add_route('/{telescope_id:int}/live/state', LiveStateResource())
        app.add_route("/{telescope_id:int}/live/exposure", LiveExposureResource())
        app.add_route("/{telescope_id:int}/live/photo", LivePhotoResource())
        app.add_route("/{telescope_id:int}/live/video", LiveVideoResource())
        app.add_route("/{telescope_id:int}/live/zoom", LiveZoomResource())
        app.add_route(
            "/{telescope_id:int}/schedule/exposure", ScheduleExposureResource()
        )
        app.add_route("/{telescope_id:int}/live/focus", LiveFocusResource())
        app.add_route("/{telescope_id:int}/live/gain", LiveGainResource())
        app.add_route("/{telescope_id:int}/live/{mode}", LivePage())
        app.add_route("/{telescope_id:int}/mosaic", MosaicResource())
        app.add_route("/{telescope_id:int}/planning", PlanningResource())
        app.add_route("/{telescope_id:int}/position", TelescopePositionResource())
        app.add_route("/{telescope_id:int}/search", SearchObjectResource())
        app.add_route("/{telescope_id:int}/settings", SettingsResource())
        app.add_route("/{telescope_id:int}/schedule", ScheduleResource())
        app.add_route(
            "/{telescope_id:int}/schedule/auto-focus", ScheduleAutoFocusResource()
        )
        app.add_route("/{telescope_id:int}/schedule/clear", ScheduleClearResource())
        app.add_route("/{telescope_id:int}/schedule/delete", ScheduleDeleteResource())
        app.add_route(
            "/{telescope_id:int}/schedule/download", ScheduleDownloadSchedule()
        )
        app.add_route("/{telescope_id:int}/schedule/export", ScheduleExportResource())
        app.add_route("/{telescope_id:int}/schedule/focus", ScheduleFocusResource())
        app.add_route("/{telescope_id:int}/schedule/image", ScheduleImageResource())
        app.add_route("/{telescope_id:int}/schedule/import", ScheduleImportResource())
        app.add_route("/{telescope_id:int}/schedule/mosaic", ScheduleMosaicResource())
        app.add_route("/{telescope_id:int}/schedule/startup", ScheduleStartupResource())
        app.add_route(
            "/{telescope_id:int}/schedule/shutdown", ScheduleShutdownResource()
        )
        app.add_route("/{telescope_id:int}/schedule/park", ScheduleParkResource())
        app.add_route("/{telescope_id:int}/schedule/lpf", ScheduleLpfResource())
        app.add_route(
            "/{telescope_id:int}/schedule/dew-heater", ScheduleDewHeaterResource()
        )
        app.add_route("/{telescope_id:int}/schedule/refresh", ScheduleRefreshResource())
        app.add_route(
            "/{telescope_id:int}/schedule/restart_schedule", ScheduleReStartResource()
        )
        app.add_route("/{telescope_id:int}/schedule/state", ScheduleToggleResource())
        app.add_route(
            "/{telescope_id:int}/schedule/wait-until", ScheduleWaitUntilResource()
        )
        app.add_route(
            "/{telescope_id:int}/schedule/wait-for", ScheduleWaitForResource()
        )
        app.add_route("/{telescope_id:int}/schedule/upload", ScheduleUploadResource())
        app.add_route("/{telescope_id:int}/startup", StartupResource())
        app.add_route("/{telescope_id:int}/stats", StatsResource())
        app.add_route("/{telescope_id:int}/guestmode", GuestModeResource())
        app.add_route("/{telescope_id:int}/support", SupportResource())
        app.add_route("/{telescope_id:int}/system", SystemResource())
        app.add_route("/{telescope_id:int}/eventstatus", EventStatus())
        app.add_route(
            "/{telescope_id:int}/gensupportbundle", GenSupportBundleResource()
        )
        app.add_route("/{telescope_id:int}/config", ConfigResource())
        app.add_route("/{telescope_id:int}/pa_refine", BlindPolarAlignResource())
        app.add_route("/{telescope_id:int}/platform-rpi", PlatformRpiResource())
        app.add_static_route("/public", f"{os.path.dirname(__file__)}/public")
        app.add_route("/simbad", SimbadResource())
        app.add_route("/stellarium", StellariumResource())
        app.add_route("/toggleuitheme", ToggleUIThemeResource())
        app.add_route("/toggleplanningcard", TogglePlanningCardResource())
        app.add_route("/collapseplanningcard", CollapsePlanningCardResource())
        app.add_route("/updatetwilighttimes", UpdateTwilightTimesResource())
        app.add_route("/getbalancesensor", GetBalanceSensorResource())
        app.add_route("/gensupportbundle", GenSupportBundleResource())
        app.add_route("/getplanetcoordinates", GetPlanetCoordinates())
        app.add_route("/getcometcoordinates", GetCometCoordinates())
        app.add_route("/localsearch", GetLocalSearch())
        app.add_route("/getminorplanetcoordinates", GetMinorPlanetCoordinates())
        app.add_route("/getaavsocoordinates", GetAAVSOSearch())
        app.add_route("/config", ConfigResource())
        app.add_route("/pa_refine", BlindPolarAlignResource())

        try:
            self.httpd = make_server(
                Config.ip_address,
                Config.uiport,
                app,
                handler_class=LoggingWSGIRequestHandler,
            )
            logger.info(
                f"==STARTUP== Serving on {Config.ip_address}:{Config.uiport}. Time stamps are UTC."
            )

            # Print listening IP:Port to the console
            logger.info(f"SSC Started: http://{get_listening_ip()}:{Config.uiport}")

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

    def reload(self):
        global logger
        logger = get_logger()
        Config.load_toml()
        logger.debug("FrontMain got reload")


class style:
    YELLOW = "\033[33m"
    RESET = "\033[0m"


if __name__ == "__main__":
    print(style.YELLOW + "WARN")
    print(style.YELLOW + "WARN" + style.RESET + ": Deprecated app launch detected.")
    print(
        style.YELLOW
        + "WARN"
        + style.RESET
        + ": We recommend launching from the top level root_app.py, instead of ./front/app.py"
    )
    print(style.YELLOW + "WARN" + style.RESET)
    app = FrontMain()
    app.start()
