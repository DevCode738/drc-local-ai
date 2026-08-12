#!/bin/bash
# NEXA AUTO — Self-Building AI Installer
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 NEXA AUTO — Self-Building AI"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root" && exit 1

AUTO_DIR="/opt/autonexa"
mkdir -p "$AUTO_DIR"/{logs,data,modules,sources}

echo "📦 Installing dependencies..."
apt-get update -qq && apt-get install -y -qq python3 sqlite3 curl nohup 2>/dev/null || apt-get install -y -qq python3 sqlite3 curl

# Download files
echo "⬇️ Downloading NEXA core..."
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-core.py -o "$AUTO_DIR/nexa-core.py"
chmod +x "$AUTO_DIR/nexa-core.py"

echo "⬇️ Downloading watcher..."
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-watcher.py -o "$AUTO_DIR/nexa-watcher.py"
chmod +x "$AUTO_DIR/nexa-watcher.py"

echo "⬇️ Downloading sources manifest..."
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/sources.json -o "$AUTO_DIR/sources.json"

# Create commands
cat > /usr/local/bin/nexa << 'EOF'
#!/bin/bash
python3 /opt/autonexa/nexa-core.py --chat
EOF
chmod +x /usr/local/bin/nexa

cat > /usr/local/bin/n << 'EOF'
#!/bin/bash
python3 /opt/autonexa/nexa-core.py --chat
EOF
chmod +x /usr/local/bin/n

cat > /usr/local/bin/x << 'EOF'
#!/bin/bash
python3 /opt/autonexa/nexa-watcher.py
EOF
chmod +x /usr/local/bin/x

# Init database
python3 -c "
import sqlite3, os
os.makedirs('/opt/autonexa/data', exist_ok=True)
conn = sqlite3.connect('/opt/autonexa/data/brain.db')
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY, source TEXT, category TEXT, chunk TEXT, keywords TEXT, weight REAL DEFAULT 1.0, timestamp REAL)')
c.execute('CREATE TABLE IF NOT EXISTS patterns (id INTEGER PRIMARY KEY, pattern TEXT, response TEXT, category TEXT, hits INTEGER DEFAULT 0, timestamp REAL)')
c.execute('CREATE TABLE IF NOT EXISTS modules (id INTEGER PRIMARY KEY, name TEXT, code TEXT, status TEXT, tests TEXT, timestamp REAL)')
c.execute('CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)')
c.execute('CREATE TABLE IF NOT EXISTS errors (id INTEGER PRIMARY KEY, module TEXT, error TEXT, fix TEXT, timestamp REAL)')
conn.commit()
conn.close()
print('✅ Brain initialized')
"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ NEXA AUTO INSTALLED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "STEP 1 — Start the builder (runs 24/7):"
echo "  nohup python3 /opt/autonexa/nexa-core.py > /dev/null 2>&1 &"
echo ""
echo "STEP 2 — Watch live build logs:"
echo "  x"
echo ""
echo "STEP 3 — Chat with NEXA:"
echo "  nexa    or    n"
echo ""
echo "The AI will:"
echo "  • Fetch 30+ learning sources automatically"
echo "  • Build its own code modules"
echo "  • Test itself"
echo "  • Learn from conversations"
echo "  • Improve every 5 minutes"
echo ""
echo "Just run the nohup command and type 'x' to watch!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
