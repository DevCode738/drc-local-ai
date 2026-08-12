#!/usr/bin/env python3
"""
NEXA CORE — Self-Building AI Engine
No external models. Pure self-improvement.
Runs via nohup, builds itself continuously.
"""

import os, sys, sqlite3, json, time, threading, subprocess, re, hashlib, random
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ─── PATHS ───
BASE = Path("/opt/autonexa")
LOG_DIR = BASE / "logs"
DATA_DIR = BASE / "data"
MODULES_DIR = BASE / "modules"
SOURCES_DIR = BASE / "sources"
BRAIN_DB = DATA_DIR / "brain.db"
BUILD_LOG = LOG_DIR / "build.log"
CHAT_LOG = LOG_DIR / "chat.log"
SOURCES_FILE = BASE / "sources.json"
STATE_FILE = DATA_DIR / "state.json"

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MODULES_DIR, exist_ok=True)
os.makedirs(SOURCES_DIR, exist_ok=True)

# ─── LOGGER ───
class BuildLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.lock = threading.Lock()

    def log(self, phase, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] [{phase}] {message}\n"
        with self.lock:
            with open(self.log_file, "a") as f:
                f.write(line)
            # Also print for nohup capture
            print(line.strip(), flush=True)

    def info(self, phase, msg): self.log(phase, msg, "INFO")
    def warn(self, phase, msg): self.log(phase, msg, "WARN")
    def error(self, phase, msg): self.log(phase, msg, "ERROR")
    def success(self, phase, msg): self.log(phase, msg, "SUCCESS")

log = BuildLogger(BUILD_LOG)

# ─── STATE ───
class State:
    @staticmethod
    def load():
        if STATE_FILE.exists():
            with open(STATE_FILE) as f: return json.load(f)
        return {"phase": "INIT", "progress": 0, "sources_ingested": 0, "modules_built": 0, "tests_passed": 0, "tests_failed": 0, "iterations": 0, "start_time": time.time()}

    @staticmethod
    def save(state):
        with open(STATE_FILE, "w") as f: json.dump(state, f)

# ─── BRAIN DB ───
class Brain:
    def __init__(self):
        self.conn = sqlite3.connect(str(BRAIN_DB), check_same_thread=False)
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY, source TEXT, category TEXT,
            chunk TEXT, keywords TEXT, weight REAL DEFAULT 1.0,
            timestamp REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY, pattern TEXT, response TEXT,
            category TEXT, hits INTEGER DEFAULT 0, timestamp REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS modules (
            id INTEGER PRIMARY KEY, name TEXT, code TEXT,
            status TEXT, tests TEXT, timestamp REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
            content TEXT, timestamp REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY, module TEXT, error TEXT,
            fix TEXT, timestamp REAL)""")
        self.conn.commit()

    def add_knowledge(self, source, category, chunk, keywords=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO knowledge (source, category, chunk, keywords, timestamp) VALUES (?, ?, ?, ?, ?)",
                      (source, category, chunk, keywords, time.time()))
            self.conn.commit()

    def search(self, query, limit=10):
        words = set(re.findall(r"\b\w+\b", query.lower()))
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT source, category, chunk, keywords, weight FROM knowledge")
            rows = c.fetchall()
        scored = []
        for source, cat, chunk, kw, weight in rows:
            kw_set = set((kw or "").lower().split())
            chunk_words = set(re.findall(r"\b\w+\b", chunk.lower()))
            score = len(words & chunk_words) * 2 + len(words & kw_set) * 3
            if score > 0:
                scored.append((score * (weight or 1), source, cat, chunk))
        scored.sort(reverse=True)
        return scored[:limit]

    def add_pattern(self, pattern, response, category="general"):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO patterns (pattern, response, category, timestamp) VALUES (?, ?, ?, ?)",
                      (pattern, response, category, time.time()))
            self.conn.commit()

    def find_pattern(self, query):
        words = set(re.findall(r"\b\w+\b", query.lower()))
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT pattern, response, hits FROM patterns")
            rows = c.fetchall()
        best = None
        best_score = 0
        for pat, resp, hits in rows:
            pat_words = set(re.findall(r"\b\w+\b", pat.lower()))
            score = len(words & pat_words) * (1 + (hits or 0) * 0.1)
            if score > best_score:
                best_score = score
                best = (pat, resp, hits)
        if best and best_score >= 1:
            with self.lock:
                c = self.conn.cursor()
                c.execute("UPDATE patterns SET hits = hits + 1 WHERE pattern = ?", (best[0],))
                self.conn.commit()
            return best[1]
        return None

    def save_module(self, name, code, status="draft", tests=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO modules (name, code, status, tests, timestamp) VALUES (?, ?, ?, ?, ?)",
                      (name, code, status, tests, time.time()))
            self.conn.commit()

    def get_module(self, name):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT code, status FROM modules WHERE name = ?", (name,))
            row = c.fetchone()
            return row if row else (None, None)

    def save_conversation(self, session_id, role, content):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO conversations (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                      (session_id, role, content, time.time()))
            self.conn.commit()

    def get_context(self, session_id, limit=15):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                      (session_id, limit))
            rows = c.fetchall()
        return [(r, c) for r, c in reversed(rows)]

brain = Brain()

# ─── SOURCE FETCHER ───
class SourceFetcher:
    def __init__(self):
        self.sources = self._load_sources()

    def _load_sources(self):
        if SOURCES_FILE.exists():
            with open(SOURCES_FILE) as f: return json.load(f)
        return {"knowledge_sources": [], "datasets": [], "code_repos": []}

    def fetch_text(self, url, max_size=50000):
        try:
            req = Request(url, headers={"User-Agent": "NEXA-Builder/1.0"})
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > max_size:
                    data = data[:max_size]
                return data.decode("utf-8", errors="ignore")
        except Exception as e:
            log.error("FETCH", f"Failed {url}: {e}")
            return None

    def ingest_source(self, source):
        name = source.get("name", "unknown")
        url = source.get("url", "")
        log.info("INGEST", f"Fetching: {name}")

        text = self.fetch_text(url)
        if not text:
            return 0

        # Clean text
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Chunk and store
        chunks = [text[i:i+800] for i in range(0, len(text), 800)]
        category = source.get("type", "general")

        for i, chunk in enumerate(chunks):
            if len(chunk) < 50: continue
            keywords = " ".join(sorted(set(re.findall(r"\b\w{4,}\b", chunk.lower()))))[:200]
            brain.add_knowledge(name, category, chunk, keywords)

        log.success("INGEST", f"Stored {len(chunks)} chunks from {name}")
        return len(chunks)

    def run_ingestion(self):
        total = 0
        all_sources = self.sources.get("knowledge_sources", []) + self.sources.get("code_repos", [])
        log.info("INGEST", f"Starting ingestion of {len(all_sources)} sources")

        for source in all_sources:
            chunks = self.ingest_source(source)
            total += chunks
            time.sleep(2)  # Be nice to servers

        log.success("INGEST", f"Total chunks ingested: {total}")
        return total

# ─── CODE BUILDER ───
class CodeBuilder:
    MODULE_TEMPLATES = {
        "calculator": 