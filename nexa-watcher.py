#!/usr/bin/env python3
"""NEXA WATCHER — Live build log viewer"""

import os, sys, time, shutil
from pathlib import Path

LOG_FILE = Path("/opt/autonexa/logs/build.log")
STATE_FILE = Path("/opt/autonexa/data/state.json")

R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GRN, YLW, BLU, MAG, CYN = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m"
BLOCK = chr(9608)
EMPTY = chr(9617)

def read_state():
    try:
        import json
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except: pass
    return {}

def parse_log_line(line):
    import re
    m = re.match(r'\[(\d{2}:\d{2}:\d{2})\] \[(\w+)\] \[(\w+)\] (.+)', line)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    return None, None, None, line.strip()

def get_level_color(level):
    return {"INFO": BLU, "WARN": YLW, "ERROR": RED, "SUCCESS": GRN}.get(level, D)

def get_phase_icon(phase):
    icons = {
        "BOOT": "[R]", "INGESTION": "[K]", "BUILDING": "[H]",
        "TESTING": "[T]", "LEARNING": "[B]", "IMPROVING": "[I]",
        "IDLE": "[Z]", "LOOP": "[L]", "PHASE": "[P]",
        "FETCH": "[W]", "INIT": "[S]"
    }
    return icons.get(phase, "[*]")

def draw_frame(lines, state):
    cols = shutil.get_terminal_size().columns
    rows = shutil.get_terminal_size().lines

    uptime = int(time.time() - state.get("start_time", time.time()))
    hours = uptime // 3600
    mins = (uptime % 3600) // 60
    secs = uptime % 60

    header = f"{MAG}{B} NEXA BUILD WATCHER {R} {D}|{R} {CYN}Up: {hours:02d}:{mins:02d}:{secs:02d}{R} {D}|{R} {YLW}Phase: {state.get('phase', 'INIT')}{R} {D}|{R} {GRN}Iter: {state.get('iterations', 0)}{R}"

    progress = state.get("progress", 0)
    bar_width = min(40, cols - 20)
    filled = int(bar_width * progress / 100)
    bar = f"{GRN}{B}{BLOCK*filled}{R}{D}{EMPTY*(bar_width-filled)}{R} {progress}%"

    stats = f"{D}Sources: {state.get('sources_ingested', 0)} | Modules: {state.get('modules_built', 0)} | Tests: {state.get('tests_passed', 0)}OK/{state.get('tests_failed', 0)}FAIL{R}"

    print("\033[2J\033[H", end="")
    print(header)
    print(bar)
    print(stats)
    sep = "=" * min(cols-2, 60)
    print(f"{MAG}{B}{sep}{R}")

    max_lines = rows - 8
    for line in lines[-max_lines:]:
        ts, level, phase, msg = parse_log_line(line)
        if ts:
            icon = get_phase_icon(phase)
            color = get_level_color(level)
            print(f"  {icon} {D}{ts}{R} {color}[{level}]{R} {D}[{phase}]{R} {msg}")
        else:
            print(f"  {D}{line[:cols-4]}{R}")

    print(f"{MAG}{B}{sep}{R}")
    print(f"{D}Ctrl+C = exit | 'nexa' = chat | Logs: {LOG_FILE}{R}")

def watch():
    if not LOG_FILE.exists():
        print(f"{RED}[!] Build log not found.{R}")
        print(f"{D}Start builder: nohup python3 /opt/autonexa/nexa-core.py > /dev/null 2>&1 &{R}")
        return

    print(f"{CYN}[*] Starting NEXA watcher...{R}")
    time.sleep(1)

    try:
        with open(LOG_FILE, "r") as f:
            f.seek(0, 2)
            while True:
                lines = []
                while True:
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line.strip())

                state = read_state()
                if lines:
                    draw_frame(lines, state)
                else:
                    f.seek(0)
                    all_lines = [l.strip() for l in f.readlines()]
                    f.seek(0, 2)
                    draw_frame(all_lines, state)

                time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n{GRN}[*] Watcher stopped.{R}")

if __name__ == "__main__":
    watch()
