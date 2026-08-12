#!/bin/bash
set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA OWN ENGINE — Pure Local AI"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash install-nexa-own.sh" && exit 1

NEXA_DIR="/opt/nexa-ai"
mkdir -p "$NEXA_DIR"/{models,data,skills,downloads,bin}

echo "📦 Installing dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv build-essential cmake libopenblas-dev pkg-config sqlite3 curl

# Python venv
if [ ! -d "$NEXA_DIR/venv" ]; then
    python3 -m venv "$NEXA_DIR/venv"
fi
source "$NEXA_DIR/venv/bin/activate"

# Install llama-cpp-python (compiles for CPU)
echo "🔧 Building llama-cpp-python (this takes 3-5 min)..."
pip install -q --upgrade pip
CMAKE_ARGS="-DLLAMA_BLAS=OFF -DLLAMA_CUDA=OFF" pip install -q llama-cpp-python

echo "⬇️ Downloading engine..."
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-own.py -o "$NEXA_DIR/app/nexa-own.py"
chmod +x "$NEXA_DIR/app/nexa-own.py"

# Wrappers
cat > "$NEXA_DIR/bin/nexa" << 'EOF'
#!/bin/bash
source /opt/nexa-ai/venv/bin/activate
python3 /opt/nexa-ai/app/nexa-own.py "$@"
EOF
chmod +x "$NEXA_DIR/bin/nexa"
cp "$NEXA_DIR/bin/nexa" "$NEXA_DIR/bin/n"
chmod +x "$NEXA_DIR/bin/n"
ln -sf "$NEXA_DIR/bin/nexa" /usr/local/bin/nexa
ln -sf "$NEXA_DIR/bin/n" /usr/local/bin/n

echo ""
echo "✅ NEXA OWN ENGINE installed!"
echo ""
echo "First run will download ~1GB model from HuggingFace."
echo ""
echo "Start chatting:"
echo "  nexa    or    n"
echo ""
