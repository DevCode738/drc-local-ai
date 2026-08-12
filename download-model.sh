#!/bin/bash
set -e
# NEXA Model Pre-Downloader

MODEL_DIR="/opt/nexa-ai/models"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_NAME="qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_PATH="$MODEL_DIR/$MODEL_NAME"

mkdir -p "$MODEL_DIR"

if [ -f "$MODEL_PATH" ] && [ $(stat -c%s "$MODEL_PATH" 2>/dev/null || echo 0) -gt 100000000 ]; then
    echo "✅ Model already downloaded: $(du -m $MODEL_PATH | cut -f1)MB"
    exit 0
fi

echo "⬇️ Downloading Qwen2.5-1.5B model (~1GB)..."
echo "   This takes 5-15 minutes depending on internet speed..."
echo ""

wget -q --show-progress -O "$MODEL_PATH.tmp" "$MODEL_URL"
mv "$MODEL_PATH.tmp" "$MODEL_PATH"

SIZE_MB=$(du -m "$MODEL_PATH" | cut -f1)
echo ""
echo "✅ Model ready: ${SIZE_MB}MB at $MODEL_PATH"
echo "Now run: sudo bash install-nexa-own.sh"
