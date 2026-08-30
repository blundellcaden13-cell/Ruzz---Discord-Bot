#!/data/data/com.termux/files/usr/bin/bash
# termux-setup.sh — one-time setup for running this project on Termux (Android).
#
# Usage (run once):
#   bash termux-setup.sh
#
# After this finishes, run everything with:
#   bash start.sh
# (not ./start.sh — see the note printed at the end of this script
# for why that specific distinction matters on Termux.)
#
# WHY THIS EXISTS: several dependencies (aiohttp, multidict, yarl,
# frozenlist, and — critically — pydantic-core, which FastAPI needs)
# ship pre-built wheels for Windows/macOS/glibc-Linux, but NOT for
# Termux's Android/Bionic environment. pip falls back to compiling
# them from source, which needs a C compiler (and, for pydantic-core
# specifically, a Rust compiler) that Termux doesn't have by default.

set -e

echo "=================================================================="
echo " Termux setup for the bot + websites"
echo "=================================================================="

echo
echo "[1/4] Updating Termux packages..."
pkg update -y && pkg upgrade -y

echo
echo "[2/4] Installing system build dependencies..."
# - python: Termux's Python (comes with sqlite3 support already built in)
# - clang, make: needed to compile aiohttp/audioop-lts's C extensions
# - rust: needed for pydantic-core (FastAPI's dependency) — there is
#   no way to skip this one, unlike the aiohttp-family packages below.
#   This step is genuinely slow (Rust itself is a big install) — that's
#   normal, not stuck.
# - libffi, openssl: common native-dependency requirements
# - git: only needed if you ever install something straight from GitHub
pkg install -y python clang make rust libffi openssl git

echo
echo "[3/4] Creating a virtual environment (if it doesn't already exist)..."
if [ ! -d "venv" ]; then
    python -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo
echo "[4/4] Installing Python dependencies..."
echo " (this can take a WHILE the first time — pydantic-core alone can take"
echo " 10-30+ minutes to compile on a phone CPU. Let it run; it's not stuck.)"

pip install --upgrade pip

# aiohttp, multidict, yarl, and frozenlist all have OPTIONAL C
# extensions purely for speed — every one of them has a documented
# env var to skip building the extension entirely and fall back to a
# pure-Python implementation instead. That's the right trade on a
# phone: a bit slower, but skips the most failure-prone compilation
# steps. (pydantic-core has no such escape hatch — that one always
# compiles, which is what the Rust install above was for.)
export AIOHTTP_NO_EXTENSIONS=1
export MULTIDICT_NO_EXTENSIONS=1
export YARL_NO_EXTENSIONS=1
export FROZENLIST_NO_EXTENSIONS=1

pip install -r requirements.txt

echo
echo "=================================================================="
echo " Done! From now on:"
echo "     bash start.sh"
echo "=================================================================="
echo
echo " (Termux doesn't have /usr/bin/env, so start.sh's shebang line"
echo " can't resolve on its own here — running it as './start.sh' will"
echo " fail with 'No such file or directory'. Always run it as"
echo " 'bash start.sh' on Termux specifically; that sidesteps the"
echo " shebang entirely and works fine. macOS/Linux can keep using"
echo " either ./start.sh or bash start.sh, doesn't matter there.)"
echo
echo " Two Termux-specific things worth doing next:"
echo
echo " 1. Keep Android from killing the bot when Termux is in the"
echo "    background — install the Termux:API app + package, then run:"
echo "      pkg install termux-api"
echo "      termux-wake-lock"
echo "    (run that once per session, before 'bash start.sh' — or add it to"
echo "    the top of start.sh permanently if you always want it on.)"
echo
echo " 2. Also turn off battery optimization for the Termux app itself"
echo "    in Android's Settings -> Apps -> Termux -> Battery — otherwise"
echo "    Android can still kill it even with a wake lock held."
