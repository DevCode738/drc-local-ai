#!/bin/bash
# DRC VPS Inspector
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🖥️  DRC VPS INSPECTION REPORT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "\n🧩 SYSTEM"
echo "OS        : $(lsb_release -d -s 2>/dev/null || cat /etc/os-release | grep PRETTY | cut -d= -f2 | tr -d '\"')"
echo "Kernel    : $(uname -r)"
echo "Uptime    : $(uptime -p 2>/dev/null || uptime | awk -F',' '{print $1}')"

echo -e "\n⚙️ CPU"
echo "Cores     : $(nproc)"
echo "Model     : $(cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2 | sed 's/^ //')"
echo "Load Avg  : $(cat /proc/loadavg | awk '{print $1", "$2", "$3}')"

echo -e "\n🧠 RAM (GB)"
free -h | awk '/^Mem:/ {printf "Total     : %s\nUsed      : %s\nAvailable : %s\nUsage     : %.1f%%\n", $2, $3, $7, ($3/$2)*100}'

echo -e "\n💾 STORAGE (GB)"
df -h / | awk 'NR==2 {printf "Total     : %s\nUsed      : %s\nAvailable : %s\nUsage     : %s\n", $2, $3, $4, $5}'

echo -e "\n🎮 GPU"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1
else
    echo "GPU       : None detected"
fi

echo -e "\n📦 EXISTING INSTALLATIONS"
echo "Ollama    : $(command -v ollama &> /dev/null && echo 'Installed ('$(ollama --version 2>/dev/null || echo "unknown")')' || echo 'Not installed')"
echo "Python3   : $(command -v python3 &> /dev/null && echo 'Installed ('$(python3 --version 2>/dev/null)')' || echo 'Not installed')"
echo "pip3      : $(command -v pip3 &> /dev/null && echo 'Installed' || echo 'Not installed')"
echo "curl      : $(command -v curl &> /dev/null && echo 'Installed' || echo 'Not installed')"

echo -e "\n🔥 RUNNING SERVICES"
systemctl list-units --type=service --state=running 2>/dev/null | grep -E "ollama|python" || echo "No AI-related services running"

echo -e "\n🌐 NETWORK"
ip addr show 2>/dev/null | grep "inet " | awk '{print "IP        : "$2}' | head -2

echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Inspection Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
