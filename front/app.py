from flask import Flask, render_template, request, flash, redirect
import requests
import json
import time

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'  # This isn't secure!

dev_num = 1
base_url = "http://localhost:5555"


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
    return do_action("add_schedule_item", {
        "action": action,
        "params": parameters
    })


def check_response(response):
    v = response["Value"]
    if isinstance(v, str):
        flash(v)
    elif response["ErrorMessage"] != '':
        flash(response["ErrorMessage"])
        # flash("Schedule item added successfully", "success")
    else:
        flash("Item scheduled successfully")

def method_sync(method):
    out = do_action("method_sync", {"method": method})
    return out["Value"]["result"]


def do_create_mosaic(form, schedule):
    targetName = request.form["targetName"]
    ra, raPanels = request.form["ra"], request.form["raPanels"]
    dec, decPanels = request.form["dec"], request.form["decPanels"]
    panelOverlap = request.form["panelOverlap"]
    useJ2000 = request.form.get("useJ2000") == "on"
    sessionTime = request.form["sessionTime"]
    useLpfilter = request.form.get("useLpFilter") == "on"
    gain = request.form["gain"]
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
        "gain": int(gain)
    }

    # print("values:", values)
    if schedule:
        response = do_action("add_schedule_item", {
            "action": "start_mosaic",
            "params": values
        })
        print("POST scheduled request", values, response)
        check_response(response)
    else:
        response = do_action("start_mosaic", values)
        print("POST immediate request", values, response)

    return values


@app.route('/')
def home_page():
    return render_template('index.html')


@app.route('/live')
def live_page():
    status = method_sync('get_view_state')
    result = status["View"]["state"]
    mode = status["View"]["mode"]
    state = method_sync("get_device_state")
    ip = state["station"]["ip"]
    return render_template('live.html', mode=f"{result} {mode}.  stream=rtps://{ip}:4554/stream")


@app.route('/mosaic', methods=["POST", "GET"])
def mosaic_page():
    values = {}
    if request.method == 'POST':
        values = do_create_mosaic(request.form, True)
    current = do_action("get_schedule", {})
    state = current["Value"]["state"]
    schedule = current["Value"]["list"]
    # remove values=values to stop remembering values
    return render_template('mosaic.html', state=state, schedule=schedule, values=values, action="/mosaic")


@app.route('/schedule', methods=["POST", "GET"])
def schedule_page():
    current = do_action("get_schedule", {})
    state = current["Value"]["state"]
    schedule = current["Value"]["list"]
    return render_template('schedule.html', schedule=schedule, state=state, values={})


@app.route('/schedule/wait-until', methods=["POST"])
def schedule_wait_until():
    waitUntil = request.form["waitUntil"]
    response = do_schedule_action("wait_until", {"local_time": waitUntil})
    # print("POST scheduled request", response)
    check_response(response)
    return redirect("/schedule")


@app.route('/schedule/wait-for', methods=["POST"])
def schedule_wait_for():
    waitFor = request.form["waitFor"]
    response = do_schedule_action("wait_for", {"timer_sec": int(waitFor)})
    # print("POST scheduled request", response)
    check_response(response)
    return redirect("/schedule")


@app.route('/schedule/autofocus', methods=["POST"])
def schedule_autofocus():
    pass

@app.route('/schedule/mosaic', methods=["POST"])
def schedule_mosaic():
    values = do_create_mosaic(request.form, True)
    return redirect("/schedule")


@app.route('/schedule/shutdown', methods=["POST"])
def schedule_shutdown():
    pass

@app.route("/schedule/toggle", methods=["POST"])
def schedule_toggle():
    current = do_action("get_schedule", {})
    state = current["Value"]["state"]
    if state == "Stopped":
        do_action("start_scheduler", {})
        flash("Starting scheduler")
    else:
        do_action("stop_scheduler", {})
        flash("Stopping scheduler")
    return redirect(f"/schedule?{ time.time() }")


# @app.route('/settings')
# def settings_page():
#     return render_template('settings.html')

@app.route('/stats')
def stats_page():
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
    return render_template('stats.html', stats=stats)


if __name__ == "__main__":
    app.run(debug=True, port=5432)
