import threading
import uuid
from time import sleep
from seestar_util import Util

class Seestar_Federation:
    def __new__(cls, *args, **kwargs):
        # print("Create a new instance of Seestar.")
        return super().__new__(cls)

    # <ip_address> <port> <device name> <device num>
    def __init__(self, logger, seestar_devices):
        logger.info( "Initialize the new instance of Seestar federation")

        self.logger = logger
        self.seestar_devices = seestar_devices
        self.schedule = {}
        self.schedule['list'] = []

    def send_message_param_sync(self, data):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].send_message_param_sync(data)
                
    def stop_goto_target(self):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].stop_goto_target()

    def goto_target(self, params):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].stop_goto_target(params)


    # {"method":"scope_goto","params":[1.2345,75.0]}
    def slew_to_ra_dec(self, params):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].slew_to_ra_dec[params]

    def set_below_horizon_dec_offset(self, offset):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].set_below_horizon_dec_offset(offset)

    def stop_slew(self):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].stop_slew()

    # {"method":"scope_speed_move","params":{"speed":4000,"angle":270,"dur_sec":10}}
    def move_scope(self, in_angle, in_speed, in_dur=3):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].move_scope(in_angle, in_speed, in_dur)

    def try_auto_focus(self, try_count):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                af_thread = threading.Thread(target=lambda: self.seestar_devices[key].try_auto_focus(try_count))
                af_thread.start()

    def stop_stack(self):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].stop_stack()

    def play_sound(self, in_sound_id: int):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].play_sound(in_sound_id)

    def start_stack(self, params={"gain": 80, "restart": True}):
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].start_stack(params)


    def action_set_dew_heater(self, params):
         for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].action_set_dew_heater(params)
       
    def action_start_up_sequence(self, params):
         for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].action_start_up_sequence(params)

    def get_schedule(self):
        self.schedule['comment'] = 'Test comment'
        num_connected = 0
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                num_connected = num_connected + 1
                if cur_device.get_shcedule()['state'] == "Running":
                    self.schedule['state'] = "Running"
                    return self.schedule
        self.schedule['num_devices_connected'] = num_connected       
        if num_connected == 0:
            self.schedule['comment'] = 'No connected devices.'
            return self.schedule
        
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                if cur_device.get_shcedule()['state'] == "Stopping":
                    self.schedule['state'] = "Stopping"
                    return self.schedule
        self.schedule['state'] = "Stopped"

        return self.schedule

    def create_schedule(self):
        cur_schedule = self.get_schedule()
        if cur_schedule == "Running":
            return "scheduler is still active"
        self.schedule = {}
        self.schedule['state'] = "Stopped"
        self.schedule['list'] = []
        return self.schedule

    def add_schedule_item(self, params):
        cur_schedule = self.get_schedule()
        if cur_schedule == "Running":
            return "scheduler is still active"
        if params['action'] == 'start_mosaic':
            mosaic_params = params['params']
            if isinstance(mosaic_params['ra'], str):
                # try to trim the seconds to 1 decimal
                mosaic_params['ra'] = Util.trim_seconds(mosaic_params['ra'])
                mosaic_params['dec'] = Util.trim_seconds(mosaic_params['dec'])
            elif isinstance(mosaic_params['ra'], float):
                if mosaic_params['ra'] < 0:
                    mosaic_params['ra'] = self.ra
                    mosaic_params['dec'] = self.dec
                    mosaic_params['is_j2000'] = False
                mosaic_params['ra'] = round(mosaic_params['ra'], 4)
                mosaic_params['dec'] = round(mosaic_params['dec'], 4)                
                
        params['id'] = str(uuid.uuid4())
        self.schedule['list'].append(params)
        return self.schedule

    # shortcut to start a new scheduler with only a mosaic request
    def start_mosaic(self, params):
        cur_schedule = self.get_schedule()
        if cur_schedule["num_devices_connected"] < 1:
            return "Failed: No connected devices found to perform operation"
        elif cur_schedule['state'] != "Stopped":
            return "Failed: At least one device is still running a schedule."

        cur_params = params['params']
        if cur_schedule["num_devices_connected"]  == 1 or 'array_mode' not in cur_params or cur_params['array_mode'] != 'split' or (cur_params['ra_num']==1 and cur_params['dec_num']==1):
            for key in self.seestar_devices:
                cur_device = self.seestar_devices[key]
                if cur_device.is_connected:
                    return cur_device.start_mosaic(params)
            self.logger.warn("Should not reach here when trying to start a mosaic.")
            return "Should not reach here when trying to start a mosaic."
        
        if cur_params['array_mode'] != 'split':
            num_devices = 0
            for key in self.seestar_devices:
                cur_device = self.seestar_devices[key]
                if cur_device.is_connected:
                    num_devices = num_devices + 1
                    cur_schedule = cur_device.start_mosaic(params)
            self.logger.info("started {num_devices} devices for cloned mosaics.")
            return cur_schedule

        # remaining case of a split mosaic across multiple devices
        num_devices = 0
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                num_devices += num_devices
        section_array = self.get_section_array_for_mosaic(num_devices, cur_params['ra_num'], cur_params['dec_num'])
        self.schedule = {}
        self.schedule['state'] = "Running"
        self.schedule['list'] = []
        schedule_item = {}
        schedule_item['action'] = "start_mosaic"
        schedule_item['params'] = cur_params
        self.add_schedule_item(schedule_item)

        cur_index_num = 0
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                cur_params['selected_panels'] = section_array[cur_index_num]
                cur_index_num += 1
                cur_device.start_mosaic(cur_params)
        self.logger.info("started {num_devices} devices for split mosaics.")
        return self.schedule

    def start_scheduler(self):
        if self.scheduler_state != "Stopped":
            return "An existing scheduler is active. Returned with no action."
        self.scheduler_thread = threading.Thread(target=lambda: self.scheduler_thread_fn(), daemon=True)
        self.scheduler_thread.name = f"SchedulerThread.{self.device_name}"
        self.scheduler_thread.start()
        return "Scheduler started"

    def stop_scheduler(self):
         for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                self.seestar_devices[key].stop_scheduler()


