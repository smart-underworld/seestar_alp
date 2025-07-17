from flask import Flask, jsonify, request
import json
import os

STEP_COUNTER_PATH = 'step_counter.json'

def load_step_counter():
    if os.path.exists(STEP_COUNTER_PATH):
        with open(STEP_COUNTER_PATH, 'r') as f:
            return json.load(f)
    else:
        return {"steps_taken": 0, "persist_step_count": False}

def save_step_counter(data):
    with open(STEP_COUNTER_PATH, 'w') as f:
        json.dump(data, f)

@app.route('/get_step_count', methods=['GET'])
def get_step_count():
    data = load_step_counter()
    return jsonify({"steps_taken": data["steps_taken"]})

@app.route('/reset_step_count', methods=['POST'])
def reset_step_count():
    data = load_step_counter()
    data["steps_taken"] = 0
    save_step_counter(data)
    return jsonify({"status": "Step count reset"})

@app.route('/set_step_tracking_mode', methods=['POST'])
def set_step_tracking_mode():
    data = load_step_counter()
    req = request.json
    persist = req.get("persist_step_count", False)
    data["persist_step_count"] = persist
    save_step_counter(data)
    return jsonify({"status": "Tracking mode updated", "persist_step_count": persist})
