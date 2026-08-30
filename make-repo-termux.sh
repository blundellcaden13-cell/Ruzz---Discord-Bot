#!/data/data/com.termux/files/usr/bin/bash
# make-repo-termux.sh — set up the Ruzz bot Git repo on Termux
# Usage:
#   1. Put this script next to your cleaned bot folder (or inside it)
#   2. bash make-repo-termux.sh
#   3. Follow the prompts

set -e

echo "========================================"
echo "  Ruzz bot — Termux repo setup"
echo "========================================"
echo

# --- find project root ---
if [ -f "main.py" ] && [ -f "requirements.txt" ]; then
    PROJECT_DIR="$(pwd)"
elif [ -d "ruzz-bot-clean" ] && [ -f "ruzz-bot-clean/main.py" ]; then
    PROJECT_DIR="$(pwd)/ruzz-bot-clean"
elif [ -d "ruzz-bot" ] && [ -f "ruzz-bot/main.py" ]; then
    PROJECT_DIR="$(pwd)/ruzz-bot"
else
    echo "Could not find the bot files."
    echo "Run this script from inside the bot folder, or from the folder that contains it."
    echo
    echo "Expected files: main.py, requirements.txt, .env.example"
    exit 1
fi

cd "$PROJECT_DIR"
echo "Project: $PROJECT_DIR"
echo

# --- check git ---
if ! command -v git >/dev/null 2>&1; then
    echo "git not found. Installing..."
    pkg update -y
    pkg install -y git
fi

# --- safety: never commit secrets ---
if [ -f ".env" ]; then
    echo "WARNING: .env exists. It will NOT be committed (.gitignore blocks it)."
    echo "Make sure it does not contain a token you care about sharing."
    echo
fi

if [ -f "database/devhub.db" ]; then
    echo "WARNING: database/devhub.db found. It is gitignored and will not be committed."
    echo
fi

# --- ensure .gitignore exists ---
if [ ! -f ".gitignore" ]; then
    cat > .gitignore << 'EOF'
.env
venv/
__pycache__/
*.pyc
*.pyo
*.db
logs/*.log
*.log
.DS_Store
Thumbs.db
dist/
build/
*.egg-info/
.requirements.hash
EOF
    echo "Created .gitignore"
fi

# --- ensure .env.example exists ---
if [ ! -f ".env.example" ]; then
    cat > .env.example << 'EOF'
TOKEN=your-bot-token-here
OWNER_ID=your-discord-user-id

POLL_WEB_PORT=8090
POLL_WEB_USERNAME=admin
POLL_WEB_PASSWORD=

HOME_WEB_PORT=8091
BOT_API_URL=http://localhost:8080

LOGS_WEB_PORT=8092
TICKETS_WEB_PORT=8094
EOF
    echo "Created .env.example"
fi

# --- git config (local only if not set) ---
if [ -z "$(git config --global user.name 2>/dev/null)" ]; then
    echo "Git user.name not set."
    read -r -p "Your name (for commits): " GIT_NAME
    git config --global user.name "$GIT_NAME"
fi
if [ -z "$(git config --global user.email 2>/dev/null)" ]; then
    echo "Git user.email not set."
    read -r -p "Your email (for commits): " GIT_EMAIL
    git config --global user.email "$GIT_EMAIL"
fi

# --- init repo ---
if [ -d ".git" ]; then
    echo "Git repo already exists here."
    read -r -p "Re-init and make a fresh initial commit? [y/N] " REINIT
    if [ "$REINIT" = "y" ] || [ "$REINIT" = "Y" ]; then
        rm -rf .git
        git init
        git branch -M main
        git add .
        git commit -m "Initial open-source release"
        echo "Fresh repo created."
    else
        echo "Keeping existing repo. Running git status:"
        git status -sb
    fi
else
    git init
    git branch -M main
    git add .
    git commit -m "Initial open-source release"
    echo "Repo initialized and first commit made."
fi

echo
echo "========================================"
echo "  Local repo is ready"
echo "========================================"
echo
echo "Files staged/committed (secrets excluded by .gitignore)."
echo
echo "Next steps on GitHub:"
echo "  1. Open https://github.com/new"
echo "  2. Create an empty PUBLIC repo (no README / no .gitignore)"
echo "  3. Copy the repo URL, then run:"
echo
echo "     git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git"
echo "     git push -u origin main"
echo
echo "To attach Linux / macOS / Windows zips later:"
echo "  Repo page → Releases → Create a new release → upload the 3 zips"
echo
echo "Optional: install GitHub CLI for easier push/releases:"
echo "  pkg install gh"
echo "  gh auth login"
echo "  gh repo create YOUR_REPO --public --source=. --remote=origin --push"
echo
echo "Done."
