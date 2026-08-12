#!/bin/bash
set -e
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧠 NEXA OWN ENGINE — INSTALL + PRELOAD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[ "$EUID" -ne 0 ] && echo "❌ Run as root: sudo bash install-nexa-own.sh" && exit 1

NEXA_DIR="/opt/nexa-ai"
MODEL_DIR="$NEXA_DIR/models"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_NAME="qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_PATH="$MODEL_DIR/$MODEL_NAME"

mkdir -p "$NEXA_DIR"/{models,data,skills,downloads,bin}

echo "📦 Installing dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv build-essential cmake libopenblas-dev pkg-config sqlite3 curl wget

# Python venv
if [ ! -d "$NEXA_DIR/venv" ]; then
    python3 -m venv "$NEXA_DIR/venv"
fi
source "$NEXA_DIR/venv/bin/activate"

# Install llama-cpp-python
echo "🔧 Building llama-cpp-python..."
pip install -q --upgrade pip
CMAKE_ARGS="-DLLAMA_BLAS=OFF -DLLAMA_CUDA=OFF" pip install -q llama-cpp-python

echo "⬇️ Downloading NEXA engine..."
curl -fsSL https://raw.githubusercontent.com/DevCode738/drc-local-ai/main/nexa-own.py -o "$NEXA_DIR/app/nexa-own.py"
chmod +x "$NEXA_DIR/app/nexa-own.py"

# Pre-download model
if [ ! -f "$MODEL_PATH" ] || [ $(stat -c%s "$MODEL_PATH" 2>/dev/null || echo 0) -lt 100000000 ]; then
    echo ""
    echo "⬇️ Downloading AI brain (~1GB)..."
    echo "   Source: HuggingFace Qwen2.5-1.5B-Instruct"
    echo "   This takes 5-15 min depending on speed..."
    echo ""
    wget -q --show-progress -O "$MODEL_PATH.tmp" "$MODEL_URL"
    mv "$MODEL_PATH.tmp" "$MODEL_PATH"
    SIZE_MB=$(du -m "$MODEL_PATH" | cut -f1)
    echo "✅ Model downloaded: ${SIZE_MB}MB"
else
    SIZE_MB=$(du -m "$MODEL_PATH" | cut -f1)
    echo "✅ Model already exists: ${SIZE_MB}MB"
fi

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
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ NEXA READY — Model pre-loaded!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Start chatting NOW:"
echo "  nexa    or    n"
echo ""
