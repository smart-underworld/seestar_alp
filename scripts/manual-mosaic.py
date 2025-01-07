#!/usr/bin/env python3
"""
An example script for generating individual scheduled items for a mosaic
"""
import sys
import os
import argparse
import json

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.realpath(os.path.join(current, ".."))
sys.path.append(parent)

from device.seestar_util import Util

#
# Tunables
#
class Tunables:
    def __init__(self, tn,ij,nra,ndec,cra,cdec,ov,pts,lp,af,dh,g,po,nr,rws) -> None:
        self.target_name=tn
        self.is_j2000=ij
        self.nRA = nra
        self.nDec = ndec
        self.center_RA = cra
        self.center_Dec = cdec
        self.overlap_percent = ov
        self.panel_time_sec = pts
        self.use_LPF = lp
        self.use_AF = af
        self.use_heater = dh
        self.gain = g
        self.panel_order = po
        self.num_tries = nr
        self.retry_wait_s = rws

class ManualMosaic:
    def __init__(self, tunables) -> None:
        self.tunables = tunables
        self.panels = {}
        self.schedule = {
            "version": 1.0,
            "state": "stoppped",
            "current_item_id": "",
            "item_number": 0,
            "list": []
        }

    def calculate(self):
        parsed_coord = Util.parse_coordinate(self.tunables.is_j2000, self.tunables.center_RA, self.tunables.center_Dec)
        center_RA = parsed_coord.ra.hour
        center_Dec = parsed_coord.dec.deg

        spacing_result = Util.mosaic_next_center_spacing(center_RA, center_Dec, self.tunables.overlap_percent)
        delta_RA = spacing_result[0]
        delta_Dec = spacing_result[1]

        # adjust mosaic center if num panels is even
        if self.tunables.nRA % 2 == 0:
            center_RA += delta_RA / 2
        if self.tunables.nDec % 2 == 0:
            center_Dec += delta_Dec / 2

        cur_dec = center_Dec - int(self.tunables.nDec / 2) * delta_Dec

        for index_dec in range(self.tunables.nDec):
            spacing_result = Util.mosaic_next_center_spacing(center_RA, cur_dec, self.tunables.overlap_percent)
            delta_RA = spacing_result[0]
            cur_ra = center_RA - int(self.tunables.nRA / 2) * spacing_result[0]
            for index_ra in range(self.tunables.nRA):
                panel_string = str(index_ra + 1) + str(index_dec + 1)

                panel_dict = {
                    "action": "start_mosaic",
                    "params": {
                        "dec": cur_dec,
                        "dec_num": 1,
                        "gain": self.tunables.gain,
                        "is_j2000": self.tunables.is_j2000,
                        "is_use_autofocus": self.tunables.use_AF,
                        "is_use_lp_filter": self.tunables.use_LPF,
                        "num_tries": self.tunables.num_tries,
                        "panel_overlap_percent": 100,
                        "ra": cur_ra,
                        "ra_num": 1,
                        "retry_wait_s": self.tunables.retry_wait_s,
                        "target_name": self.tunables.target_name + "_" + panel_string,
                        "panel_time_sec": self.tunables.panel_time_sec
                    }
                }
                self.panels[panel_string] = panel_dict

                cur_ra += delta_RA
            cur_dec += delta_Dec

    def print_schedule(self):
        # Print panels in order specified
        if self.tunables.panel_order:
            ordered_list = []
            for p in self.tunables.panel_order.split(";"):
                ordered_list.append(self.panels[p])
            self.schedule["list"] = ordered_list
        else:
            self.schedule["list"] = list(self.panels.values())

        print(json.dumps(self.schedule, indent=4))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate mosaic panels')
    parser.add_argument('--target_name', required=True)
    parser.add_argument('--j2000', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--nRA', required=True, type=int)
    parser.add_argument('--nDec', required=True, type=int)
    parser.add_argument('--center_RA', required=True)
    parser.add_argument('--center_Dec', required=True)
    parser.add_argument('--overlap_percent', type=int, default=20)
    parser.add_argument('--panel_time_sec', required=True, type=int)
    parser.add_argument('--use_LPF', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--use_AF', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--use_heater', action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--gain', type=int, default=80)
    parser.add_argument('--panel_order', default=None)
    parser.add_argument('--num_tries', default=1)
    parser.add_argument('--retry_wait_s', default=300)

    args = parser.parse_args()

    # Example target
    #target_name="CygnusLoop"
    #is_j2000=False
    #nRA = 5
    #nDec = 3
    #center_RA="20h51m29.31s"
    #center_Dec="+30d40m30.9s"
    #overlap_percent=20
    #panel_time_sec=4800
    #use_LPF=True
    #use_AF=False
    #use_heater=False
    #gain=110
    #panel_order="33;43;23;53;13;52;22;32;42;51;21;12;31;41;11"
    #panel_order=None
    t = Tunables(
        args.target_name,
        args.j2000,
        args.nRA,
        args.nDec,
        args.center_RA,
        args.center_Dec,
        args.overlap_percent,
        args.panel_time_sec,
        args.use_LPF,
        args.use_AF,
        args.use_heater,
        args.gain,
        args.panel_order,
        args.num_tries,
        args.retry_wait_s
    )
    mm = ManualMosaic(t)
    mm.calculate()
    mm.print_schedule()
