#!/usr/bin/env python3
"""
NEXA FULL v3 — Modular Self-Hosted AI Engine
Ollama-based | Tools | RAG | Memory | Web Search | Shell Safety | Reasoning
"""

import os, sys, sqlite3, json, signal, readline, time, shutil, threading, subprocess, re, hashlib, math, textwrap, traceback, logging, random
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote_plus, urlparse
from pathlib import Path

# ─── CONFIG ───
BASE_DIR = Path("/opt/nexa")
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "brain.db"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = LOGS_DIR / "nexa.log"
HISTORY_FILE = Path.home() / ".nexa_history"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("NEXA_MODEL", "qwen2.5:7b")
REASONING_MODEL = os.environ.get("NEXA_REASONING", "deepseek-r1:7b")
MAX_CONTEXT = 12
N_CTX = 8192

# Colors
R, B, D = "\033[0m", "\033[1m", "\033[2m"
RED, GRN, YLW, BLU, MAG, CYN, WHT = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m", "\033[97m"

# ─── LOGGING ───
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("nexa")

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

# ─── CONFIG MODULE ───
class Config:
    DEFAULTS = {
        "model": DEFAULT_MODEL,
        "reasoning_model": REASONING_MODEL,
        "temperature": 0.6,
        "max_tokens": 2048,
        "context_size": N_CTX,
        "web_search_enabled": True,
        "web_search_provider": "duckduckgo",
        "shell_allowlist": ["ls", "df", "free", "uptime", "uname", "ps", "du", "cat", "head", "tail", "wc", "grep", "find", "pwd", "whoami", "id", "systemctl", "journalctl", "netstat", "ss", "ping", "curl", "wget"],
        "shell_blocklist": ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "halt", "init 0", "fdisk", "parted"],
        "dangerous_requires_confirm": True,
        "bind_host": "127.0.0.1",
        "log_level": "INFO"
    }

    @classmethod
    def load(cls):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f: return {**cls.DEFAULTS, **json.load(f)}
            except: pass
        return dict(cls.DEFAULTS)

    @classmethod
    def save(cls, cfg):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f: json.dump(cfg, f, indent=2)

# ─── DB MODULE ───
class Database:
    @staticmethod
    def init():
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, session_id TEXT DEFAULT 'default',
            role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, title TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY, source TEXT, chunk TEXT,
            embedding TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY, path TEXT, name TEXT, size INTEGER,
            chunks INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit(); conn.close()

    @staticmethod
    def execute(query, params=(), fetch=False):
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute(query, params)
        result = c.fetchall() if fetch else None
        conn.commit(); conn.close()
        return result

# ─── MEMORY MODULE ───
class Memory:
    @staticmethod
    def save_msg(role, content, sid="default"):
        Database.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (sid, role, content))
        Database.execute("""INSERT INTO sessions (session_id, title, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP""", (sid, content[:60]))

    @staticmethod
    def load_ctx(sid="default", limit=MAX_CONTEXT):
        rows = Database.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (sid, limit), fetch=True)
        return [{"role": r, "content": c} for r, c in reversed(rows)] if rows else []

    @staticmethod
    def list_sessions():
        return Database.execute("SELECT session_id, title, updated_at FROM sessions ORDER BY updated_at DESC", fetch=True) or []

    @staticmethod
    def clear_session(sid="default"):
        Database.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        Database.execute("DELETE FROM sessions WHERE session_id=?", (sid,))

    @staticmethod
    def get_history(sid="default"):
        return Database.execute("SELECT role, content, timestamp FROM messages WHERE session_id=? ORDER BY id", (sid,), fetch=True) or []

    @staticmethod
    def remember(key, value):
        Database.execute("INSERT OR REPLACE INTO memories (key, value) VALUES (?, ?)", (key, value))

    @staticmethod
    def recall(key):
        rows = Database.execute("SELECT value FROM memories WHERE key=?", (key,), fetch=True)
        return rows[0][0] if rows else None

    @staticmethod
    def list_memories():
        return Database.execute("SELECT key, value, timestamp FROM memories ORDER BY timestamp DESC", fetch=True) or []

    @staticmethod
    def forget(key):
        Database.execute("DELETE FROM memories WHERE key=?", (key,))

    @staticmethod
    def clear_memories():
        Database.execute("DELETE FROM memories")

# ─── RAG / KNOWLEDGE MODULE ───
class RAG:
    @staticmethod
    def simple_embed(text):
        text = text.lower()
        vec = [0.0]*128
        for word in re.findall(r"\b\w+\b", text):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % 128] += 1.0
        norm = sum(x*x for x in vec)**0.5 or 1.0
        return [x/norm for x in vec]

    @staticmethod
    def cosine_sim(a, b):
        return sum(x*y for x, y in zip(a, b))

    @classmethod
    def add_document(cls, source, text):
        chunks = [text[i:i+600] for i in range(0, len(text), 600)]
        for chunk in chunks:
            emb = json.dumps(cls.simple_embed(chunk))
            Database.execute("INSERT INTO knowledge (source, chunk, embedding) VALUES (?, ?, ?)", (source, chunk, emb))
        Database.execute("INSERT OR REPLACE INTO documents (path, name, size, chunks) VALUES (?, ?, ?, ?)",
            (source, Path(source).name, len(text), len(chunks)))
        return len(chunks)

    @classmethod
    def search(cls, query, top_k=5):
        q_emb = cls.simple_embed(query)
        rows = Database.execute("SELECT source, chunk, embedding FROM knowledge", fetch=True)
        if not rows: return []
        scored = []
        for source, chunk, emb_json in rows:
            try:
                emb = json.loads(emb_json)
                score = cls.cosine_sim(q_emb, emb)
                scored.append((score, source, chunk))
            except: continue
        scored.sort(reverse=True)
        return scored[:top_k]

    @staticmethod
    def list_docs():
        return Database.execute("SELECT name, size, chunks, timestamp FROM documents ORDER BY timestamp DESC", fetch=True) or []

    @staticmethod
    def read_file(path):
        p = Path(path)
        if not p.exists(): return f"❌ File not found: {path}"
        try:
            suffix = p.suffix.lower()
            if suffix == ".pdf":
                try:
                    import PyPDF2
                    with open(p, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        return "\n".join(page.extract_text() or "" for page in reader.pages)
                except ImportError:
                    return "❌ PyPDF2 not installed. Run: pip install PyPDF2"
            elif suffix in [".txt", ".md", ".json", ".csv", ".py", ".sh", ".log"]:
                return p.read_text(errors="ignore")
            else:
                return p.read_text(errors="ignore")[:50000]
        except Exception as e:
            return f"❌ Error reading file: {e}"

# ─── LLM MODULE ───
class LLM:
    @staticmethod
    def check_ollama():
        try:
            req = Request(f"{OLLAMA_HOST}/api/tags", method="GET")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return True, [m["name"] for m in data.get("models", [])]
        except Exception as e:
            return False, str(e)

    @staticmethod
    def check_model(models, name):
        for m in models:
            if name in m or m.startswith(name.split(":")[0]): return True
        return False

    @classmethod
    def chat(cls, messages, model=None, stream=False, temperature=0.6, max_tokens=2048):
        cfg = Config.load()
        model = model or cfg.get("model", DEFAULT_MODEL)
        payload = {
            "model": model, "messages": messages, "stream": stream,
            "options": {"num_ctx": cfg.get("context_size", N_CTX), "temperature": temperature, "max_tokens": max_tokens}
        }
        req = Request(f"{OLLAMA_HOST}/api/chat", data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=120) as resp:
                full = ""
                for line in resp:
                    line = line.decode().strip()
                    if not line: continue
                    try:
                        chunk = json.loads(line)
                        if "message" in chunk and "content" in chunk["message"]:
                            text = chunk["message"]["content"]
                            full += text
                            if stream:
                                sys.stdout.write(text); sys.stdout.flush()
                        if chunk.get("done"): break
                    except: continue
                if stream: sys.stdout.write("\n"); sys.stdout.flush()
                return full
        except Exception as e:
            log.error(f"LLM error: {e}")
            return f"❌ LLM error: {e}"

    @classmethod
    def generate(cls, prompt, model=None, temperature=0.6, max_tokens=1024):
        cfg = Config.load()
        model = model or cfg.get("model", DEFAULT_MODEL)
        payload = {"model": model, "prompt": prompt, "stream": False,
                   "options": {"temperature": temperature, "max_tokens": max_tokens}}
        req = Request(f"{OLLAMA_HOST}/api/generate", data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return data.get("response", "")
        except Exception as e:
            return f"❌ Generate error: {e}"

# ─── REASONING MODULE ───
class Reasoning:
    @classmethod
    def needs_reasoning(cls, text):
        triggers = ["why", "how", "explain", "solve", "calculate", "logic", "riddle", "which", "if", "compare", "difference", "what is the", "determine", "find the", "prove", "optimize"]
        return any(t in text.lower() for t in triggers) or len(text) > 80

    @classmethod
    def reason_and_answer(cls, user_msg, context, cfg):
        model = cfg.get("model", DEFAULT_MODEL)
        r1_model = cfg.get("reasoning_model", REASONING_MODEL)

        ok, models = LLM.check_ollama()
        if not ok: return "❌ Ollama not running."
        if not LLM.check_model(models, model): return f"❌ Model '{model}' not found. Run: ollama pull {model}"

        sys_msg = {"role": "system", "content": "You are NEXA, an advanced AI assistant. Be concise, accurate, and helpful."}

        # RAG context
        rag_results = RAG.search(user_msg)
        rag_text = ""
        if rag_results:
            rag_text = "\n\nRelevant knowledge:\n" + "\n".join([f"[{s}]: {c[:400]}" for _, s, c in rag_results])

        # Memory context
        mem = Memory.recall("user_preference")
        mem_text = f"\n\nUser preference: {mem}" if mem else ""

        if cls.needs_reasoning(user_msg) and LLM.check_model(models, r1_model):
            spin_start("Reasoning")
            think_msgs = [
                {"role": "system", "content": "Think step by step deeply. Put detailed reasoning inside   tags. After  , give only the final concise answer."},
                {"role": "user", "content": user_msg + rag_text + mem_text}
            ]
            think_msgs.extend(context[-5:])
            raw = LLM.chat(think_msgs, model=r1_model, stream=False, temperature=0.4, max_tokens=2048)
            spin_stop()

            if raw.startswith("❌"): return raw

            think_match = re.search(r'  (.*?)  ', raw, re.DOTALL)
            thinking = think_match.group(1).strip() if think_match else ""
            final = re.sub(r'  .*?  ', '', raw, flags=re.DOTALL).strip()

            if thinking:
                RAG.add_document("reasoning_session", thinking)

            if len(final) < 40 and thinking:
                spin_start("Synthesizing")
                syn_msgs = [sys_msg, {"role": "system", "content": f"Based on this reasoning, give clear final answer:\n{thinking[:1500]}"},
                            {"role": "user", "content": user_msg}]
                final = LLM.chat(syn_msgs, stream=False, temperature=0.5)
                spin_stop()

            # Add reasoning summary
            if thinking:
                summary = thinking[:200].replace("\n", " ")
                return f"{final}\n\n{D}💡 Reasoning: {summary}...{R}" if len(thinking) > 200 else final
            return final
        else:
            spin_start("Thinking")
            msgs = [sys_msg, {"role": "user", "content": user_msg + rag_text + mem_text}]
            msgs.extend(context[-8:])
            resp = LLM.chat(msgs, stream=False, temperature=cfg.get("temperature", 0.6))
            spin_stop()
            return resp

# ─── WEB TOOLS MODULE ───
class WebTools:
    @staticmethod
    def search(query, max_results=5):
        try:
            url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            results = []
            for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)">([^<]+)</a>', html):
                link, title = m.group(1), re.sub(r'<[^>]+>', '', m.group(2))
                if link.startswith("http") and len(results) < max_results:
                    results.append(f"• {title}\n  → {link}")
            return "\n\n".join(results) if results else "No results found."
        except Exception as e:
            log.error(f"Web search error: {e}")
            return f"❌ Search error: {e}"

    @staticmethod
    def fetch_url(url, max_chars=8000):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]
        except Exception as e:
            return f"❌ Fetch error: {e}"

# ─── SHELL TOOLS MODULE ───
class ShellTools:
    DANGEROUS = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "halt", "init 0", "fdisk", "parted", "mkfs.ext", "mkfs.xfs"]

    @classmethod
    def is_safe(cls, cmd):
        for d in cls.DANGEROUS:
            if d in cmd.lower(): return False, f"Blocked: {d}"
        return True, "OK"

    @classmethod
    def run(cls, cmd, timeout=30):
        safe, reason = cls.is_safe(cmd)
        if not safe:
            return f"❌ {reason}"
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            out = result.stdout.strip() or "(no output)"
            if result.returncode != 0 and result.stderr.strip():
                return f"Exit {result.returncode}\n{out}\nSTDERR:\n{result.stderr.strip()[:500]}"
            return out[:3000]
        except subprocess.TimeoutExpired:
            return "⏱ Timed out."
        except Exception as e:
            return f"❌ Error: {e}"

# ─── SYSTEM TOOLS MODULE ───
class SystemTools:
    @staticmethod
    def info():
        try:
            ram = subprocess.run(["free", "-h"], capture_output=True, text=True).stdout.strip()
            disk = subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout.strip()
            cpu = subprocess.run(["cat", "/proc/loadavg"], capture_output=True, text=True).stdout.strip()
            uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True).stdout.strip()
            return f"RAM:\n{ram}\n\nDisk:\n{disk}\n\nLoad: {cpu}\n\nUptime: {uptime}"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def status():
        ok, models = LLM.check_ollama()
        ollama_status = "✅ Running" if ok else "❌ Down"
        model_list = ", ".join(models[:5]) if ok else "None"

        sessions = len(Memory.list_sessions())
        memories = len(Memory.list_memories())
        docs = len(RAG.list_docs())

        db_size = DB_PATH.stat().st_size / (1024*1024) if DB_PATH.exists() else 0

        return f"""{CYN}{B}NEXA Status{R}
Ollama: {ollama_status}
Models: {model_list}
Sessions: {sessions}
Memories: {memories}
Documents: {docs}
DB Size: {db_size:.1f} MB
Config: {CONFIG_PATH}
Logs: {LOG_PATH}"""

# ─── DOCTOR MODULE ───
class Doctor:
    TESTS = [
        ("Python", lambda: (sys.version_info >= (3, 8), sys.version)),
        ("Ollama", lambda: LLM.check_ollama()[0]),
        ("Model", lambda: LLM.check_model(LLM.check_ollama()[1], Config.load().get("model", DEFAULT_MODEL))),
        ("SQLite", lambda: (True, sqlite3.sqlite_version)),
        ("Disk", lambda: (shutil.disk_usage("/").free > 1_000_000_000, f"{shutil.disk_usage('/').free//(1024**3)}GB free")),
        ("RAM", lambda: (True, f"Available (check with /status)")),
        ("Config", lambda: CONFIG_PATH.exists()),
        ("Database", lambda: DB_PATH.exists()),
    ]

    @classmethod
    def run(cls):
        print(f"\n{MAG}{B}🔬 NEXA Doctor{R}\n")
        passed = 0
        for name, test in cls.TESTS:
            try:
                result = test()
                if isinstance(result, tuple):
                    ok, detail = result
                else:
                    ok, detail = result, "OK"
                status = f"{GRN}PASS{R}" if ok else f"{RED}FAIL{R}"
                print(f"  {status} {name:<12} {D}{detail}{R}")
                if ok: passed += 1
            except Exception as e:
                print(f"  {RED}FAIL{R} {name:<12} {D}{e}{R}")

        print(f"\n{passed}/{len(cls.TESTS)} tests passed.")

        # Run reasoning test
        print(f"\n{YLW}{B}🧠 Reasoning Test{R}")
        test_q = "A bat and ball cost $1.10 total. The bat costs $1 more than the ball. How much does the ball cost?"
        spin_start("Testing reasoning")
        ans = Reasoning.reason_and_answer(test_q, [], Config.load())
        spin_stop()
        if "0.05" in ans or "5 cent" in ans.lower():
            print(f"  {GRN}PASS{R} Reasoning: Correct answer detected")
        else:
            print(f"  {YLW}WARN{R} Reasoning: Answer may need verification")
            print(f"  {D}Response: {ans[:100]}...{R}")

        # Memory test
        print(f"\n{YLW}{B}📝 Memory Test{R}")
        Memory.remember("doctor_test", "NEXA_v3_working")
        recalled = Memory.recall("doctor_test")
        if recalled == "NEXA_v3_working":
            print(f"  {GRN}PASS{R} Memory: Store and recall working")
        else:
            print(f"  {RED}FAIL{R} Memory: Recall failed")

        print()

# ─── UI MODULE ───
class UI:
    @staticmethod
    def banner():
        cols = shutil.get_terminal_size().columns
        w = min(50, cols - 4)
        cfg = Config.load()
        ok, models = LLM.check_ollama()
        model_name = cfg.get("model", DEFAULT_MODEL).split("/")[-1][:18]

        print(f"\n{MAG}{B}", end="")
        print("╭" + "━" * w + "╮")
        t = "     NEXA LOCAL AI     "
        p = (w - len(t)) // 2
        print("┃" + " " * p + CYN + B + t + MAG + B + " " * (w - p - len(t)) + "┃")
        print("┣" + "━" * w + "┫")

        lines = [
            f"  Model: {model_name}",
            f"  Tools: ON    Memory: ON",
            f"  Web: READY   RAG: READY",
        ]
        for line in lines:
            p2 = (w - len(line)) // 2
            print("┃" + " " * p2 + D + line + R + MAG + B + " " * (w - p2 - len(line)) + "┃")
        print("╰" + "━" * w + "╯")
        print(f"{R}")
        print(f"{D}Commands: /new /history /clear /memory /status /doctor /help /exit{R}")
        print(f"{D}Tools: search <q> | ! <cmd> | add <file> | recall <key>{R}\n")

    @staticmethod
    def print_ai(text):
        text = re.sub(r'  .*?  ', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'</?think>', '', text)
        print(f"{GRN}{B}NEXA:{R} {text}")

    @staticmethod
    def print_sys(t, c=D): print(f"{c}{D}▸ {t}{R}")
    @staticmethod
    def print_err(t): print(f"{RED}✖ {t}{R}")
    @staticmethod
    def print_ok(t): print(f"{GRN}✔ {t}{R}")

# ─── TOOL PARSER ───
class ToolParser:
    @staticmethod
    def detect(user_input):
        ui = user_input.lower().strip()

        if ui.startswith("search ") or ui.startswith("find ") or ui.startswith("google "):
            return "search", user_input.split(" ", 1)[1] if " " in user_input else ""

        if ui.startswith("! ") or ui.startswith("run ") or ui.startswith("shell ") or ui.startswith("exec "):
            return "shell", user_input.split(" ", 1)[1] if " " in user_input else ""

        if ui.startswith("fetch ") or ui.startswith("get "):
            return "fetch", user_input.split(" ", 1)[1] if " " in user_input else ""

        if ui.startswith("add ") or ui.startswith("ingest "):
            return "add", user_input.split(" ", 1)[1] if " " in user_input else ""

        if ui.startswith("recall ") or ui.startswith("remember "):
            parts = user_input.split(" ", 2)
            if len(parts) >= 2:
                return "recall", parts[1], parts[2] if len(parts) > 2 else ""

        if ui.startswith("forget "):
            return "forget", user_input.split(" ", 1)[1] if " " in user_input else ""

        return "chat", user_input

# ─── MAIN ───
def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    Database.init()
    cfg = Config.load()

    # CLI args
    if "--doctor" in sys.argv:
        Doctor.run(); return
    if "--setup" in sys.argv:
        print(f"{BLU}{B}🔧 NEXA Setup{R}\n")
        print("Current config:")
        for k, v in cfg.items():
            if "key" not in k.lower():
                print(f"  {k}: {v}")
        print(f"\nEdit {CONFIG_PATH} to change settings.")
        return
    if "--status" in sys.argv:
        print(SystemTools.status()); return
    if "--model" in sys.argv:
        ok, models = LLM.check_ollama()
        print(f"{CYN}{B}Installed Models:{R}")
        for m in models: print(f"  • {m}")
        print(f"\nActive: {cfg.get('model', DEFAULT_MODEL)}")
        return

    session_id = "default"
    if "--new" in sys.argv:
        session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    elif "--history" in sys.argv:
        sessions = Memory.list_sessions()
        print(f"\n{MAG}{B}📜 Sessions{R}\n")
        for sid, title, updated in sessions:
            print(f"  {CYN}•{R} {sid:<28} {D}({updated}){R}")
        print(); return
    elif "--clear" in sys.argv:
        Memory.clear_session(); UI.print_ok("Cleared."); return

    # Check Ollama
    UI.print_sys("Checking Ollama...")
    ok, models = LLM.check_ollama()
    if not ok:
        UI.print_err(f"Ollama not running at {OLLAMA_HOST}")
        UI.print_sys("Install: curl -fsSL https://ollama.com/install.sh | sh")
        UI.print_sys("Start: sudo systemctl start ollama")
        return

    if not LLM.check_model(models, cfg.get("model", DEFAULT_MODEL)):
        UI.print_err(f"Model '{cfg.get('model', DEFAULT_MODEL)}' not found.")
        UI.print_sys(f"Pull: ollama pull {cfg.get('model', DEFAULT_MODEL)}")
        return

    UI.print_ok(f"Ollama ready. Model: {cfg.get('model', DEFAULT_MODEL)}")
    if LLM.check_model(models, cfg.get("reasoning_model", REASONING_MODEL)):
        UI.print_ok(f"Reasoning: {cfg.get('reasoning_model', REASONING_MODEL)}")
    time.sleep(0.2)

    UI.banner()

    context = Memory.load_ctx(session_id)
    if context: UI.print_sys(f"Loaded {len(context)} messages from memory.")

    try: readline.read_history_file(str(HISTORY_FILE))
    except FileNotFoundError: pass

    while True:
        try:
            user_input = input(f"{BLU}{B}You{R} {D}❯{R} ").strip()
        except EOFError: break
        if not user_input: continue

        # Built-in commands
        if user_input.lower() in ["/exit", "/quit", "exit", "quit"]:
            UI.print_sys("NEXA offline. Goodbye."); break
        elif user_input.lower() == "/new":
            session_id = f"nexa_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            context = []; UI.print_ok("New conversation."); continue
        elif user_input.lower() == "/clear":
            Memory.clear_session(session_id); context = []; UI.print_ok("Cleared."); continue
        elif user_input.lower() == "/history":
            history = Memory.get_history(session_id)
            print(f"\n{MAG}{B}📜 History{R}\n")
            for role, content, ts in history:
                color = BLU if role == "user" else GRN
                print(f"  {color}{B}{role.upper()}{R} {D}[{ts}]{R}\n  {content[:200]}{'...' if len(content)>200 else ''}\n")
            continue
        elif user_input.lower() == "/memory":
            memories = Memory.list_memories()
            print(f"\n{MAG}{B}🧠 Memories{R}\n")
            if not memories: UI.print_sys("No memories stored. Use 'remember <key> <value>' to add."); print(); continue
            for key, value, ts in memories:
                print(f"  {CYN}•{R} {key} = {value[:50]} {D}({ts}){R}")
            print(); continue
        elif user_input.lower() == "/forget":
            memories = Memory.list_memories()
            if not memories: UI.print_sys("No memories to forget."); continue
            print(f"\n{MAG}{B}🗑 Select memory to forget:{R}")
            for i, (key, val, _) in enumerate(memories[:10], 1):
                print(f"  {i}. {key} = {val[:40]}...")
            choice = input(f"\n{D}Enter number or 'all': {R}").strip()
            if choice.lower() == "all":
                Memory.clear_memories(); UI.print_ok("All memories cleared."); continue
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(memories):
                    Memory.forget(memories[idx][0])
                    UI.print_ok(f"Forgot: {memories[idx][0]}")
            except: UI.print_err("Invalid choice."); continue
            continue
        elif user_input.lower() == "/status":
            print(f"\n{SystemTools.status()}\n"); continue
        elif user_input.lower() == "/doctor":
            Doctor.run(); continue
        elif user_input.lower() == "/help":
            print(f"""
{MAG}{B}NEXA Commands:{R}
  /new       New conversation
  /history   Session history
  /clear     Clear session
  /memory    Show stored memories
  /forget    Delete memory
  /status    System status
  /doctor    Run diagnostics
  /help      This help
  /exit      Quit

{MAG}{B}Tools:{R}
  search <query>        Web search
  ! <command>           Run shell command
  fetch <url>           Fetch webpage text
  add <file>            Add file to knowledge base
  remember <key> <val>  Store memory
  recall <key>          Retrieve memory

{MAG}{B}CLI:{R}
  nexa --new       Fresh conversation
  nexa --history   List sessions
  nexa --status    Show status
  nexa --doctor    Run tests
  nexa --model     List models
  n                Same as nexa
""")
            continue

        # Tool detection
        tool_type, *tool_args = ToolParser.detect(user_input)

        if tool_type == "search":
            query = tool_args[0]
            UI.print_sys(f"Searching web: {query}")
            spin_start("Searching")
            results = WebTools.search(query)
            spin_stop()
            print(f"\n{YLW}{B}🔍 Results:{R}\n{results}\n")
            Memory.save_msg("user", f"[search] {query}", session_id)
            Memory.save_msg("assistant", results, session_id)
            continue

        elif tool_type == "shell":
            cmd = tool_args[0]
            UI.print_sys(f"Executing: {cmd}")
            spin_start("Executing")
            result = ShellTools.run(cmd)
            spin_stop()
            print(f"\n{CYN}{B}📟 Output:{R}\n{result}\n")
            Memory.save_msg("user", f"[shell] {cmd}", session_id)
            Memory.save_msg("assistant", result, session_id)
            continue

        elif tool_type == "fetch":
            url = tool_args[0]
            UI.print_sys(f"Fetching: {url}")
            spin_start("Fetching")
            text = WebTools.fetch_url(url)
            spin_stop()
            print(f"\n{BLU}{B}📄 Content:{R}\n{text[:1500]}{'...' if len(text)>1500 else ''}\n")
            Memory.save_msg("user", f"[fetch] {url}", session_id)
            Memory.save_msg("assistant", text[:1000], session_id)
            continue

        elif tool_type == "add":
            path = tool_args[0]
            UI.print_sys(f"Adding to knowledge: {path}")
            spin_start("Processing")
            text = RAG.read_file(path)
            spin_stop()
            if text.startswith("❌"):
                UI.print_err(text); continue
            chunks = RAG.add_document(path, text)
            UI.print_ok(f"Added {chunks} chunks from {path}")
            Memory.save_msg("user", f"[add] {path}", session_id)
            Memory.save_msg("assistant", f"Added {chunks} chunks", session_id)
            continue

        elif tool_type == "recall":
            key = tool_args[0]
            val = Memory.recall(key)
            if val:
                print(f"\n{CYN}{B}🧠 Memory:{R} {key} = {val}\n")
            else:
                UI.print_err(f"No memory found for: {key}")
            continue

        elif tool_type == "forget":
            key = tool_args[0]
            Memory.forget(key)
            UI.print_ok(f"Forgot: {key}")
            continue

        # Normal chat
        Memory.save_msg("user", user_input, session_id)
        response = Reasoning.reason_and_answer(user_input, context, cfg)

        if response and not response.startswith("❌"):
            UI.print_ai(response)
            Memory.save_msg("assistant", response, session_id)
            context = Memory.load_ctx(session_id, MAX_CONTEXT)
        else:
            UI.print_err(response or "No response.")

    try: readline.write_history_file(str(HISTORY_FILE))
    except: pass
    print()

if __name__ == "__main__":
    main()
