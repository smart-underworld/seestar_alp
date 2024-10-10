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
        self.is_connected = True
        self.logger = logger
        self.seestar_devices = seestar_devices
        self.schedule = {}
        self.schedule['list'] = []
        self.schedule['state'] = "stopped"
        self.schedule['schedule_id'] = str(uuid.uuid4())

    def disconnect(self):
        return

    def reconnect(self):
        return True

    def get_event_state(self, params=None):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].get_event_state(params)
        return result

    def send_message_param_sync(self, data):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].send_message_param_sync(data)
        return result
                
    def goto_target(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].goto_target(params)
        return result
    
    def stop_goto_target(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[key].stop_goto_target()
        return result
    
    def is_goto(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[key].is_goto()
        return result
    
    def is_goto_completed_ok(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = result[key] = self.seestar_devices[key].is_goto_completed_ok()
        return result
    
    def set_below_horizon_dec_offset(self, offset):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].set_below_horizon_dec_offset(offset)
        return result
    
    def stop_slew(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].stop_slew()
        return result
    
    # {"method":"scope_speed_move","params":{"speed":4000,"angle":270,"dur_sec":10}}
    def move_scope(self, in_angle, in_speed, in_dur=3):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].move_scope(in_angle, in_speed, in_dur)
        return result
    
    def try_auto_focus(self, try_count):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                af_thread = threading.Thread(target=lambda: self.seestar_devices[key].try_auto_focus(try_count))
                af_thread.start()
                result[key] = "Auto focus started"
        return result
    
    def stop_stack(self):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].stop_stack()
        return result
    
    def play_sound(self, in_sound_id: int):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].play_sound(in_sound_id)
        return result
    
    def start_stack(self, params={"gain": 80, "restart": True}):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].start_stack(params)
        return result

    def action_set_dew_heater(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].action_set_dew_heater(params)
        return result
           
    def action_start_up_sequence(self, params):
        result = {}
        for key in self.seestar_devices:
            if self.seestar_devices[key].is_connected:
                result[key] = self.seestar_devices[key].action_start_up_sequence(params)
        return result
    
    def get_schedule(self, params):
        if 'schedule_id' in params:
            if self.schedule['schedule_id'] == params['schedule_id']:
                result = self.schedule.copy()
            else:
                result = {}
        else:
            result = self.schedule.copy()
        result['device'] = {}
        availiable_device_list = []

        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                device_schedule = cur_device.get_schedule(params)
                if 'state' not in device_schedule:
                    continue
                if device_schedule['state'] == "stopped":
                    availiable_device_list.append(key)
                result['device'][key] = device_schedule
        result['available_device_list'] = availiable_device_list
        result['comment'] = 'Test comment'
        return result

    def create_schedule(self, params):
        self.schedule = {}
        self.schedule['list'] = []
        self.schedule['state'] = "stopped"
        self.schedule['schedule_id'] = str(uuid.uuid4())
        return self.schedule

    def add_schedule_item(self, params):
        if params['action'] == 'start_mosaic':
            mosaic_params = params['params']
            if isinstance(mosaic_params['ra'], str):
                # try to trim the seconds to 1 decimal
                mosaic_params['ra'] = Util.trim_seconds(mosaic_params['ra'])
                mosaic_params['dec'] = Util.trim_seconds(mosaic_params['dec'])
            elif isinstance(mosaic_params['ra'], float):
                if mosaic_params['ra'] < 0:
                    self.logger.warn("Failed. Must specify an proper coordinate for a federated schedule.")
                    raise Exception( "Failed. Must specify an proper coordinate for a federated schedule.")
                mosaic_params['ra'] = round(mosaic_params['ra'], 4)
                mosaic_params['dec'] = round(mosaic_params['dec'], 4)                
                
        params['id'] = str(uuid.uuid4())
        self.schedule['list'].append(params)
        return self.schedule

    # cur_params['selected_panels'] cur_params['ra_num'], cur_params['dec_num']
    # split selected panels into multiple sections. Given num_devices > 1 and num ra and dec is > 1
    def get_section_array_for_mosaic(self, device_id_list, params):
        num_devices = len(device_id_list)
        if num_devices == 0:
            raise Exception("there is no active device connected!")
        
        if 'selected_panels' in params and params['selected_panels'] != "":
            panel_array = params['selected_panels'].split(';')
            num_panels = len(panel_array)
        else:
            num_panels = params['dec_num'] * params['ra_num']
            panel_array = ['']*num_panels
            index = 0
            for n_dec in range(params['dec_num']):
                for n_ra in range(params['ra_num']):
                    panel_array[index] = f'{n_ra+1}{n_dec+1}'
                    index += 1
        start_index = 0

        num_panels_per_device = int(num_panels / num_devices)
        result = {}
        for i in device_id_list:
            end_index = start_index + num_panels_per_device
            selected_panels = ';'.join(panel_array[start_index:end_index])
            if len(selected_panels) > 0:
                result[i] = selected_panels
            start_index = end_index
        # take care of the reminder of the selected panels
        for i in device_id_list:
            if start_index >= num_panels:
                break
            result[i] = f'{result[i]};{panel_array[start_index]}'
            start_index += 1

        return result

    # shortcut to start a new scheduler with only a mosaic request
    def start_mosaic(self, cur_params):
        cur_schedule = self.get_schedule(cur_params)
        num_devices = len(cur_schedule["available_device_list"])
        if num_devices < 1:
            return {"error":"Failed: No available devices found to execute a schedule."}

        self.schedule = {}
        self.schedule['list'] = []
        self.schedule['state'] = "stopped"
        self.schedule['schedule_id'] = str(uuid.uuid4())
        schedule_item = {}
        schedule_item['action'] = "start_mosaic"
        schedule_item['params'] = cur_params
        self.add_schedule_item(schedule_item)
        return self.start_scheduler(cur_params)

    def start_scheduler(self, params):
        if len(self.schedule['list']) == 0:
            return {"error": "Failed: The schedule is empty."}
        
        root_schedule = self.get_schedule(params)
        available_devices = root_schedule["available_device_list"]

        if 'max_devices' in params:
            available_devices = available_devices[:params['max_devices']]

        num_devices = len(available_devices)
        if num_devices < 1:
            return{"error": "Failed: No available devices found to execute a schedule."}

        
        for key in available_devices:
            cur_device = self.seestar_devices[key]
            cur_device.create_schedule(params)


        for schedule_item in self.schedule['list']:
            if schedule_item['action'] == "start_mosaic":
                cur_params = schedule_item['params']
                if num_devices  == 1 or 'array_mode' not in cur_params or cur_params['array_mode'] != 'split' or (cur_params['ra_num']==1 and cur_params['dec_num']==1):
                    for key in available_devices:
                        cur_device = self.seestar_devices[key]
                        new_item = {}
                        new_item['action'] = "start_mosaic"
                        cur_params = schedule_item['params'].copy()
                        new_item['params'] = cur_params
                        new_item['id'] = str(uuid.uuid4())
                        cur_device.add_schedule_item(new_item)
                else:
                    section_dict = self.get_section_array_for_mosaic(available_devices, cur_params)
                    for key in section_dict:
                        cur_device = self.seestar_devices[key]
                        new_item = {}
                        new_item['action'] = "start_mosaic"
                        cur_params = schedule_item['params'].copy()
                        cur_params['selected_panels'] = section_dict[key]
                        new_item['params'] = cur_params
                        new_item['id'] = str(uuid.uuid4())
                        cur_device.add_schedule_item(new_item)

            else:
                for key in available_devices:
                    cur_device = self.seestar_devices[key]
                    new_item = {}
                    new_item['action'] = schedule_item['action']
                    cur_params = schedule_item['params'].copy()
                    new_item['params'] = cur_params
                    new_item['id'] = str(uuid.uuid4())
                    cur_device.add_schedule_item(new_item)
        
        for key in available_devices:
            cur_device = self.seestar_devices[key]
            cur_device.start_scheduler(params)

        return self.get_schedule(params)

    def stop_scheduler(self, params):
        result = {}
        for key in self.seestar_devices:
            cur_device = self.seestar_devices[key]
            if cur_device.is_connected:
                result[key] = cur_device.stop_scheduler(params)
        return result
    
    


