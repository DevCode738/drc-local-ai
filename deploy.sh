#!/bin/bash
# DRC Local AI — One-Shot Deploy
# This script contains everything embedded. Just run it.

set -e
[ "$EUID" -ne 0 ] && echo "Run as root: sudo bash deploy-all.sh" && exit 1

DRC_DIR="/opt/drc-ai"
MODEL="llama3.2:3b"

echo "🤖 DRC Local AI — One-Shot Deploy"
echo "=================================="

# Inspect
RAM_MB=$(free -m | awk '/^Mem:/ {print $2}')
[ "$RAM_MB" -gt 12000 ] && MODEL="qwen2.5:7b" || ([ "$RAM_MB" -gt 7000 ] && MODEL="llama3.2:3b" || MODEL="llama3.2:1b")
echo "Detected RAM: ${RAM_MB}MB → Model: $MODEL"

# Install deps
apt-get update -qq && apt-get install -y -qq curl python3 python3-venv sqlite3 lsb-release

# Install Ollama
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Structure
mkdir -p "$DRC_DIR"/{app,data,logs,config,bin}
python3 -m venv "$DRC_DIR/venv"

# Deploy app
cat > "$DRC_DIR/app/drc-chat.py" << 'PYEOF'
#!/usr/bin/env python3
import os, sys, sqlite3, json, signal, readline, time, shutil
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("DRC_MODEL", "llama3.2:3b")
DB_DIR = "/opt/drc-ai/data"
DB_PATH = os.path.join(DB_DIR, "conversations.db")
MAX_CONTEXT = 30
HISTORY_FILE = os.path.expanduser("~/.drc_chat_history")
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GRN, YLW, BLU, MAG, CYN = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m"

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT DEFAULT 'default', role TEXT NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE NOT NULL, title TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()

def save_message(role, content, session_id="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
    c.execute("""INSERT INTO sessions (session_id, title, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) ON CONFLICT(session_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP""", (session_id, content[:50]))
    conn.commit(); conn.close()

def load_context(session_id="default", limit=MAX_CONTEXT):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, limit))
    rows = c.fetchall(); conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def list_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT session_id, title, updated_at FROM sessions ORDER BY updated_at DESC")
    rows = c.fetchall(); conn.close()
    return rows

def clear_session(session_id="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit(); conn.close()

def get_session_history(session_id="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY id", (session_id,))
    rows = c.fetchall(); conn.close()
    return rows

def check_ollama():
    try:
        req = Request(f"{OLLAMA_HOST}/api/tags", method="GET")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return True, [m["name"] for m in data.get("models", [])]
    except Exception as e:
        return False, str(e)

def check_model(models):
    for m in models:
        if MODEL in m or m.startswith(MODEL.split(":")[0]):
            return True
    return False

def stream_chat(messages):
    payload = {"model": MODEL, "messages": messages, "stream": True, "options": {"num_ctx": 8192, "temperature": 0.7}}
    req = Request(f"{OLLAMA_HOST}/api/chat", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=300) as resp:
            full_text = ""
            for line in resp:
                line = line.decode().strip()
                if not line: continue
                try:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        text = chunk["message"]["content"]
                        full_text += text
                        sys.stdout.write(text); sys.stdout.flush()
                    if chunk.get("done"): break
                except json.JSONDecodeError: continue
            sys.stdout.write("\n"); sys.stdout.flush()
            return full_text
    except URLError as e:
        print(f"\n{RED}✖ Connection error: {e}{R}"); return None
    except Exception as e:
        print(f"\n{RED}✖ Error: {e}{R}"); return None

def banner():
    cols = shutil.get_terminal_size().columns
    w = min(50, cols - 4)
    print(f"\n{CYN}{B}╭{'─'*w}╮")
    t = " DRC LOCAL AI "
    p = (w - len(t)) // 2
    print(f"│{' '*p}{t}{' '*(w-p-len(t))}│")
    print(f"├{'─'*w}┤")
    i = f" Model: {MODEL} "
    p2 = (w - len(i)) // 2
    print(f"│{' '*p2}{D}{i}{R}{CYN}{B}{' '*(w-p2-len(i))}│")
    print(f"╰{'─'*w}╯{R}\n")
    print(f"{D}Commands: /new  /history  /clear  /help  /exit{R}\n")

def print_sys(t, c=D): print(f"{c}{D}▸ {t}{R}")
def print_err(t): print(f"{RED}✖ {t}{R}")
def print_ok(t): print(f"{GRN}✔ {t}{R}")

def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    session_id = "default"
    if "--new" in sys.argv:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    elif "--history" in sys.argv:
        init_db(); sessions = list_sessions()
        print(f"\n{BLU}{B}📜 Conversation History{R}\n")
        if not sessions: print_sys("No conversations yet.")
        else:
            for sid, title, updated in sessions:
                print(f"  {CYN}•{R} {sid:<25} {D}({updated}){R}")
                print(f"    {D}{title or '(no title)'}{R}")
        print(); return
    elif "--clear" in sys.argv:
        init_db(); clear_session(); print_ok("All conversations cleared."); return
    init_db()
    print_sys("Checking Ollama...")
    ok, models = check_ollama()
    if not ok:
        print_err(f"Ollama not running at {OLLAMA_HOST}")
        print_sys("Start: sudo systemctl start ollama")
        print_sys("Install: curl -fsSL https://ollama.com/install.sh | sh")
        sys.exit(1)
    if not check_model(models):
        print_err(f"Model '{MODEL}' not found.")
        print_sys(f"Pull: ollama pull {MODEL}"); sys.exit(1)
    print_ok(f"Ollama ready. Model: {MODEL}"); time.sleep(0.3)
    banner()
    context = load_context(session_id)
    if context: print_sys(f"Loaded {len(context)} messages from memory.")
    try: readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError: pass
    while True:
        try: user_input = input(f"{BLU}{B}You{R} {D}❯{R} ").strip()
        except EOFError: break
        if not user_input: continue
        if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
            print_sys("Goodbye."); break
        elif user_input.lower() == "/new":
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            context = []; print_ok("New conversation started."); continue
        elif user_input.lower() == "/clear":
            clear_session(session_id); context = []; print_ok("Conversation cleared."); continue
        elif user_input.lower() == "/history":
            history = get_session_history(session_id)
            print(f"\n{BLU}{B}📜 Current Session History{R}\n")
            for role, content, ts in history:
                color = BLU if role == "user" else GRN
                print(f"  {color}{B}{role.upper()}{R} {D}[{ts}]{R}\n  {content}\n")
            continue
        elif user_input.lower() == "/help":
            print(f"""
{BLU}{B}Commands:{R}
  /new      Start a new conversation
  /history  Show this session's history
  /clear    Clear current conversation
  /help     Show this help
  /exit     Quit

{BLU}{B}Usage:{R}
  chat          Start chatting (resumes last session)
  chat --new    Start fresh conversation
  chat --history  List all past conversations
  chat --clear    Delete all history
"""); continue
        save_message("user", user_input, session_id)
        messages = [{"role": "system", "content": "You are DRC, a helpful AI assistant. Be concise and direct."}]
        messages.extend(context)
        messages.append({"role": "user", "content": user_input})
        print(f"{GRN}{B}AI{R} {D}❯{R} ", end="", flush=True)
        response = stream_chat(messages)
        if response:
            save_message("assistant", response, session_id)
            context = load_context(session_id, MAX_CONTEXT)
        else: print_err("No response received.")
    try: readline.write_history_file(HISTORY_FILE)
    except: pass
    print()

if __name__ == "__main__": main()
PYEOF

chmod +x "$DRC_DIR/app/drc-chat.py"

# Wrappers
cat > "$DRC_DIR/bin/chat" << 'EOF'
#!/bin/bash
export DRC_MODEL="${DRC_MODEL:-llama3.2:3b}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
/opt/drc-ai/venv/bin/python3 /opt/drc-ai/app/drc-chat.py "$@"
EOF
chmod +x "$DRC_DIR/bin/chat"
cp "$DRC_DIR/bin/chat" "$DRC_DIR/bin/h"
chmod +x "$DRC_DIR/bin/h"
ln -sf "$DRC_DIR/bin/chat" /usr/local/bin/chat
ln -sf "$DRC_DIR/bin/h" /usr/local/bin/h

# Systemd
cat > /etc/systemd/system/ollama.service << 'EOF'
[Unit]
Description=Ollama AI Service
After=network-online.target
[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="HOME=/usr/share/ollama"
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_ORIGINS=*"
[Install]
WantedBy=default.target
EOF

id -u ollama &>/dev/null || useradd -r -s /bin/false -m -d /usr/share/ollama ollama
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "⏳ Waiting for Ollama..."
for i in {1..30}; do
    curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
done

echo "⬇️ Pulling model: $MODEL ..."
ollama pull "$MODEL"

echo "✅ Done!"
echo ""
echo "Test it:"
echo "  chat    → Start AI"
echo "  h       → Same"
echo ""
