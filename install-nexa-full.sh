#!/bin/bash
# NEXA FULL v3 — Fixed Installer
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA FULL v3 — Modular AI Engine"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash install-nexa-full.sh" && exit 1

NEXA_DIR="/opt/nexa"
mkdir -p "$NEXA_DIR"/{config,data,knowledge,logs,bin,app}

# ─── STEP 1: INSPECT ───
echo ""
echo "📋 VPS Inspection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

RAM_MB=$(free -m | awk '/^Mem:/ {print $2}')
RAM_GB=$(awk "BEGIN {printf \"%.1f\", $RAM_MB/1024}")
CPU_CORES=$(nproc)
DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')

echo "  RAM: ${RAM_GB}GB | Cores: $CPU_CORES | Disk Free: $DISK_FREE"

if command -v ollama &>/dev/null; then
    echo "  Ollama binary: $(which ollama)"
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
echo "  Selected: $MODEL (Reasoning: $R1)"
read -p "  Press Enter to continue or type custom model: " USER_MODEL
[ -n "$USER_MODEL" ] && MODEL="$USER_MODEL"

# ─── STEP 2: INSTALL OLLAMA ───
echo ""
echo "🦙 Installing Ollama..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama installed"
else
    echo "✅ Ollama already present"
fi

# ─── STEP 3: FIX USER/GROUP ───
echo ""
echo "👤 Fixing Ollama user..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Remove old user if exists with issues
userdel ollama 2>/dev/null || true
groupdel ollama 2>/dev/null || true

# Create fresh
groupadd -f ollama 2>/dev/null || true
useradd -r -g ollama -s /bin/false -m -d /usr/share/ollama ollama 2>/dev/null || true

# Ensure home dir exists
mkdir -p /usr/share/ollama
chown -R ollama:ollama /usr/share/ollama 2>/dev/null || true

echo "✅ User fixed"

# ─── STEP 4: SYSTEMD ───
echo ""
echo "⚙️  Setting up Systemd..."
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

systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "⏳ Waiting for Ollama (max 30s)..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "✅ Ollama running on port 11434"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo ""
    echo "⚠️  Ollama not responding. Trying manual start..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 5
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "✅ Ollama running (manual start)"
    else
        echo "❌ Ollama failed to start. Check: journalctl -u ollama -n 20"
    fi
fi

# ─── STEP 5: PULL MODELS ───
echo ""
echo "🧠 Pulling Models..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⬇️ This takes 10-20 min..."

ollama pull "$MODEL" || echo "⚠️ Model pull may need retry"
[ -n "$R1" ] && ollama pull "$R1" || echo "⚠️ Reasoning model pull may need retry"

echo "✅ Models done"

# ─── STEP 6: DEPLOY NEXA ───
echo ""
echo "🚀 Deploying NEXA..."
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

# ─── STEP 7: TEST ───
echo ""
echo "🧪 Testing..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "✅ Ollama API reachable"
    MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join([m['name'] for m in d.get('models',[])]))" 2>/dev/null || echo "unknown")
    echo "  Models: $MODELS"
else
    echo "⚠️ Ollama API not reachable yet"
fi

# ─── DONE ───
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ NEXA FULL v3 INSTALLED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Start: nexa    or    n"
echo ""
echo "Commands:"
echo "  nexa --doctor    Diagnostics"
echo "  nexa --status    System status"
echo "  nexa --model     List models"
echo ""
