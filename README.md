# 🤖 DRC Local AI — VPS Setup Guide

## Files
| File | Purpose |
|------|---------|
| `vps-inspect.sh` | Inspect VPS hardware |
| `install-drc-ai.sh` | Full installer (run this) |
| `drc-chat.py` | Main chat application |

## Quick Start (3 Commands)

```bash
# 1. Upload files to VPS
scp vps-inspect.sh install-drc-ai.sh drc-chat.py root@YOUR_VPS_IP:/root/

# 2. Inspect (optional)
chmod +x vps-inspect.sh && ./vps-inspect.sh

# 3. Install
chmod +x install-drc-ai.sh && sudo bash install-drc-ai.sh
```

## After Install

```bash
chat        # Start AI chat
h           # Same as chat
chat --new  # Fresh conversation
chat --history  # View all past chats
chat --clear    # Delete all history
```

## Inside Chat Commands
- `/new` — New session
- `/history` — Current session history
- `/clear` — Clear current session
- `/help` — Help
- `/exit` — Quit

## Architecture
```
/opt/drc-ai/
├── app/
│   └── drc-chat.py      # Python chat app
├── data/
│   └── conversations.db # SQLite memory
├── logs/
├── config/
├── bin/
│   ├── chat             # Wrapper script
│   └── h                # Alias wrapper
└── venv/                # Python virtual env
```

## Systemd
```bash
sudo systemctl status ollama    # Check Ollama
sudo systemctl restart ollama   # Restart
sudo systemctl enable ollama    # Auto-start on boot
```

## Model Info
| Model | Disk | RAM | Quality |
|-------|------|-----|---------|
| llama3.2:3b | ~2GB | ~2.5GB | Good |
| llama3.2:1b | ~1.3GB | ~1.5GB | Basic |
| qwen2.5:7b | ~4.7GB | ~5GB | Better |

Default: `llama3.2:3b` (recommended for 10GB RAM VPS)

## Change Model
```bash
export DRC_MODEL=qwen2.5:7b
ollama pull qwen2.5:7b
chat
```

## Uninstall
```bash
sudo systemctl stop ollama
sudo systemctl disable ollama
sudo rm -rf /opt/drc-ai /usr/local/bin/chat /usr/local/bin/h /etc/systemd/system/ollama.service
sudo userdel ollama
```
