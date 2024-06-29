from datetime import datetime

import falcon
from falcon import HTTPTemporaryRedirect, HTTPFound
from jinja2 import Template, Environment, FileSystemLoader
from wsgiref.simple_server import WSGIRequestHandler, make_server
import requests
import json
import re

dev_num = 1
base_url = "http://localhost:5555"


def flash(resp, message):
    resp.set_cookie('flash_cookie', message, path='/')


def get_flash_cookie(req, resp):
    cookie = req.get_cookie_values('flash_cookie')
    if cookie:
        resp.unset_cookie('flash_cookie', path='/')
        return cookie
    return []


def do_action(action, parameters):
    url = f"{base_url}/api/v1/telescope/{dev_num}/action"
    payload = {
        "Action": action,
        "Parameters": json.dumps(parameters),
        "ClientID": 1,
        "ClientTransactionID": 999
    }
    r = requests.put(url, json=payload)
    return r.json()


def do_schedule_action(action, parameters):
    if parameters:
        return do_action("add_schedule_item", {
            "action": action,
            "params": parameters
        })
    else:
        return do_action("add_schedule_item", {
            "action": action
        })


def check_response(resp, response):
    v = response["Value"]
    if isinstance(v, str):
        flash(resp, v)
    elif response["ErrorMessage"] != '':
        flash(resp, response["ErrorMessage"])
        # flash("Schedule item added successfully", "success")
    else:
        flash(resp, "Item scheduled successfully")


def method_sync(method):
    out = do_action("method_sync", {"method": method})
    return out["Value"]["result"]


def get_device_state():
    result = method_sync("get_device_state")
    device = result["device"]
    settings = result["setting"]
    pi_status = result["pi_status"]
    stats = {
        "Firmware Version": device["firmware_ver_string"],
        "Focal Position": settings["focal_pos"],
        "Auto Power Off": settings["auto_power_off"],
        "Heater?": settings["heater_enable"],
        "Free Storage (MB)": result["storage"]["storage_volume"][0]["freeMB"],
        "Balance Sensor (angle)": result["balance_sensor"]["data"]["angle"],
        "Compass Sensor (direction)": result["compass_sensor"]["data"]["direction"],
        "Temperature Sensor": pi_status["temp"],
        "Charge Status": pi_status["charger_status"],
        "Battery %": pi_status["battery_capacity"],
        "Battery Temp": pi_status["battery_temp"],
    }
    return stats

def check_ra_value(raString):
    valid = [
        r"^\d+h\s*\d+m\s*([0-9.]+s)?$",
        r"^\d+(\.\d+)?$",
        r"^\d+\s+\d+\s+[0-9.]+$"
        r"^-1$",
    ]
    return any(re.search(pattern, raString) for pattern in valid)
    
def check_dec_value(decString):
    
    valid = [
        r"^[+-]?\d+d\s*\d+m\s*([0-9.]+s)?$",
        r"^[+-]?\d+(\.\d+)?$",
        r"^[+-]?\d+\s+\d+\s+[0-9.]+$"
    ]
    return any(re.search(pattern, decString) for pattern in valid)
    
def do_create_mosaic(req, resp, schedule):
    form = req.media
    targetName = form["targetName"]
    ra, raPanels = form["ra"], form["raPanels"]
    dec, decPanels = form["dec"], form["decPanels"]
    panelOverlap = form["panelOverlap"]
    useJ2000 = form.get("useJ2000") == "on"
    sessionTime = form["sessionTime"]
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
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus
    }
    
    if not check_ra_value(ra):
        print("Bad RA")
        flash(resp, "Invalid RA value")
        errors["ra"] = ra
        
    if not check_dec_value(dec):
        print("Bad DEC")
        flash(resp, "Invalid DEC Value")
        errors["dec"] = dec
        
    if errors:
        print("ERROR detected", errors)
        return values, errors

    if schedule:
        response = do_action("add_schedule_item", {
            "action": "start_mosaic",
            "params": values
        })
        print("POST scheduled request", values, response)
        check_response(resp, response)
    else:
        response = do_action("start_mosaic", values)
        print("POST immediate request", values, response)

    return values, errors


def do_create_image(req, resp, schedule):
    form = req.media
    targetName = form["targetName"]
    ra, raPanels = form["ra"], 1
    dec, decPanels = form["dec"], 1
    panelOverlap = 100
    useJ2000 = form.get("useJ2000") == "on"
    sessionTime = form["sessionTime"]
    useLpfilter = form.get("useLpFilter") == "on"
    useAutoFocus = form.get("useAutoFocus") == "on"
    gain = form["gain"]
    values = {
        "target_name": targetName,
        "is_j2000": useJ2000,
        "ra": float(ra),
        "dec": float(dec),
        "is_use_lp_filter": useLpfilter,
        "session_time_sec": int(sessionTime),
        "ra_num": int(raPanels),
        "dec_num": int(decPanels),
        "panel_overlap_percent": int(panelOverlap),
        "gain": int(gain),
        "is_use_autofocus": useAutoFocus
    }

    # print("values:", values)
    if schedule:
        response = do_action("add_schedule_item", {
            "action": "start_mosaic",
            "params": values
        })
        print("POST scheduled request", values, response)
        check_response(resp, response)
    else:
        response = do_action("start_mosaic", values)
        print("POST immediate request", values, response)

    return values


def redirect(location):
    raise HTTPFound(location)
    # raise HTTPTemporaryRedirect(location)


def render_template(req, resp, template_name, **context):
    template = Environment(loader=FileSystemLoader('./templates')).get_template(template_name)

    resp.status = falcon.HTTP_200
    resp.content_type = 'text/html'
    resp.text = template.render(flashed_messages=get_flash_cookie(req, resp), **context)


class HomeResource:
    @staticmethod
    def on_get(req, resp):
        stats = get_device_state()
        now = datetime.now()
        render_template(req, resp, 'index.html', stats=stats, now=now)


class ImageResource:
    def on_get(self, req, resp):
        values = {}
        self.image(req, resp, values)

    def on_post(self, req, resp):
        values = do_create_image(req, resp, True)
        self.image(req, resp, {})

    @staticmethod
    def image(req, resp, values):
        current = do_action("get_schedule", {})
        state = current["Value"]["state"]
        schedule = current["Value"]["list"]
        # remove values=values to stop remembering values
        render_template(req, resp, 'image.html', state=state, schedule=schedule, values=values, action="/image")


class MosaicResource:
    def on_get(self, req, resp):
        self.mosaic(req, resp, {}, {})

    def on_post(self, req, resp):
        values, errors = do_create_mosaic(req, resp, False)
        self.mosaic(req, resp, values, errors)

    @staticmethod
    def mosaic(req, resp, values, errors):
        current = do_action("get_schedule", {})
        state = current["Value"]["state"]
        schedule = current["Value"]["list"]
        # remove values=values to stop remembering values
        render_template(req, resp, 'mosaic.html', state=state, schedule=schedule, values=values, errors=errors, action="/mosaic")


class ScheduleResource:
    def on_get(self, req, resp):
        self.render_schedule(req, resp)

    def on_post(self, req, resp):
        self.render_schedule(req, resp)

    @staticmethod
    def render_schedule(req, resp):
        current = do_action("get_schedule", {})
        state = current["Value"]["state"]
        schedule = current["Value"]["list"]
        render_template(req, resp, 'schedule.html', schedule=schedule, state=state, errors={}, values={})


class ScheduleWaitUntilResource:
    @staticmethod
    def on_post(req, resp):
        waitUntil = req.media["waitUntil"]
        response = do_schedule_action("wait_until", {"local_time": waitUntil})
        # print("POST scheduled request", response)
        check_response(resp, response)
        redirect("/schedule")


class ScheduleWaitForResource:
    @staticmethod
    def on_post(req, resp):
        waitFor = req.media["waitFor"]
        response = do_schedule_action("wait_for", {"timer_sec": int(waitFor)})
        # print("POST scheduled request", response)
        check_response(resp, response)
        redirect("/schedule")


class ScheduleAutofocusResource:
    def on_post(self, req, resp):
        pass


class ScheduleImageResource:
    @staticmethod
    def on_post(req, resp):
        values = do_create_image(req, resp, True)
        redirect("/schedule")


class ScheduleMosaicResource:
    @staticmethod
    def on_post(req, resp):
        values = do_create_mosaic(req, resp, True)
        redirect("/schedule")


class ScheduleShutdownResource:
    @staticmethod
    def on_post(req, resp):
        response = do_schedule_action("shutdown", "")
        check_response(resp, response)
        redirect("/schedule")


class ScheduleToggleResource:
    @staticmethod
    def on_post(req, resp):
        current = do_action("get_schedule", {})
        state = current["Value"]["state"]
        if state == "Stopped":
            do_action("start_scheduler", {})
            
        else:
            do_action("stop_scheduler", {})
            flash(resp, "Stopping scheduler")
        redirect("/schedule")


class ScheduleClearResource:
    @staticmethod
    def on_post(req, resp):
        current = do_action("get_schedule", {})
        state = current["Value"]["state"]
        if state == "Running":
            do_action("stop_scheduler", {})
            flash(resp, "Stopping scheduler")

        do_action("create_schedule", {})
        flash(resp, "Created New Schedule")
        redirect("/schedule")


class LivePage:
    @staticmethod
    def on_get(req, resp):
        status = method_sync('get_view_state')
        result = status["View"]["state"]
        mode = status["View"]["mode"]
        state = method_sync("get_device_state")
        ip = state["station"]["ip"]
        render_template(req, resp, 'live.html', mode=f"{result} {mode}.  stream=rtps://{ip}:4554/stream")


class SettingsResource:
    @staticmethod
    def on_get(req, resp):
        render_template(req, resp, 'settings.html')


class StatsResource:
    @staticmethod
    def on_get(req, resp):
        stats = get_device_state()
        now = datetime.now()
        render_template(req, resp, 'stats.html', stats=stats, now=now)


class LoggingWSGIRequestHandler(WSGIRequestHandler):
    """Subclass of  WSGIRequestHandler allowing us to control WSGI server's logging"""

    def log_message(self, format: str, *args):
        # if args[1] != '200':  # Log this only on non-200 responses
        print(f'{datetime.now()} {self.client_address[0]} <- {format % args}')


def main():
    app = falcon.App()
    app.add_route('/', HomeResource())
    app.add_route('/image', ImageResource())
    app.add_route('/mosaic', MosaicResource())
    app.add_route('/settings', SettingsResource())
    app.add_route('/schedule', ScheduleResource())
    app.add_route('/schedule/clear', ScheduleClearResource())
    app.add_route('/schedule/image', ScheduleImageResource())
    app.add_route('/schedule/mosaic', ScheduleMosaicResource())
    app.add_route('/schedule/shutdown', ScheduleShutdownResource())
    app.add_route('/schedule/toggle', ScheduleToggleResource())
    app.add_route('/schedule/wait-until', ScheduleWaitUntilResource())
    app.add_route('/schedule/wait-for', ScheduleWaitForResource())
    app.add_route('/stats', StatsResource())
    try:
        # with make_server(Config.ip_address, Config.port, falc_app, handler_class=LoggingWSGIRequestHandler) as httpd:
        with make_server("127.0.0.1", 5432, app, handler_class=LoggingWSGIRequestHandler) as httpd:
            # logger.info(f'==STARTUP== Serving on {Config.ip_address}:{Config.port}. Time stamps are UTC.')
            # Serve until process is killed
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("Keyboard interupt. Server shutting down.")
        # for dev in Config.seestars:
        #     telescope.end_seestar_device(dev['device_num'])
        httpd.server_close()


if __name__ == '__main__':
    main()
