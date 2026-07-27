#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== GSE Portfolio — Install ==="

# --- Python version check ---
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3 not found. Install it first."
  exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Using $PYTHON ($PY_VERSION)"

# --- Virtual environment ---
VENV_DIR="$REPO_DIR/backend/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Installing backend dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_DIR/backend/requirements.txt"

echo "Installing bot dependencies..."
pip install --quiet -r "$REPO_DIR/bot/requirements.txt"

# --- .env file ---
ENV_FILE="$REPO_DIR/backend/.env"

if [ ! -f "$ENV_FILE" ]; then
  SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
  cat > "$ENV_FILE" <<EOF
SECRET_KEY=$SECRET_KEY
BOT_TOKEN=your-telegram-bot-token-here
ALLOWED_IDS=comma,separated,telegram,ids
EOF
  echo ""
  echo "Created $ENV_FILE with a random SECRET_KEY."
  echo ">>> Edit it now to set BOT_TOKEN and ALLOWED_IDS <<<"
else
  echo ".env already exists, skipping."
fi

# --- Init database ---
echo "Initializing database..."
cd "$REPO_DIR/backend"
python -c "import db; db.init_db(); print('Database ready.')"

# --- Run tests ---
echo "Running tests..."
python -m pytest tests/ -q

echo ""
echo "=== Install complete ==="
echo ""
echo "To start the backend:"
echo "  cd backend && source .venv/bin/activate"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "To start the Telegram bot:"
echo "  cd bot && source ../backend/.venv/bin/activate"
echo "  python main.py"
