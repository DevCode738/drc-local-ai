#!/usr/bin/env python3
"""
NEXA OWN ENGINE — Pure Python, No Ollama, No OpenRouter, No External API
Loads GGUF model directly via llama-cpp-python. SQLite brain. Self-hosted.
"""

import os, sys, sqlite3, json, signal, readline, time, shutil, threading, subprocess, re, hashlib, math
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import quote_plus, urlparse

# ─── CONFIG ───
BASE_DIR = "/opt/nexa-ai"
MODEL_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(DATA_DIR, "brain.db")
HISTORY_FILE = os.path.expanduser("~/.nexa_history")

MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_NAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME)
N_CTX = 8192
N_THREADS = 4

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

# ─── DB ───
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY, session_id TEXT DEFAULT 'default',
        role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY, source TEXT, chunk TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
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

def load_ctx(sid="default", limit=20):
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

# ─── KNOWLEDGE ───
def add_knowledge(source, text):
    chunks = [text[i:i+800] for i in range(0, len(text), 800)]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for chunk in chunks:
        c.execute("INSERT INTO knowledge (source, chunk) VALUES (?, ?)", (source, chunk))
    conn.commit(); conn.close()

def search_knowledge(query, top_k=5):
    words = set(re.findall(r"\b\w+\b", query.lower()))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT source, chunk FROM knowledge")
    rows = c.fetchall(); conn.close()
    scored = []
    for source, chunk in rows:
        chunk_words = set(re.findall(r"\b\w+\b", chunk.lower()))
        score = len(words & chunk_words) / (len(words) + 1)
        scored.append((score, source, chunk))
    scored.sort(reverse=True)
    return scored[:top_k]

# ─── MODEL MANAGEMENT ───
def check_model():
    return os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 100_000_000

def download_model():
    print_sys(f"Downloading model (~1GB)...")
    print_sys(f"Source: HuggingFace Qwen2.5-1.5B-Instruct")
    spin_start("Downloading 1.5B model")
    try:
        req = Request(MODEL_URL, headers={"User-Agent": "NEXA-Engine/1.0"})
        with urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 8192
            with open(MODEL_PATH, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk: break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and downloaded % (1024*1024*50) == 0:
                        pct = (downloaded / total) * 100
                        sys.stdout.write(f"\r{D}▸ Downloaded: {pct:.1f}%{R}  ")
                        sys.stdout.flush()
        spin_stop()
        size_mb = os.path.getsize(MODEL_PATH) / (1024*1024)
        print_ok(f"Model downloaded: {size_mb:.1f} MB")
        return True
    except Exception as e:
        spin_stop()
        print_err(f"Download failed: {e}")
        return False

# ─── LLM ENGINE ───
_llm = None

def get_llm():
    global _llm
    if _llm is not None:
        return _llm
    try:
        from llama_cpp import Llama
    except ImportError:
        print_err("llama-cpp-python not installed.")
        print_sys("Run: pip install llama-cpp-python")
        sys.exit(1)

    if not check_model():
        if not download_model():
            print_err("Model not available. Cannot start.")
            sys.exit(1)

    print_sys("Loading model into RAM...")
    spin_start("Loading 1.5B parameters")
    _llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        verbose=False,
        use_mmap=True,
        use_mlock=False
    )
    spin_stop()
    print_ok(f"Model loaded. Threads: {N_THREADS} | Context: {N_CTX}")
    return _llm

def generate(messages, max_tokens=1024, temperature=0.7, stream=False):
    llm = get_llm()
    try:
        if stream:
            # Streaming not easily supported with simple API, simulate
            output = llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|im_end|>", "<|endoftext|>"]
            )
            text = output["choices"][0]["message"]["content"]
            # Simulate streaming
            for char in text:
                sys.stdout.write(char)
                sys.stdout.flush()
                time.sleep(0.005)
            sys.stdout.write("\n")
            return text
        else:
            output = llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|im_end|>", "<|endoftext|>"]
            )
            return output["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Generation error: {e}"

# ─── REASONING (HIDDEN) ───
def reason_and_answer(user_msg, context, use_reasoning=True):
    needs_reasoning = use_reasoning and (
        any(k in user_msg.lower() for k in ["why", "how", "explain", "solve", "calculate", "logic", "riddle", "which", "if", "compare"])
        or len(user_msg) > 60
    )

    sys_msg = {"role": "system", "content": "You are NEXA, an advanced AI assistant. Be concise, accurate, and helpful."}

    # Knowledge retrieval
    knowledge = search_knowledge(user_msg)
    knowledge_text = ""
    if knowledge:
        knowledge_text = "\n\nRelevant knowledge:\n" + "\n".join([f"[{s}]: {c[:400]}" for _, s, c in knowledge])

    if needs_reasoning:
        spin_start("Reasoning")
        # Step 1: Deep thinking (hidden)
        think_msgs = [
            {"role": "system", "content": "Think step by step deeply. Put your detailed reasoning inside <think> tags. After </think>, give only the final concise answer."},
            {"role": "user", "content": user_msg + knowledge_text}
        ]
        raw = generate(think_msgs, max_tokens=1500, temperature=0.5)
        spin_stop()

        if raw.startswith("❌"): return raw

        # Extract final answer (after </think> or outside tags)
        think_match = re.search(r'<think>(.*?)</think>', raw, re.DOTALL)
        thinking = think_match.group(1).strip() if think_match else ""
        final = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

        # Store reasoning for learning
        if thinking:
            add_knowledge("reasoning_session", thinking)

        # If final too short, synthesize
        if len(final) < 40 and thinking:
            spin_start("Synthesizing")
            syn_msgs = [
                sys_msg,
                {"role": "system", "content": f"Based on this reasoning, provide a clear final answer:\n{thinking[:1200]}"},
                {"role": "user", "content": user_msg}
            ]
            final = generate(syn_msgs, max_tokens=800, temperature=0.6)
            spin_stop()

        return final if final else raw
    else:
        spin_start("Thinking")
        msgs = [sys_msg, {"role": "user", "content": user_msg + knowledge_text}]
        msgs.extend(context[-10:])
        resp = generate(msgs, max_tokens=800, temperature=0.7)
        spin_stop()
        return resp

# ─── TOOLS ───
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
    except Exception as e:
        return f"Search error: {e}"

def fetch_url_text(url):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:12000]
    except Exception as e:
        return f"Error: {e}"

def download_file(url, filename=None):
    try:
        parsed = urlparse(url)
        if not filename:
            filename = os.path.basename(parsed.path) or "download"
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        spin_start("Downloading")
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=120) as resp:
            with open(filepath, "wb") as f:
                f.write(resp.read())
        spin_stop()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO downloads (url, path, status) VALUES (?, ?, ?)", (url, filepath, "done"))
        conn.commit(); conn.close()
        return f"✅ Downloaded: {filepath} ({os.path.getsize(filepath)} bytes)"
    except Exception as e:
        spin_stop()
        return f"❌ Download failed: {e}"

def shell_cmd(cmd, timeout=30):
    blocked = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "init 0", "halt", "fdisk"]
    for b in blocked:
        if b in cmd.lower():
            return f"❌ Blocked: {b}"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = result.stdout.strip() or "(no output)"
        if result.returncode != 0 and result.stderr.strip():
            return f"Exit {result.returncode}\n{out}\nSTDERR:\n{result.stderr.strip()}"
        return out
    except subprocess.TimeoutExpired:
        return "⏱ Timed out."
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
        safe_globals = {"__builtins__": {"print": print, "len": len, "str": str, "int": int, "float": float, "list": list, "dict": dict, "range": range, "open": open}, "os": os, "sys": sys, "subprocess": subprocess, "json": json, "re": re}
        safe_locals = {"args": args, "result": None}
        exec(code, safe_globals, safe_locals)
        return str(safe_locals.get("result", "Done"))
    except Exception as e:
        return f"Skill error: {e}"

# ─── TOOL DETECTION ───
def detect_tool(ui):
    ui = ui.lower().strip()
    if ui.startswith("search ") or ui.startswith("find ") or ui.startswith("google "):
        return "search", ui.split(" ", 1)[1] if " " in ui else ""
    if ui.startswith("! ") or ui.startswith("run ") or ui.startswith("shell "):
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
    w = min(58, cols - 4)
    print(f"\n{MAG}{B}", end="")
    print("╭" + "━" * w + "╮")
    t = "   NEXA OWN ENGINE v2.0   "
    p = (w - len(t)) // 2
    print("┃" + " " * p + CYN + B + t + MAG + B + " " * (w - p - len(t)) + "┃")
    print("┣" + "━" * w + "┫")
    info = f"  Engine: llama.cpp + Qwen2.5-1.5B  "
    p2 = (w - len(info)) // 2
    print("┃" + " " * p2 + D + info + R + MAG + B + " " * (w - p2 - len(info)) + "┃")
    print("╰" + "━" * w + "╯")
    print(f"{R}")
    print(f"{D}Tools: search <q> | ! <cmd> | download <url> | learn <url/file>{R}")
    print(f"{D}Chat:  /new /history /clear /skills /help /exit{R}\n")

def print_ai(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'</?think>', '', text)
    print(f"{GRN}{B}NEXA:{R} {text}")

def print_sys(t, c=D): print(f"{c}{D}▸ {t}{R}")
def print_err(t): print(f"{RED}✖ {t}{R}")
def print_ok(t): print(f"{GRN}✔ {t}{R}")

# ─── MAIN ───
def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    if "--new" in sys.argv:
        session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    elif "--history" in sys.argv:
        init_db(); sessions = list_sessions()
        print(f"\n{MAG}{B}📜 History{R}\n")
        if not sessions: print_sys("No conversations.")
        else:
            for sid, title, updated in sessions:
                print(f"  {CYN}•{R} {sid:<28} {D}({updated}){R}")
        print(); return
    elif "--clear" in sys.argv:
        init_db(); clear_session(); print_ok("Cleared."); return
    else:
        session_id = "default"

    init_db()

    # Check llama-cpp-python
    try:
        from llama_cpp import Llama
    except ImportError:
        print_err("llama-cpp-python not installed.")
        print_sys("Installing...")
        spin_start("Installing llama-cpp-python")
        ret = subprocess.run([sys.executable, "-m", "pip", "install", "llama-cpp-python", "-q"], capture_output=True)
        spin_stop()
        if ret.returncode != 0:
            print_err("Install failed. Try manually: pip install llama-cpp-python")
            sys.exit(1)
        print_ok("Installed. Restart NEXA.")
        return

    # Check/download model
    if not check_model():
        print_sys("Model not found. Will download ~1GB from HuggingFace.")
        if not download_model():
            print_err("Cannot proceed without model.")
            sys.exit(1)

    # Load model
    get_llm()

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

        if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
            print_sys("NEXA offline. Goodbye."); break
        elif user_input.lower() == "/new":
            session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            context = []; print_ok("New conversation."); continue
        elif user_input.lower() == "/clear":
            clear_session(session_id); context = []; print_ok("Cleared."); continue
        elif user_input.lower() == "/history":
            history = get_history(session_id)
            print(f"\n{MAG}{B}📜 History{R}\n")
            for role, content, ts in history:
                color = BLU if role == "user" else GRN
                print(f"  {color}{B}{role.upper()}{R} {D}[{ts}]{R}\n  {content[:200]}{'...' if len(content)>200 else ''}\n")
            continue
        elif user_input.lower() == "/skills":
            skills = load_skills()
            print(f"\n{MAG}{B}🔧 Skills{R}\n")
            if not skills: print_sys("No skills. Use 'learn skill <desc>' to teach.")
            else:
                for name, code, desc in skills:
                    print(f"  {CYN}•{R} {name} {D}- {desc or 'No desc'}{R}")
            print(); continue
        elif user_input.lower() == "/help":
            print(f"""
{MAG}{B}NEXA Commands:{R}
  /new /history /clear /skills /help /exit

{MAG}{B}Tools:{R}
  search <query>     Web search
  ! <cmd>            Shell command
  download <url>     Direct download
  learn <url/file>   Ingest knowledge
  skill <name>       Run saved skill
  learn skill <desc> Teach new skill

{MAG}{B}Usage:{R}
  nexa / n
""")
            continue

        tool_type, *tool_args = detect_tool(user_input)

        if tool_type == "search":
            query = tool_args[0]
            print_sys(f"Searching: {query}")
            spin_start("Searching")
            results = web_search(query)
            spin_stop()
            print(f"\n{YLW}{B}🔍 Results:{R}\n{results}\n")
            save_msg("user", f"[search] {query}", session_id)
            save_msg("assistant", results, session_id)
            continue

        elif tool_type == "shell":
            cmd = tool_args[0]
            print_sys(f"Running: {cmd}")
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
                spin_stop(); print_err("Source not found."); continue
            if text.startswith("Error"):
                spin_stop(); print_err(text); continue
            add_knowledge(source, text)
            spin_stop()
            print_ok(f"Learned {len(text)} chars from {source}")
            save_msg("user", f"[learn] {source}", session_id)
            save_msg("assistant", f"Learned {len(text)} chars", session_id)
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

        # Normal chat
        save_msg("user", user_input, session_id)
        response = reason_and_answer(user_input, context, use_reasoning=True)

        if response and not response.startswith("❌"):
            print_ai(response)
            save_msg("assistant", response, session_id)
            context = load_ctx(session_id, 20)
        else:
            print_err(response or "No response.")

    try: readline.write_history_file(HISTORY_FILE)
    except: pass
    print()

if __name__ == "__main__":
    main()
