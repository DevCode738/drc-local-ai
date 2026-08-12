#!/usr/bin/env python3
"""
NEXA v2 — Custom AI Engine
No Ollama. No local LLM server. Pure Python brain.
Uses free API tiers (OpenRouter) + SQLite memory + RAG + Tools.
"""

import os, sys, sqlite3, json, signal, readline, time, shutil, threading, subprocess, re, hashlib
from datetime import datetime
from urllib.request import urlopen, Request, urlretrieve
from urllib.error import URLError
from urllib.parse import quote_plus, urlparse

# ─── CONFIG ───
CONFIG_DIR = "/opt/nexa-ai/config"
DB_DIR = "/opt/nexa-ai/data"
SKILLS_DIR = "/opt/nexa-ai/skills"
DOWNLOADS_DIR = "/opt/nexa-ai/downloads"
DB_PATH = os.path.join(DB_DIR, "brain.db")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
HISTORY_FILE = os.path.expanduser("~/.nexa_history")

# API Config — OpenRouter free tier (no local LLM)
DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nousresearch/hermes-3-llama-3.1-405b:free"  # 405B free tier
FALLBACK_MODEL = "meta-llama/llama-3.1-8b-instruct:free"

# Colors
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GRN, YLW, BLU, MAG, CYN, WHT = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m", "\033[97m"

# ─── SPINNER ───
_spin_run = False
_spin_thr = None

def _spin_task(text):
    chars = ["◐","◓","◑","◒"]
    cols = [CYN, BLU, MAG, GRN]
    i = 0
    while _spin_run:
        sys.stdout.write(f"\r{cols[i%4]}{B}{chars[i%4]}{R} {D}{text}...{R}  ")
        sys.stdout.flush()
        time.sleep(0.1)
        i += 1
    sys.stdout.write("\r" + " "*50 + "\r")
    sys.stdout.flush()

def spin_start(text="Thinking"):
    global _spin_run, _spin_thr
    _spin_run = True
    _spin_thr = threading.Thread(target=_spin_task, args=(text,), daemon=True)
    _spin_thr.start()

def spin_stop():
    global _spin_run
    _spin_run = False
    if _spin_thr: _spin_thr.join(timeout=0.5)

# ─── CONFIG ───
def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f: return json.load(f)
    return {"api_url": DEFAULT_API_URL, "api_key": "", "model": DEFAULT_MODEL, "fallback_model": FALLBACK_MODEL, "reasoning": True}

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f: json.dump(cfg, f, indent=2)

# ─── DB ───
def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY, session_id TEXT DEFAULT 'default',
        role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY, source TEXT, chunk TEXT,
        embedding BLOB, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, title TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, code TEXT, desc TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY, url TEXT, path TEXT, status TEXT)""")
    conn.commit(); conn.close()

def save_msg(role, content, sid="default"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (sid, role, content))
    c.execute("""INSERT INTO sessions (session_id, title, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(session_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP""", (sid, content[:50]))
    conn.commit(); conn.close()

def load_ctx(sid="default", limit=15):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (sid, limit))
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

# ─── KNOWLEDGE / RAG ───
def add_knowledge(source, text):
    """Chunk and store text in knowledge base."""
    chunks = [text[i:i+500] for i in range(0, len(text), 500)]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for chunk in chunks:
        emb = simple_embed(chunk)
        c.execute("INSERT INTO knowledge (source, chunk, embedding) VALUES (?, ?, ?)",
                  (source, chunk, json.dumps(emb)))
    conn.commit(); conn.close()

def simple_embed(text):
    """Simple hash-based embedding (lightweight, no heavy models)."""
    text = text.lower()
    vec = [0.0]*128
    for i, word in enumerate(re.findall(r"\b\w+\b", text)):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % 128] += 1.0
    norm = sum(x*x for x in vec)**0.5 or 1.0
    return [x/norm for x in vec]

def cosine_sim(a, b):
    return sum(x*y for x, y in zip(a, b))

def search_knowledge(query, top_k=3):
    """Retrieve relevant knowledge chunks."""
    q_emb = simple_embed(query)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT source, chunk, embedding FROM knowledge")
    rows = c.fetchall(); conn.close()
    scored = []
    for source, chunk, emb_json in rows:
        emb = json.loads(emb_json)
        score = cosine_sim(q_emb, emb)
        scored.append((score, source, chunk))
    scored.sort(reverse=True)
    return scored[:top_k]

# ─── LLM API ───
def llm_chat(messages, model=None, stream=False, reasoning=False):
    """Call external LLM API. No local models."""
    cfg = load_config()
    api_key = cfg.get("api_key", "")
    api_url = cfg.get("api_url", DEFAULT_API_URL)
    model = model or cfg.get("model", DEFAULT_MODEL)

    if not api_key:
        return "❌ No API key. Get free key from https://openrouter.ai/keys and run:\n  nexa --setup"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nexa-ai.local",
        "X-Title": "NEXA Local AI"
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        req = Request(api_url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            elif "error" in data:
                err = data["error"]
                if "rate limit" in str(err).lower() or "quota" in str(err).lower():
                    # Try fallback model
                    if model != cfg.get("fallback_model"):
                        return llm_chat(messages, model=cfg.get("fallback_model"), stream=stream, reasoning=reasoning)
                return f"❌ API Error: {err}"
            return "❌ No response from API"
    except URLError as e:
        return f"❌ Network error: {e}"
    except Exception as e:
        return f"❌ Error: {e}"

def get_reasoning_response(user_msg, context, cfg):
    """Hidden reasoning + final answer."""
    needs_reasoning = cfg.get("reasoning", True) and (
        any(k in user_msg.lower() for k in ["why", "how", "explain", "solve", "calculate", "what if", "compare", "difference", "logic", "riddle"])
        or len(user_msg) > 80
    )

    sys_msg = {"role": "system", "content": "You are NEXA, an advanced AI. Be concise, accurate, and helpful."}

    # Add knowledge context
    knowledge = search_knowledge(user_msg)
    knowledge_text = ""
    if knowledge:
        knowledge_text = "\n\nRelevant knowledge:\n" + "\n".join([f"[{s}]: {c[:300]}" for _, s, c in knowledge])

    if needs_reasoning:
        spin_start("Reasoning")
        # Step 1: Get reasoning
        reason_msgs = [
            sys_msg,
            {"role": "system", "content": "Think step by step. Put your detailed reasoning inside   tags. Then provide the final concise answer after the reasoning."},
            {"role": "user", "content": user_msg + knowledge_text}
        ]
        reason_msgs.extend(context[-5:])
        raw = llm_chat(reason_msgs, stream=False, reasoning=True)
        spin_stop()

        if raw.startswith("❌"):
            return raw

        # Extract thinking and answer
        think_match = re.search(r'  (.*?)  ', raw, re.DOTALL)
        thinking = think_match.group(1).strip() if think_match else ""
        final = re.sub(r'  .*?  ', '', raw, flags=re.DOTALL).strip()

        # Store reasoning for learning
        if thinking:
            add_knowledge("reasoning", thinking)

        # If final answer is too short, synthesize better
        if len(final) < 30 and thinking:
            spin_start("Synthesizing")
            syn_msgs = [
                sys_msg,
                {"role": "system", "content": f"Based on this reasoning, give a clear final answer:\n{thinking[:1500]}"},
                {"role": "user", "content": user_msg}
            ]
            final = llm_chat(syn_msgs, stream=False)
            spin_stop()

        return final if final else raw
    else:
        spin_start("Thinking")
        msgs = [sys_msg, {"role": "user", "content": user_msg + knowledge_text}]
        msgs.extend(context)
        resp = llm_chat(msgs, stream=False)
        spin_stop()
        return resp

# ─── TOOLS ───
def web_search(query, max_results=5):
    try:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        results = []
        for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>', html):
            link, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2))
            if link.startswith("http") and len(results) < max_results:
                results.append(f"{title}\n  → {link}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {e}"

def download_file(url, filename=None):
    """Download file from direct link without signup."""
    try:
        parsed = urlparse(url)
        if not filename:
            filename = os.path.basename(parsed.path) or "download"
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        spin_start("Downloading")
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=60) as resp:
            with open(filepath, "wb") as f:
                f.write(resp.read())
        spin_stop()
        # Store in DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO downloads (url, path, status) VALUES (?, ?, ?)", (url, filepath, "done"))
        conn.commit(); conn.close()
        return f"✅ Downloaded: {filepath}"
    except Exception as e:
        spin_stop()
        return f"❌ Download failed: {e}"

def fetch_url_text(url):
    """Fetch and extract text from a webpage."""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Simple text extraction
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:10000]  # Limit size
    except Exception as e:
        return f"Error fetching URL: {e}"

def shell_cmd(cmd, timeout=30):
    blocked = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "init 0", "halt"]
    for b in blocked:
        if b in cmd.lower():
            return f"❌ Blocked dangerous command: {b}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = result.stdout.strip() or "(no output)"
        if result.returncode != 0 and result.stderr.strip():
            return f"Exit {result.returncode}\n{out}\nSTDERR:\n{result.stderr.strip()}"
        return out
    except subprocess.TimeoutExpired:
        return "⏱ Command timed out."
    except Exception as e:
        return f"Error: {e}"

def save_skill(name, code, desc=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO skills (name, code, desc) VALUES (?, ?, ?)", (name, code, desc))
    conn.commit(); conn.close()
    with open(os.path.join(SKILLS_DIR, f"{name}.py"), "w") as f:
        f.write(code)

def load_skills():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, code, desc FROM skills")
    rows = c.fetchall(); conn.close()
    return rows

def run_skill(name, args=""):
    skills = {n: (c, d) for n, c, d in load_skills()}
    if name not in skills:
        return f"Skill '{name}' not found."
    code, desc = skills[name]
    try:
        safe_globals = {"__builtins__": {"print": print, "len": len, "str": str, "int": int, "float": float, "list": list, "dict": dict, "range": range, "open": open}, "os": os, "sys": sys, "subprocess": subprocess, "json": json, "re": re, "requests": None}
        safe_locals = {"args": args, "result": None}
        exec(code, safe_globals, safe_locals)
        return str(safe_locals.get("result", "Skill executed."))
    except Exception as e:
        return f"Skill error: {e}"

# ─── TOOL DETECTION ───
def detect_tool(ui):
    ui = ui.lower().strip()
    if ui.startswith("search ") or ui.startswith("find ") or ui.startswith("google "):
        return "search", ui.split(" ", 1)[1] if " " in ui else ""
    if ui.startswith("! ") or ui.startswith("run ") or ui.startswith("shell ") or ui.startswith("exec "):
        return "shell", ui.split(" ", 1)[1] if " " in ui else ""
    if ui.startswith("download ") or ui.startswith("dl "):
        return "download", ui.split(" ", 1)[1] if " " in ui else ""
    if ui.startswith("learn ") or ui.startswith("ingest "):
        return "learn", ui.split(" ", 1)[1] if " " in ui else ""
    if ui.startswith("skill ") or ui.startswith("use "):
        parts = ui.split(" ", 2)
        return "skill", parts[1], parts[2] if len(parts) > 2 else ""
    return "chat", ui

# ─── UI ───
def banner():
    cols = shutil.get_terminal_size().columns
    w = min(56, cols - 4)
    print(f"\n{MAG}{B}", end="")
    print("╭" + "━" * w + "╮")
    t = "   NEXA v2 — CUSTOM AI   "
    p = (w - len(t)) // 2
    print("┃" + " " * p + CYN + B + t + MAG + B + " " * (w - p - len(t)) + "┃")
    print("┣" + "━" * w + "┫")
    cfg = load_config()
    mdl = cfg.get("model", DEFAULT_MODEL).split("/")[-1][:20]
    info = f"  Engine: API + SQLite Brain  "
    p2 = (w - len(info)) // 2
    print("┃" + " " * p2 + D + info + R + MAG + B + " " * (w - p2 - len(info)) + "┃")
    print("╰" + "━" * w + "╯")
    print(f"{R}")
    print(f"{D}Tools: search <q> | ! <cmd> | download <url> | learn <url/file>{R}")
    print(f"{D}Chat:  /new /history /clear /skills /setup /help /exit{R}\n")

def print_ai(text):
    text = re.sub(r'  .*?  ', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'</?think>', '', text)
    print(f"{GRN}{B}NEXA:{R} {text}")

def print_sys(t, c=D): print(f"{c}{D}▸ {t}{R}")
def print_err(t): print(f"{RED}✖ {t}{R}")
def print_ok(t): print(f"{GRN}✔ {t}{R}")

# ─── SETUP WIZARD ───
def setup_wizard():
    print(f"\n{BLU}{B}🔧 NEXA API Setup{R}\n")
    print("NEXA uses OpenRouter free tier (no local LLM needed).")
    print("Get your FREE API key from: https://openrouter.ai/keys")
    print("(No credit card required)\n")
    key = input("Enter OpenRouter API key (or press Enter to skip): ").strip()
    if key:
        cfg = load_config()
        cfg["api_key"] = key
        save_config(cfg)
        print_ok("API key saved!")
        # Test
        print_sys("Testing API...")
        spin_start("Testing")
        test = llm_chat([{"role": "user", "content": "Say 'NEXA online' in 2 words"}], stream=False)
        spin_stop()
        if test.startswith("❌"):
            print_err(f"Test failed: {test}")
        else:
            print_ok(f"API test passed: {test}")
    else:
        print_sys("No key entered. You can add later with: nexa --setup")

# ─── MAIN ───
def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    if "--setup" in sys.argv:
        init_db(); setup_wizard(); return

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
        print(); return
    elif "--clear" in sys.argv:
        init_db(); clear_session(); print_ok("All conversations cleared."); return

    init_db()
    cfg = load_config()

    if not cfg.get("api_key"):
        print_err("No API key configured.")
        print_sys("Run: nexa --setup")
        print_sys("Get free key: https://openrouter.ai/keys")
        return

    print_sys("Connecting to AI brain...")
    spin_start("Initializing")
    test = llm_chat([{"role": "user", "content": "hi"}], stream=False)
    spin_stop()

    if test.startswith("❌"):
        print_err(f"Connection failed: {test}")
        print_sys("Check API key or run: nexa --setup")
        return

    print_ok(f"Brain online. Model: {cfg.get('model', DEFAULT_MODEL).split('/')[-1]}")
    time.sleep(0.2)
    banner()

    context = load_ctx(session_id)
    if context: print_sys(f"Loaded {len(context)} messages from memory.")

    try: readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError: pass

    while True:
        try:
            user_input = input(f"{BLU}{B}You{R} {D}❯{R} ").strip()
        except EOFError: break
        if not user_input: continue

        # Built-in commands
        if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
            print_sys("NEXA offline. Goodbye."); break
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
        elif user_input.lower() == "/setup":
            setup_wizard(); continue
        elif user_input.lower() == "/help":
            print(f"""
{MAG}{B}NEXA v2 Commands:{R}
  /new       New conversation
  /history   Session history
  /clear     Clear session
  /skills    List learned skills
  /setup     Configure API key
  /help      This help
  /exit      Quit

{MAG}{B}Tools:{R}
  search <query>        Web search (DuckDuckGo)
  ! <command>           Run shell command
  download <url>        Download file directly
  learn <url/file>      Ingest knowledge into brain
  skill <name>          Run saved skill
  learn skill <desc>    Teach NEXA a new skill

{MAG}{B}Usage:{R}
  nexa          Start AI chat
  nexa --new    Fresh conversation
  nexa --setup  Add API key
  n             Same as nexa
""")
            continue

        # Tool detection
        tool_type, *tool_args = detect_tool(user_input)

        if tool_type == "search":
            query = tool_args[0]
            print_sys(f"Searching web: {query}")
            spin_start("Searching")
            results = web_search(query)
            spin_stop()
            print(f"\n{YLW}{B}🔍 Results:{R}\n{results}\n")
            save_msg("user", f"[search] {query}", session_id)
            save_msg("assistant", results, session_id)
            continue

        elif tool_type == "shell":
            cmd = tool_args[0]
            print_sys(f"Executing: {cmd}")
            spin_start("Executing")
            result = shell_cmd(cmd)
            spin_stop()
            print(f"\n{CYN}{B}📟 Output:{R}\n{result}\n")
            save_msg("user", f"[shell] {cmd}", session_id)
            save_msg("assistant", result, session_id)
            continue

        elif tool_type == "download":
            url = tool_args[0]
            result = download_file(url)
            print(f"\n{BLU}{B}📥 Download:{R}\n{result}\n")
            save_msg("user", f"[download] {url}", session_id)
            save_msg("assistant", result, session_id)
            continue

        elif tool_type == "learn":
            source = tool_args[0]
            print_sys(f"Learning from: {source}")
            spin_start("Ingesting")
            if source.startswith("http://") or source.startswith("https://"):
                text = fetch_url_text(source)
            elif os.path.exists(source):
                with open(source, "r", errors="ignore") as f:
                    text = f.read()
            else:
                spin_stop()
                print_err("Source not found. Provide URL or file path.")
                continue

            if text.startswith("Error"):
                spin_stop()
                print_err(text)
                continue

            add_knowledge(source, text)
            spin_stop()
            print_ok(f"Learned {len(text)} chars from {source}")
            print_sys("This knowledge is now available for future queries.")
            save_msg("user", f"[learn] {source}", session_id)
            save_msg("assistant", f"Learned {len(text)} chars from {source}", session_id)
            continue

        elif tool_type == "skill":
            name = tool_args[0]
            args = tool_args[1] if len(tool_args) > 1 else ""
            print_sys(f"Running skill: {name}")
            result = run_skill(name, args)
            print(f"\n{CYN}{B}🔧 Skill:{R}\n{result}\n")
            save_msg("user", f"[skill] {name}", session_id)
            save_msg("assistant", result, session_id)
            continue

        # Normal chat with reasoning
        save_msg("user", user_input, session_id)
        response = get_reasoning_response(user_input, context, cfg)

        if response and not response.startswith("❌"):
            print_ai(response)
            save_msg("assistant", response, session_id)
            context = load_ctx(session_id, 15)
        else:
            print_err(response or "No response.")

    try: readline.write_history_file(HISTORY_FILE)
    except: pass
    print()

if __name__ == "__main__":
    main()
