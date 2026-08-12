#!/usr/bin/env python3
"""
NEXA WATCHER — Live build log viewer with animation
Type 'x' anywhere to watch NEXA build itself
"""

import os, sys, time, shutil
from pathlib import Path

LOG_FILE = Path("/opt/autonexa/logs/build.log")
STATE_FILE = Path("/opt/autonexa/data/state.json")

R = "\033[0m"
B = "\033[1m"
D = "\033[2m"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
BLU = "\033[94m"
MAG = "\033[95m"
CYN = "\033[96m"

def read_state():
    try:
        import json
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except: pass
    return {}

def parse_log_line(line):
    """Parse log line into components."""
    # Format: [HH:MM:SS] [LEVEL] [PHASE] Message
    import re
    m = re.match(r'\[(\d{2}:\d{2}:\d{2})\] \[(\w+)\] \[(\w+)\] (.+)', line)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    return None, None, None, line.strip()

def get_level_color(level):
    return {"INFO": BLU, "WARN": YLW, "ERROR": RED, "SUCCESS": GRN}.get(level, D)

def get_phase_icon(phase):
    icons = {
        "BOOT": "🚀", "INGESTION": "📚", "BUILDING": "🔨",
        "TESTING": "🧪", "LEARNING": "🧠", "IMPROVING": "⚡",
        "IDLE": "💤", "LOOP": "🔄", "PHASE": "📋",
        "FETCH": "🌐", "INIT": "⚙️"
    }
    return icons.get(phase, "📌")

def draw_frame(lines, state):
    cols = shutil.get_terminal_size().columns
    rows = shutil.get_terminal_size().lines

    # Header
    uptime = int(time.time() - state.get("start_time", time.time()))
    hours = uptime // 3600
    mins = (uptime % 3600) // 60
    secs = uptime % 60

    header = f"{MAG}{B} NEXA BUILD WATCHER {R} {D}|{R} {CYN}Uptime: {hours:02d}:{mins:02d}:{secs:02d}{R} {D}|{R} {YLW}Phase: {state.get('phase', 'UNKNOWN')}{R} {D}|{R} {GRN}Iter: {state.get('iterations', 0)}{R}"

    # Progress bar
    progress = state.get("progress", 0)
    bar_width = min(40, cols - 20)
    filled = int(bar_width * progress / 100)
    bar = f"{GRN}{B}{█*filled}{R}{D}{░*(bar_width-filled)}{R} {progress}%"

    # Stats
    stats = f"{D}Sources: {state.get('sources_ingested', 0)} | Modules: {state.get('modules_built', 0)} | Tests: {state.get('tests_passed', 0)}✓/{state.get('tests_failed', 0)}✗{R}"

    # Clear screen
    print("\033[2J\033[H", end="")

    # Draw
    print(header)
    print(bar)
    print(stats)
    print(f"{MAG}{B}{'━' * min(cols-2, 60)}{R}")

    # Show last N log lines
    max_lines = rows - 8
    for line in lines[-max_lines:]:
        ts, level, phase, msg = parse_log_line(line)
        if ts:
            icon = get_phase_icon(phase)
            color = get_level_color(level)
            print(f"  {icon} {D}{ts}{R} {color}[{level}]{R} {D}[{phase}]{R} {msg}")
        else:
            print(f"  {D}{line[:cols-4]}{R}")

    print(f"{MAG}{B}{'━' * min(cols-2, 60)}{R}")
    print(f"{D}Press Ctrl+C to exit watcher. Type 'nexa' to chat.{R}")

def watch():
    if not LOG_FILE.exists():
        print(f"{RED}✖ Build log not found.{R}")
        print(f"{D}Start NEXA first with nohup command.{R}")
        return

    print(f"{CYN}Starting NEXA build watcher...{R}")
    print(f"{D}Monitoring: {LOG_FILE}{R}\\n")
    time.sleep(1)

    try:
        with open(LOG_FILE, "r") as f:
            # Go to end
            f.seek(0, 2)

            while True:
                lines = []
                # Read all new lines
                while True:
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line.strip())

                if lines:
                    state = read_state()
                    draw_frame(lines, state)
                else:
                    # Just refresh state
                    state = read_state()
                    # Read last 20 lines for display
                    f.seek(0)
                    all_lines = [l.strip() for l in f.readlines()]
                    f.seek(0, 2)
                    draw_frame(all_lines, state)

                time.sleep(2)

    except KeyboardInterrupt:
        print(f"\\n{GRN}✔ Watcher stopped.{R}")

if __name__ == "__main__":
    watch()
