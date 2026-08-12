#!/bin/bash
set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA v2 — CUSTOM AI ENGINE INSTALL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash install-nexa-v2.sh" && exit 1

NEXA_DIR="/opt/nexa-ai"
mkdir -p "$NEXA_DIR"/{app,config,data,skills,downloads,bin}

# Deps
echo "📦 Installing dependencies..."
apt-get update -qq && apt-get install -y -qq python3 python3-pip sqlite3 curl

# App
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-v2.py -o "$NEXA_DIR/app/nexa-v2.py"
chmod +x "$NEXA_DIR/app/nexa-v2.py"

# Wrappers
cat > "$NEXA_DIR/bin/nexa" << 'EOF'
#!/bin/bash
python3 /opt/nexa-ai/app/nexa-v2.py "$@"
EOF
chmod +x "$NEXA_DIR/bin/nexa"
cp "$NEXA_DIR/bin/nexa" "$NEXA_DIR/bin/n"
chmod +x "$NEXA_DIR/bin/n"
ln -sf "$NEXA_DIR/bin/nexa" /usr/local/bin/nexa
ln -sf "$NEXA_DIR/bin/n" /usr/local/bin/n

# Init DB
python3 -c "import sys; sys.path.insert(0, '/opt/nexa-ai/app'); exec(open('/opt/nexa-ai/app/nexa-v2.py').read().split('def main()')[0]); init_db()" 2>/dev/null || true

echo ""
echo "✅ NEXA v2 installed!"
echo ""
echo "NEXT STEP — Add API key (FREE):"
echo "  nexa --setup"
echo ""
echo "Or get key manually from: https://openrouter.ai/keys"
echo ""
echo "Then start chatting:"
echo "  nexa    or    n"
echo ""
