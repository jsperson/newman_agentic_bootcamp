#!/bin/bash

# Docker Container Run Script: AI Development Environment
# Creates an Ubuntu container with git, gh CLI, Claude Code, and OpenCode
# Pattern: create if missing, start if stopped, connect if running

# Variables
CONTAINER_NAME="newman_agentic_development"
IMAGE_NAME="ubuntu:latest"
USER_IN_CONTAINER="developer"
MOUNT_PATH_ON_HOST="${HOME}"
MOUNT_PATH_IN_CONTAINER="/home/${USER_IN_CONTAINER}/host"

# Check if the container exists
CONTAINER_ID=$(docker ps -a -q -f name="^${CONTAINER_NAME}$")

# If the container does not exist, create, setup, and run it
if [ -z "$CONTAINER_ID" ]; then
    echo "Container does not exist. Creating and starting..."

    docker run -d \
      --name $CONTAINER_NAME \
      -v $MOUNT_PATH_ON_HOST:$MOUNT_PATH_IN_CONTAINER \
      $IMAGE_NAME sleep infinity

    echo "Container created. Running setup..."

    # --- Setup script piped via stdin to avoid heredoc quoting issues ---
    docker exec -i $CONTAINER_NAME bash <<'SETUP_EOF'
set -e
export DEBIAN_FRONTEND=noninteractive

DEVELOPER_USER="developer"

echo "[1/8] Updating system..."
apt update && apt upgrade -y

echo "[2/8] Installing essentials..."
apt install -y \
    curl wget sudo git vim nano \
    build-essential ca-certificates gnupg \
    lsb-release software-properties-common \
    unzip zip jq less tree htop man-db

echo "[3/8] Creating developer user..."
useradd -m -s /bin/bash $DEVELOPER_USER
echo "$DEVELOPER_USER:developer" | chpasswd
echo "$DEVELOPER_USER ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
# Fix ownership on home dir only (skip bind-mounted host/ to avoid recursing into macOS home)
chown $DEVELOPER_USER:$DEVELOPER_USER /home/$DEVELOPER_USER
find /home/$DEVELOPER_USER -maxdepth 1 ! -name host ! -path /home/$DEVELOPER_USER -exec chown -R $DEVELOPER_USER:$DEVELOPER_USER {} +

echo "[4/8] Installing gh CLI..."
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
apt update && apt install -y gh

echo "[5/8] Installing Claude Code (native installer)..."
su - $DEVELOPER_USER -c "curl -fsSL https://claude.ai/install.sh | bash"
# Add ~/.local/bin to PATH for developer (Claude Code installs here)
su - $DEVELOPER_USER -c 'echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.bashrc'

echo "[6/8] Installing Node.js LTS (for OpenCode)..."
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
apt install -y nodejs

echo "[7/8] Installing OpenCode..."
npm install -g opencode-ai@latest

echo "[8/8] Configuring developer environment..."
su - $DEVELOPER_USER -c "git config --global init.defaultBranch main"
su - $DEVELOPER_USER -c "git config --global pull.rebase false"
su - $DEVELOPER_USER -c "git config --global credential.helper store"
su - $DEVELOPER_USER -c "mkdir -p ~/source ~/bin"

cat > /home/$DEVELOPER_USER/.bash_aliases <<'ALIASES'
alias ll="ls -alF"
alias la="ls -A"
alias gs="git status"
alias ga="git add"
alias gc="git commit"
alias gp="git push"
alias gl="git log --oneline --graph --decorate"
ALIASES
chown $DEVELOPER_USER:$DEVELOPER_USER /home/$DEVELOPER_USER/.bash_aliases

cat > /home/$DEVELOPER_USER/bin/claude_danger.sh <<'LAUNCHER'
#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
exec claude --dangerously-skip-permissions "$@"
LAUNCHER
chown $DEVELOPER_USER:$DEVELOPER_USER /home/$DEVELOPER_USER/bin/claude_danger.sh
chmod 700 /home/$DEVELOPER_USER/bin/claude_danger.sh

apt autoremove -y && apt clean

echo ""
echo "=== Setup complete ==="
echo "  Node.js:  $(node --version)"
echo "  npm:      $(npm --version)"
echo "  gh:       $(gh --version | head -1)"
CLAUDE_VER=$(su - $DEVELOPER_USER -c 'export PATH=$HOME/.local/bin:$PATH && claude --version 2>/dev/null') || CLAUDE_VER="installed"
echo "  claude:   $CLAUDE_VER"
echo "  opencode: $(opencode --version 2>/dev/null || echo installed)"
echo "======================"
SETUP_EOF

    echo "Setup finished."
else
    # Check if the container is running
    RUNNING_CONTAINER_ID=$(docker ps -q -f name="^${CONTAINER_NAME}$")
    if [ -z "$RUNNING_CONTAINER_ID" ]; then
        echo "Container exists but is stopped. Starting..."
        docker start $CONTAINER_NAME
    else
        echo "Container is already running."
    fi
fi

# Connect to the container as developer user
echo "Connecting to container as $USER_IN_CONTAINER..."
docker exec -it --user $USER_IN_CONTAINER -w /home/$USER_IN_CONTAINER $CONTAINER_NAME /bin/bash
