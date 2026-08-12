#!/bin/bash
set -e
# NEXA LOCAL AI — Full Deploy

DRC_DIR="/opt/nexa-ai"
APP_DIR="$DRC_DIR/app"
DATA_DIR="$DRC_DIR/data"
LOG_DIR="$DRC_DIR/logs"
SKILLS_DIR="$DRC_DIR/skills"
BIN_DIR="$DRC_DIR/bin"
MODEL="qwen2.5:7b"
R1_MODEL="deepseek-r1:7b"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA LOCAL AI — DEPLOY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash deploy-nexa.sh" && exit 1

# Inspect
RAM_MB=$(free -m | awk '/^Mem:/ {print $2}')
RAM_GB=$(awk "BEGIN {printf \"%.1f\", $RAM_MB/1024}")
CPU_CORES=$(nproc)
DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')

echo ""
echo "📋 VPS Specs:"
echo "  RAM: ${RAM_GB}GB | Cores: $CPU_CORES | Disk Free: $DISK_FREE"

if [ "$RAM_MB" -lt 8000 ]; then
    echo "⚠️  Low RAM detected. Using llama3.2:3b instead of qwen2.5:7b"
    MODEL="llama3.2:3b"
    R1_MODEL=""
fi

echo "  Main Model: $MODEL"
[ -n "$R1_MODEL" ] && echo "  Reasoning: $R1_MODEL"
read -p "Press Enter to continue..."

# Deps
echo ""
echo "📦 Installing dependencies..."
apt-get update -qq && apt-get install -y -qq curl python3 python3-venv sqlite3 lsb-release

# Ollama
if ! command -v ollama &>/dev/null; then
    echo "🦙 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Structure
mkdir -p "$APP_DIR" "$DATA_DIR" "$LOG_DIR" "$SKILLS_DIR" "$BIN_DIR"
python3 -m venv "$DRC_DIR/venv" 2>/dev/null || true

# App
cat > "$APP_DIR/nexa-chat.py" << 'PYEOF'
#!/usr/bin/env python3
import os, sys, sqlite3, json, signal, readline, time, shutil, threading, subprocess, re
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote_plus

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("NEXA_MODEL", "qwen2.5:7b")
REASONING_MODEL = os.environ.get("NEXA_REASONING", "deepseek-r1:7b")
DB_DIR = "/opt/nexa-ai/data"
DB_PATH = os.path.join(DB_DIR, "memory.db")
SKILLS_DIR = "/opt/nexa-ai/skills"
MAX_CONTEXT = 20
HISTORY_FILE = os.path.expanduser("~/.nexa_history")
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GRN, YLW, BLU, MAG, CYN = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m"

_spinner_running = False
_spinner_thread = None

def _spinner_task(text="Thinking"):
    chars = ["◐", "◓", "◑", "◒"]
    i = 0
    while _spinner_running:
        col = [CYN, BLU, MAG, GRN][i % 4]
        sys.stdout.write(f"\r{col}{B}{chars[i % 4]}{R} {D}{text}...{R}  ")
        sys.stdout.flush()
        time.sleep(0.12)
        i += 1
    sys.stdout.write("\r" + " " * 40 + "\r")
    sys.stdout.flush()

def start_spinner(text="Thinking"):
    global _spinner_running, _spinner_thread
    _spinner_running = True
    _spinner_thread = threading.Thread(target=_spinner_task, args=(text,), daemon=True)
    _spinner_thread.start()

def stop_spinner():
    global _spinner_running
    _spinner_running = False
    if _spinner_thread: _spinner_thread.join(timeout=0.5)

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(SKILLS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT DEFAULT 'default', role TEXT NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE NOT NULL, title TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS skills (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, code TEXT NOT NULL, description TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()

def save_msg(role, content, session_id="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
    c.execute("""INSERT INTO sessions (session_id, title, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) ON CONFLICT(session_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP""", (session_id, content[:50]))
    conn.commit(); conn.close()

def load_ctx(session_id="default", limit=MAX_CONTEXT):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit))
    rows = c.fetchall(); conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def list_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT session_id, title, updated_at FROM sessions ORDER BY updated_at DESC")
    rows = c.fetchall(); conn.close()
    return rows

def clear_session(sid="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
    c.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
    conn.commit(); conn.close()

def get_history(sid="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content, timestamp FROM messages WHERE session_id=? ORDER BY id", (sid,))
    rows = c.fetchall(); conn.close()
    return rows

def save_skill(name, code, desc=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO skills (name, code, description) VALUES (?, ?, ?)", (name, code, desc))
    conn.commit(); conn.close()
    with open(os.path.join(SKILLS_DIR, f"{name}.py"), "w") as f: f.write(code)

def load_skills():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, code, description FROM skills")
    rows = c.fetchall(); conn.close()
    return rows

def run_skill(name, args=""):
    skills = {n: (c, d) for n, c, d in load_skills()}
    if name not in skills: return f"Skill '{name}' not found."
    code, desc = skills[name]
    try:
        safe_globals = {"__builtins__": {"print": print, "len": len, "str": str, "int": int, "float": float, "list": list, "dict": dict, "range": range}, "os": os, "sys": sys, "subprocess": subprocess, "json": json, "re": re}
        safe_locals = {"args": args}
        exec(code, safe_globals, safe_locals)
        return safe_locals.get("result", "Skill executed.")
    except Exception as e: return f"Skill error: {e}"

def web_search(query, max_results=5):
    try:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        results = []
        for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>', html):
            link, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2))
            if link.startswith("http") and len(results) < max_results:
                results.append(f"{title}\n  → {link}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e: return f"Search error: {e}"

def shell_cmd(cmd, timeout=30):
    blocked = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "init 0"]
    for b in blocked:
        if b in cmd.lower(): return f"❌ Blocked: {b}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = result.stdout.strip() or "(no output)"
        if result.stderr.strip() and result.returncode != 0:
            return f"Exit {result.returncode}\nSTDOUT:\n{out}\n\nSTDERR:\n{result.stderr.strip()}"
        return out
    except subprocess.TimeoutExpired: return "⏱ Timed out."
    except Exception as e: return f"Error: {e}"

def check_ollama():
    try:
        req = Request(f"{OLLAMA_HOST}/api/tags", method="GET")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return True, [m["name"] for m in data.get("models", [])]
    except Exception as e: return False, str(e)

def check_model(models, model_name):
    for m in models:
        if model_name in m or m.startswith(model_name.split(":")[0]): return True
    return False

def chat_ollama(messages, model=None, stream=True):
    model = model or MODEL
    payload = {"model": model, "messages": messages, "stream": stream, "options": {"num_ctx": 8192, "temperature": 0.6}}
    req = Request(f"{OLLAMA_HOST}/api/chat", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=300) as resp:
            full = ""
            for line in resp:
                line = line.decode().strip()
                if not line: continue
                try:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        text = chunk["message"]["content"]
                        full += text
                        if stream: sys.stdout.write(text); sys.stdout.flush()
                    if chunk.get("done"): break
                except: continue
            if stream: sys.stdout.write("\n"); sys.stdout.flush()
            return full
    except Exception as e: return f"Error: {e}"

def get_response_with_reasoning(user_msg, context, use_reasoning=True):
    ok, models = check_ollama()
    if not ok: return "❌ Ollama not running."
    has_r1 = check_model(models, REASONING_MODEL)
    has_qwen = check_model(models, MODEL)
    if not has_qwen: return f"❌ Model '{MODEL}' not found. Run: ollama pull {MODEL}"
    sys_msg = {"role": "system", "content": "You are NEXA, a highly capable AI assistant. Be concise, accurate, and helpful."}
    msgs = [sys_msg] + context + [{"role": "user", "content": user_msg}]
    if has_r1 and use_reasoning and ("why" in user_msg.lower() or "how" in user_msg.lower() or "explain" in user_msg.lower() or len(user_msg) > 50):
        start_spinner("Reasoning")
        r1_msgs = [{"role": "system", "content": "Think step by step. Provide detailed reasoning inside  <think>  tags, then give the final concise answer."}]
        r1_msgs += context[-5:] + [{"role": "user", "content": user_msg}]
        r1_resp = chat_ollama(r1_msgs, model=REASONING_MODEL, stream=False)
        stop_spinner()
        think_match = re.search(r' <think> (.*?)</think>', r1_resp, re.DOTALL)
        thinking = think_match.group(1).strip() if think_match else ""
        final = re.sub(r' <think> .*?</think>', '', r1_resp, flags=re.DOTALL).strip()
        if len(final) < 20:
            start_spinner("Synthesizing")
            qwen_msgs = [sys_msg, {"role": "system", "content": f"Based on this reasoning:\n{thinking[:2000]}\n\nProvide the final answer."}]
            qwen_msgs += context + [{"role": "user", "content": user_msg}]
            final = chat_ollama(qwen_msgs, model=MODEL, stream=False)
            stop_spinner()
        return final
    else:
        start_spinner("Thinking")
        resp = chat_ollama(msgs, model=MODEL, stream=False)
        stop_spinner()
        return resp

def detect_tool(user_input):
    ui = user_input.lower().strip()
    if ui.startswith("search ") or ui.startswith("find ") or ui.startswith("google ") or ui.startswith("web "):
        return "search", user_input.split(" ", 1)[1] if " " in user_input else ""
    if ui.startswith("! ") or ui.startswith("run ") or ui.startswith("shell ") or ui.startswith("exec "):
        return "shell", user_input.split(" ", 1)[1] if " " in user_input else ""
    if ui.startswith("skill ") or ui.startswith("use "):
        parts = user_input.split(" ", 2)
        return "skill", parts[1], parts[2] if len(parts) > 2 else ""
    if ui.startswith("learn ") or ui.startswith("teach "):
        return "learn", user_input
    return "chat", user_input

def banner():
    cols = shutil.get_terminal_size().columns
    w = min(54, cols - 4)
    print(f"\n{MAG}{B}", end="")
    print("╭" + "━" * w + "╮")
    t = "  NEXA LOCAL AI  "
    p = (w - len(t)) // 2
    print("┃" + " " * p + CYN + B + t + MAG + B + " " * (w - p - len(t)) + "┃")
    print("┣" + "━" * w + "┫")
    info = f"  Model: {MODEL}  "
    p2 = (w - len(info)) // 2
    print("┃" + " " * p2 + D + info + R + MAG + B + " " * (w - p2 - len(info)) + "┃")
    print("╰" + "━" * w + "╯")
    print(f"{R}")
    print(f"{D}Tools: search <query>  |  ! <cmd>  |  skill <name>  |  learn <desc>{R}")
    print(f"{D}Chat:  /new  /history  /clear  /skills  /help  /exit{R}\n")

def print_ai(text):
    text = re.sub(r' <think> .*?</think>', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'</?think>', '', text)
    print(f"{GRN}{B}NEXA:{R} {text}")

def print_sys(t, c=D): print(f"{c}{D}▸ {t}{R}")
def print_err(t): print(f"{RED}✖ {t}{R}")
def print_ok(t): print(f"{GRN}✔ {t}{R}")

def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    session_id = "default"
    if "--new" in sys.argv:
        session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    elif "--history" in sys.argv:
        init_db(); sessions = list_sessions()
        print(f"\n{MAG}{B}📜 Conversation History{R}\n")
        if not sessions: print_sys("No conversations yet.")
        else:
            for sid, title, updated in sessions:
                print(f"  {CYN}•{R} {sid:<28} {D}({updated}){R}")
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
        sys.exit(1)
    if not check_model(models, MODEL):
        print_err(f"Model '{MODEL}' not found.")
        print_sys(f"Pull: ollama pull {MODEL}"); sys.exit(1)
    print_ok(f"Ollama ready. Model: {MODEL}")
    if check_model(models, REASONING_MODEL): print_ok(f"Reasoning engine: {REASONING_MODEL}")
    time.sleep(0.2)
    banner()
    context = load_ctx(session_id)
    if context: print_sys(f"Loaded {len(context)} messages from memory.")
    try: readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError: pass
    while True:
        try: user_input = input(f"{BLU}{B}You{R} {D}❯{R} ").strip()
        except EOFError: break
        if not user_input: continue
        if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
            print_sys("Goodbye. NEXA offline."); break
        elif user_input.lower() == "/new":
            session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            context = []; print_ok("New conversation started."); continue
        elif user_input.lower() == "/clear":
            clear_session(session_id); context = []; print_ok("Conversation cleared."); continue
        elif user_input.lower() == "/history":
            history = get_history(session_id)
            print(f"\n{MAG}{B}📜 Session History{R}\n")
            for role, content, ts in history:
                color = BLU if role == "user" else GRN
                print(f"  {color}{B}{role.upper()}{R} {D}[{ts}]{R}\n  {content[:200]}{'...' if len(content)>200 else ''}\n")
            continue
        elif user_input.lower() == "/skills":
            skills = load_skills()
            print(f"\n{MAG}{B}🔧 Saved Skills{R}\n")
            if not skills: print_sys("No skills saved. Use 'learn <description>' to teach NEXA.")
            else:
                for name, code, desc in skills:
                    print(f"  {CYN}•{R} {name} {D}- {desc or 'No description'}{R}")
            print(); continue
        elif user_input.lower() == "/help":
            print(f"""
{MAG}{B}NEXA Commands:{R}
  /new       New conversation
  /history   Session history
  /clear     Clear session
  /skills    List learned skills
  /help      This help
  /exit      Quit

{MAG}{B}Tools:{R}
  search <query>     Web search
  ! <command>        Run shell command
  skill <name>       Run a saved skill
  learn <desc>       Teach NEXA a new skill

{MAG}{B}Usage:{R}
  nexa          Start chatting
  nexa --new    Fresh conversation
  n             Same as nexa
"""); continue
        tool_type, *tool_args = detect_tool(user_input)
        if tool_type == "search":
            query = tool_args[0]
            print_sys(f"Searching web for: {query}")
            start_spinner("Searching")
            results = web_search(query)
            stop_spinner()
            print(f"\n{YLW}{B}🔍 Search Results:{R}\n{results}\n")
            save_msg("user", f"[search] {query}", session_id)
            save_msg("assistant", results, session_id)
            continue
        elif tool_type == "shell":
            cmd = tool_args[0]
            print_sys(f"Running: {cmd}")
            start_spinner("Executing")
            result = shell_cmd(cmd)
            stop_spinner()
            print(f"\n{CYN}{B}📟 Shell Output:{R}\n{result}\n")
            save_msg("user", f"[shell] {cmd}", session_id)
            save_msg("assistant", result, session_id)
            continue
        elif tool_type == "skill":
            name = tool_args[0]
            args = tool_args[1] if len(tool_args) > 1 else ""
            print_sys(f"Running skill: {name}")
            result = run_skill(name, args)
            print(f"\n{CYN}{B}🔧 Skill Result:{R}\n{result}\n")
            save_msg("user", f"[skill] {name}", session_id)
            save_msg("assistant", result, session_id)
            continue
        elif tool_type == "learn":
            desc = user_input.split(" ", 1)[1] if " " in user_input else "new skill"
            print_sys(f"Learning new skill: {desc}")
            learn_prompt = f"Write a Python script that {desc}. Store result in variable 'result'. Only valid Python, no explanations."
            start_spinner("Learning")
            code = chat_ollama([{"role": "user", "content": learn_prompt}], stream=False)
            stop_spinner()
            code = code.strip()
            if code.startswith("```"): code = "\n".join(code.split("\n")[1:-1])
            skill_name = re.sub(r"[^a-z0-9_]", "_", desc.lower())[:20]
            save_skill(skill_name, code, desc)
            print_ok(f"Skill '{skill_name}' learned!")
            print(f"{D}Code:\n{code[:300]}...{R}")
            continue
        save_msg("user", user_input, session_id)
        response = get_response_with_reasoning(user_input, context, use_reasoning=True)
        if response and not response.startswith("Error") and not response.startswith("❌"):
            print_ai(response)
            save_msg("assistant", response, session_id)
            context = load_ctx(session_id, MAX_CONTEXT)
        else: print_err(response or "No response.")
    try: readline.write_history_file(HISTORY_FILE)
    except: pass
    print()

if __name__ == "__main__": main()
PYEOF

chmod +x "$APP_DIR/nexa-chat.py"

# Wrappers
cat > "$BIN_DIR/nexa" << 'EOF'
#!/bin/bash
export NEXA_MODEL="${NEXA_MODEL:-qwen2.5:7b}"
export NEXA_REASONING="${NEXA_REASONING:-deepseek-r1:7b}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
/opt/nexa-ai/venv/bin/python3 /opt/nexa-ai/app/nexa-chat.py "$@"
EOF
chmod +x "$BIN_DIR/nexa"
cp "$BIN_DIR/nexa" "$BIN_DIR/n"
chmod +x "$BIN_DIR/n"
ln -sf "$BIN_DIR/nexa" /usr/local/bin/nexa
ln -sf "$BIN_DIR/n" /usr/local/bin/n

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

echo "⬇️ Pulling models (this may take 10-20 min)..."
ollama pull "$MODEL"
[ -n "$R1_MODEL" ] && ollama pull "$R1_MODEL"

echo ""
echo "✅ NEXA LOCAL AI installed!"
echo ""
echo "Usage:"
echo "  nexa        → Start AI chat"
echo "  n           → Same"
echo "  nexa --new  → Fresh conversation"
echo ""
echo "Inside chat:"
echo "  search <query>   Web search"
echo "  ! <cmd>          Run shell command"
echo "  learn <desc>     Teach new skill"
echo "  skill <name>     Run saved skill"
echo "  /new /history /clear /skills /help /exit"
echo ""
echo "Model: $MODEL"
[ -n "$R1_MODEL" ] && echo "Reasoning: $R1_MODEL"
echo "Data:  $DATA_DIR"
echo ""
