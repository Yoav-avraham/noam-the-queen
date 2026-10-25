#!/bin/bash

set -e

if ! grep -qiE "microsoft|wsl" /proc/version 2>/dev/null; then
	echo "This repository is configured for WSL-only development."
	echo "Open WSL, then run: bash ./setup.sh"
	exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
	echo "Installing uv..."
	curl -LsSf https://astral.sh/uv/install.sh | sh
	export PATH="$HOME/.local/bin:$PATH"
fi

echo "Syncing dependencies..."
uv sync --all-packages --group dev --no-editable --link-mode copy

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Setting up pre-commit..."
pre-commit install -f --hook-type pre-commit
pre-commit install -f --hook-type pre-push

echo "Configuring git credentials..."
git config --global credential.helper "/mnt/c/Program\ Files/Git/mingw64/bin/git-credential-manager.exe"

echo "Setup complete!"
echo "Activate venv with: source .venv/bin/activate"
