#
# A collection of actions to perform
#

def goto_sun(telescope):
    pass

# method: get_device_state, params: { keys: [ balance_sensor, compass_sensor ] }

#
# method: iscope_start_view, params: { mode: sun }
#   response: jsonrpc: 2.0
#             Event: View, state: working, mode: sun, tracking: false, planet_correction: false
# method: start_scan_planet
#   responses: jsonrpc
#              Event: ScanSun, state: working, route: [ View ]
#              Event: ScanSun, state: complete, route: [ View ]
# method: clear_app_state, params: { name: ScanSun }
# method: scope_set_track_state, params: { tracking: true }
#

# Event handlers
