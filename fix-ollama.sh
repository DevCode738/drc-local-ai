#!/bin/bash
set -e
echo "🔧 NEXA FIX — Ollama Service Repair"
echo "===================================="

# 1. Find ollama binary
OLLAMA_BIN=""
for path in /usr/local/bin/ollama /usr/bin/ollama /opt/ollama/bin/ollama /root/.ollama/bin/ollama; do
    if [ -x "$path" ]; then
        OLLAMA_BIN="$path"
        echo "✅ Found ollama: $OLLAMA_BIN"
        break
    fi
done

if [ -z "$OLLAMA_BIN" ]; then
    echo "❌ Ollama binary not found. Reinstalling..."
    curl -fsSL https://ollama.com/install.sh | sh
    OLLAMA_BIN="/usr/local/bin/ollama"
fi

# 2. Create ollama user properly
if ! id -u ollama &>/dev/null; then
    groupadd -f ollama
    useradd -r -g ollama -s /bin/false -m -d /usr/share/ollama ollama 2>/dev/null || true
    echo "✅ Ollama user created"
else
    echo "✅ Ollama user exists"
fi

# 3. Fix systemd service
cat > /etc/systemd/system/ollama.service << EOF
[Unit]
Description=Ollama AI Service
After=network-online.target

[Service]
ExecStart=$OLLAMA_BIN serve
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

echo "✅ Systemd service fixed"

# 4. Permissions
chown -R ollama:ollama /usr/share/ollama 2>/dev/null || true
mkdir -p /usr/share/ollama
chown ollama:ollama /usr/share/ollama

# 5. Reload + Start
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama

echo "⏳ Waiting for Ollama to start..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "✅ Ollama is running on port 11434"
        break
    fi
    sleep 1
done

# 6. Verify
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo ""
    echo "🎉 Ollama fixed and running!"
    echo ""
    echo "Pulling models (if not present)..."
    $OLLAMA_BIN pull qwen2.5:7b 2>/dev/null || echo "⚠️ qwen2.5:7b pull may need manual retry"
    $OLLAMA_BIN pull deepseek-r1:7b 2>/dev/null || echo "⚠️ deepseek-r1:7b pull may need manual retry"
    echo ""
    echo "Test now: type 'n' or 'nexa'"
else
    echo "❌ Ollama still not running. Check logs: journalctl -u ollama -n 20"
fi
