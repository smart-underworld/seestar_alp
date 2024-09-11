#!/usr/bin/env python3
#
# This script generates stats for mosaic files, suggests an order to feed into manual-mosaic.py,
# And suggests times for each panel, in order to have equivalent SNR for each panel.
#
import os
import glob
import re
import sys

if len(sys.argv) != 2:
    print(f"usage: {sys.argv[0]} <Directory>")
    print("Where <Directory> has mosaic panels named Panel-11, Panel-12, etc")
    exit(1)


total_mins=0
panel_files={}
stat={}

panel_dirs=sorted(glob.glob(f"{sys.argv[1]}/Panel-*"))

def get_mins(panel_dir):
    s30_files=len(glob.glob(f"{panel_dir}/lights/*30.0s*.fit"))
    s20_files=len(glob.glob(f"{panel_dir}/lights/*20.0s*.fit"))
    s10_files=len(glob.glob(f"{panel_dir}/lights/*10.0s*.fit"))

    return {
        "mins" : (s30_files/2) + (s20_files/3) + (s10_files/6),
        "s30": s30_files,
        "s20": s20_files,
        "s10": s10_files
    }

def get_dates(panel_dir):
    dates = []
    for f in glob.glob(f"{panel_dir}/lights/*.fit"):
        d = re.search('.*_(202[0-9]*)-.*', f).group(1)
        dates += d
    return list(set(dates))

# find max mins
max_mins=0
for panel_dir in panel_dirs:
    mins=get_mins(panel_dir)["mins"]
    if mins > max_mins:
        max_mins = mins

all_dates=[]
print("Panel   \t30s\t20s\t10s\tHrs\tDiffMins")
for panel_dir in panel_dirs:
    panel=os.path.basename(panel_dir)
    panel_num=panel.split('-')[1]

    stats = get_mins(panel_dir)
    total_mins += stats["mins"]

    panel_files[panel_num]=stats["mins"]
    s30=stats["s30"]
    s20=stats["s20"]
    s10=stats["s10"]
    hours=round(stats["mins"]/60,2)
    diff=round(max_mins - stats["mins"],2)

    dates=get_dates(panel_dir)
    all_dates=list(set(all_dates + dates))

    print(f"{panel}:\t{s30}\t{s20}\t{s10}\t{hours}\t{diff}")

print(f"\ntotal:\t\t\t\t\t{round(total_mins/60,2)} hours")
print(f"sessions:\t\t\t\t{len(all_dates)}")

print("")


sorted = [k for k, v in sorted(panel_files.items(), key=lambda item: item[1])]
print("Next order:")
print(';'.join(sorted))

print("\nSuggested times(s):")
running_t=0
for panel in sorted:
    secs=panel_files[panel]*60
    max_secs=max_mins*60
    recommended_secs=int(max_secs-secs)
    running_t += recommended_secs
    print(f"{panel}\t{recommended_secs}")

print(f"total: {round(running_t/60/60,2)} hrs")