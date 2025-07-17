import json
import os
import time

STEP_COUNTER_PATH = 'step_counter.json'

def load_step_counter():
    if os.path.exists(STEP_COUNTER_PATH):
        with open(STEP_COUNTER_PATH, 'r') as f:
            return json.load(f)
    return {"steps_taken": 0, "persist_step_count": False}

def save_step_counter(data):
    with open(STEP_COUNTER_PATH, 'w') as f:
        json.dump(data, f)

class TelescopeController:
    def __init__(self):
        self.load_config()
        counter = load_step_counter()
        if not counter.get("persist_step_count", False):
            counter["steps_taken"] = 0
            save_step_counter(counter)

    def move_with_mode(self, direction):
        config = self.load_movement_config()
        mode = config.get("mode", "default")

        if mode == "step":
            step_count = config.get("step_count", 5)
            for _ in range(step_count):
                self.move(direction)
                time.sleep(0.1)
                self.stop()
                time.sleep(0.1)
                self.increment_step_counter()
        elif mode == "time":
            duration = config.get("duration", 0.5)
            self.move(direction)
            time.sleep(duration)
            self.stop()
        else:
            self.move(direction)

    def increment_step_counter(self):
        counter = load_step_counter()
        counter["steps_taken"] += 1
        save_step_counter(counter)

    def load_movement_config(self):
        with open("movement_config.json", "r") as f:
            return json.load(f)

    def move(self, direction):
        pass

    def stop(self):
        pass
