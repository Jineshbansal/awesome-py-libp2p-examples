#!/bin/bash
set -e

BASE_PORT=8000

echo "=================================================="
echo "  🚀 P2P DHT Chat - Quick Start"
echo "=================================================="
echo ""

# --------------------------------------------------
# Check Python
# --------------------------------------------------
if ! command -v python &> /dev/null; then
    echo "❌ Python not found. Install Python 3.8+"
    exit 1
fi

# --------------------------------------------------
# Check dependencies
# --------------------------------------------------
echo "🔍 Checking dependencies..."
python - <<EOF
try:
    import libp2p, trio, multiaddr
except Exception:
    raise SystemExit(1)
EOF

if [ $? -ne 0 ]; then
    echo "📦 Installing dependencies..."
    pip install libp2p trio multiaddr
fi

echo "✅ Dependencies OK"
echo ""

# --------------------------------------------------
# Menu
# --------------------------------------------------
echo "Choose an option:"
echo ""
echo "  1) Start FIRST user (bootstrap node)"
echo "  2) Start ANOTHER user"
echo "  3) Quit"
echo ""
read -p "Enter choice: " choice

# --------------------------------------------------
# First user
# --------------------------------------------------
if [ "$choice" = "1" ]; then
    echo ""
    read -p "Enter username: " USERNAME

    PORT=$BASE_PORT

    echo ""
    echo "=============================================="
    echo "🟢 Starting FIRST user"
    echo "----------------------------------------------"
    echo "Username : $USERNAME"
    echo "Port     : $PORT"
    echo ""
    echo "⚠️  COPY ONE MULTIADDR SHOWN BELOW"
    echo "    You will need it for other users"
    echo "=============================================="
    echo ""

    python dhtd.py \
        -u "$USERNAME" \
        -p "$PORT" \
        -i

# --------------------------------------------------
# Additional user
# --------------------------------------------------
elif [ "$choice" = "2" ]; then
    echo ""
    read -p "Enter user number (2, 3, 4, ...): " USER_NUM
    read -p "Enter username: " USERNAME
    read -p "Enter bootstrap multiaddr: " BOOTSTRAP

    PORT=$((BASE_PORT + USER_NUM - 1))

    echo ""
    echo "=============================================="
    echo "🔵 Starting user #$USER_NUM"
    echo "----------------------------------------------"
    echo "Username  : $USERNAME"
    echo "Port      : $PORT"
    echo "Bootstrap : $BOOTSTRAP"
    echo "=============================================="
    echo ""

    python dhtd.py \
        -u "$USERNAME" \
        -p "$PORT" \
        -b "$BOOTSTRAP" \
        -i

# --------------------------------------------------
# Quit
# --------------------------------------------------
else
    echo "👋 Exiting"
    exit 0
fi
