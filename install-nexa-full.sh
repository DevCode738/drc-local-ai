#!/bin/bash
set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA FULL v3 — Modular AI Engine"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash install-nexa-full.sh" && exit 1

NEXA_DIR="/opt/nexa"
mkdir -p "$NEXA_DIR"/{config,data,knowledge,logs,bin}

# ─── STEP 1: INSPECT ───
echo ""
echo "📋 STEP 1: VPS Inspection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

RAM_MB=$(free -m | awk '/^Mem:/ {print $2}')
RAM_GB=$(awk "BEGIN {printf \"%.1f\", $RAM_MB/1024}")
CPU_CORES=$(nproc)
DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')

echo "  RAM: ${RAM_GB}GB | Cores: $CPU_CORES | Disk Free: $DISK_FREE"

if command -v ollama &>/dev/null; then
    echo "  Ollama: $(ollama --version 2>/dev/null || echo 'installed')"
    echo "  Models:"
    ollama list 2>/dev/null | head -10 || echo "    (none or Ollama not running)"
else
    echo "  Ollama: Not installed"
fi

# Model selection
if [ "$RAM_MB" -gt 14000 ]; then
    MODEL="qwen2.5:14b"
    R1="deepseek-r1:14b"
elif [ "$RAM_MB" -gt 9000 ]; then
    MODEL="qwen2.5:7b"
    R1="deepseek-r1:7b"
else
    MODEL="qwen2.5:3b"
    R1="deepseek-r1:1.5b"
fi

echo ""
echo "  Selected Model: $MODEL"
echo "  Reasoning: $R1"
read -p "  Press Enter to continue or type custom model: " USER_MODEL
[ -n "$USER_MODEL" ] && MODEL="$USER_MODEL"

# ─── STEP 2: INSTALL OLLAMA ───
echo ""
echo "🦙 STEP 2: Ollama"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command -v ollama &>/dev/null; then
    echo "⬇️ Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama installed"
else
    echo "✅ Ollama already installed"
fi

# ─── STEP 3: SYSTEMD ───
echo ""
echo "⚙️  STEP 3: Systemd Service"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

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

id -u ollama &>/dev/null || useradd -r -g ollama -s /bin/false -m -d /usr/share/ollama ollama 2>/dev/null || useradd -r -s /bin/false -m -d /usr/share/ollama ollama
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "⏳ Waiting for Ollama..."
for i in {1..30}; do
    curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
done

if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ Ollama running"
else
    echo "⚠️ Ollama may need manual start: sudo systemctl start ollama"
fi

# ─── STEP 4: PULL MODELS ───
echo ""
echo "🧠 STEP 4: Pulling Models"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⬇️ This takes 10-20 minutes depending on speed..."

ollama pull "$MODEL"
[ -n "$R1" ] && ollama pull "$R1"

echo "✅ Models ready"

# ─── STEP 5: DEPLOY NEXA ───
echo ""
echo "🚀 STEP 5: Deploying NEXA"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-full.py -o "$NEXA_DIR/app/nexa-full.py"
chmod +x "$NEXA_DIR/app/nexa-full.py"

# Config
cat > "$NEXA_DIR/config/config.json" << EOF
{
  "model": "$MODEL",
  "reasoning_model": "$R1",
  "temperature": 0.6,
  "max_tokens": 2048,
  "context_size": 8192,
  "web_search_enabled": true,
  "web_search_provider": "duckduckgo",
  "shell_allowlist": ["ls", "df", "free", "uptime", "uname", "ps", "du", "cat", "head", "tail", "wc", "grep", "find", "pwd", "whoami", "id", "systemctl", "journalctl", "netstat", "ss", "ping", "curl", "wget"],
  "shell_blocklist": ["rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:", "> /dev/sda", "shutdown", "reboot", "poweroff", "halt", "init 0"],
  "dangerous_requires_confirm": true,
  "bind_host": "127.0.0.1",
  "log_level": "INFO"
}
EOF

# Wrappers
cat > "$NEXA_DIR/bin/nexa" << 'EOF'
#!/bin/bash
export NEXA_MODEL="${NEXA_MODEL:-qwen2.5:7b}"
export NEXA_REASONING="${NEXA_REASONING:-deepseek-r1:7b}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
python3 /opt/nexa/app/nexa-full.py "$@"
EOF
chmod +x "$NEXA_DIR/bin/nexa"
cp "$NEXA_DIR/bin/nexa" "$NEXA_DIR/bin/n"
chmod +x "$NEXA_DIR/bin/n"
ln -sf "$NEXA_DIR/bin/nexa" /usr/local/bin/nexa
ln -sf "$NEXA_DIR/bin/n" /usr/local/bin/n

# ─── STEP 6: TEST ───
echo ""
echo "🧪 STEP 6: Testing"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 "$NEXA_DIR/app/nexa-full.py" --doctor 2>/dev/null || echo "⚠️ Doctor test skipped (Ollama may still be loading model)"

# ─── DONE ───
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ NEXA FULL v3 INSTALLED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Start chatting:"
echo "  nexa    or    n"
echo ""
echo "Commands:"
echo "  nexa --new       Fresh conversation"
echo "  nexa --history   List sessions"
echo "  nexa --status    System status"
echo "  nexa --doctor    Run diagnostics"
echo "  nexa --model     List installed models"
echo ""
echo "Inside chat:"
echo "  search <query>     Web search"
echo "  ! <cmd>            Shell command"
echo "  fetch <url>        Fetch webpage"
echo "  add <file>         Add to knowledge"
echo "  remember <k> <v>   Store memory"
echo "  recall <key>       Retrieve memory"
echo ""
echo "  /new /history /clear /memory /forget /status /doctor /help /exit"
echo ""
echo "Model: $MODEL"
echo "Data:  $NEXA_DIR/data/"
echo "Logs:  $NEXA_DIR/logs/"
echo ""
