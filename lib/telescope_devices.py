from typing import TypedDict

import requests


class TelescopeDevice(TypedDict):
    """Telescope connection parameters"""
    name: str
    ip_address: str
    api_ip_address: str
    port: int
    location: str
    telescope_id: int
    device_num: int # Alias for telescope_id
    # unique_id: str
    remote_offset: int


def get_telescope_devices(ip_address: str, port: int = 5555, remote_offset: int = 0, timeout: int = 2) -> list[TelescopeDevice]:
    """Returns list of telescope devices associated with a given ALP endpoint"""
    r = requests.get(f"http://{ip_address}:{port}/management/v1/configureddevices", timeout=timeout)
    # todo : capture errors
    response = r.json()
    values = response.get('Value')
    if len(values) == 1 and values[0].get('DeviceNumber') == 0:
        values[0]['DeviceNumber'] = 1

    return [{
        "name": tel.get('DeviceName'),
        "ip_address": ip_address,
        "api_ip_address": ip_address,
        "port": port,
        "location": tel.get('Location'),
        "telescope_id": remote_offset + tel['DeviceNumber'],
        "device_num": remote_offset + tel['DeviceNumber'],
        "remote_offset": remote_offset,
    } for tel in response.get('Value')]

    # 'name': tel['DeviceName'],
    # 'device_num': remote_num + tel['DeviceNumber'],
    # 'ip_address': ip_address,
    # 'api_ip_address': ip_address,
    # 'img_port': '7556',  # Todo : make this dynamic!
    # 'location': remote.get('location'),
    # 'remote_id': remote_num,
