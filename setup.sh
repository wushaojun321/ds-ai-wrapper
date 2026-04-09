#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Discord Bot (DsAiWrapper) 用户级一键部署脚本
# 用法: ./setup.sh
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

if [[ $EUID -eq 0 ]]; then
    error "请勿以 root 运行此脚本。直接以普通用户运行: ./setup.sh"
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
SERVICE_TEMPLATE="$SCRIPT_DIR/discord-bot.service"
SERVICE_NAME="discord-bot"
USER_SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$USER_SERVICE_DIR/${SERVICE_NAME}.service"

info "当前用户: $USER"
info "Bot 目录: $SCRIPT_DIR"

# ---------- 检测 node / claude 路径，构造 EXTRA_PATH ----------
EXTRA_PATHS=""

NODE_BIN=$(which node 2>/dev/null || true)
if [[ -n "$NODE_BIN" ]]; then
    NODE_DIR=$(dirname "$NODE_BIN")
    EXTRA_PATHS="$NODE_DIR"
    info "检测到 node: $NODE_BIN"
else
    warn "未找到 node，claude CLI 可能无法运行"
fi

CLAUDE_BIN=$(which claude-internal 2>/dev/null || which claude 2>/dev/null || true)
if [[ -n "$CLAUDE_BIN" ]]; then
    CLAUDE_DIR=$(dirname "$CLAUDE_BIN")
    if [[ "$EXTRA_PATHS" != *"$CLAUDE_DIR"* ]]; then
        EXTRA_PATHS="${EXTRA_PATHS:+$EXTRA_PATHS:}$CLAUDE_DIR"
    fi
    info "检测到 claude: $CLAUDE_BIN"
else
    warn "未找到 claude CLI，请确认 .env 中 CLAUDE_CMD 使用了完整路径"
fi

for p in "$HOME/.local/bin" "$HOME/.npm-global/bin"; do
    if [[ -d "$p" && "$EXTRA_PATHS" != *"$p"* ]]; then
        EXTRA_PATHS="${EXTRA_PATHS:+$EXTRA_PATHS:}$p"
    fi
done

info "额外 PATH: $EXTRA_PATHS"

# ---------- 1. 创建 venv & 安装依赖 ----------
info "创建 Python 虚拟环境..."
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    info "venv 创建完成: $VENV_DIR"
else
    info "venv 已存在，跳过创建"
fi

PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

info "安装 Python 依赖..."
"$PIP_BIN" install -r "$SCRIPT_DIR/requirements.txt" --quiet
info "依赖安装完成"

# 将 venv Python 加到 PATH 最前面
VENV_BIN="$VENV_DIR/bin"
EXTRA_PATHS="${VENV_BIN}${EXTRA_PATHS:+:$EXTRA_PATHS}"

# ---------- 2. 检查 .env ----------
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn ".env 文件不存在，已从 .env.example 复制"
        warn "请编辑 .env 填写实际配置: nano $ENV_FILE"
    else
        error ".env.example 文件不存在，无法继续"
    fi
else
    info ".env 文件已存在"
fi

# ---------- 3. 生成用户级 systemd service ----------
info "生成 systemd 用户级 service 文件..."
if [[ ! -f "$SERVICE_TEMPLATE" ]]; then
    error "service 模板文件不存在: $SERVICE_TEMPLATE"
fi

mkdir -p "$USER_SERVICE_DIR"

sed \
    -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" \
    -e "s|__PYTHON__|${PYTHON_BIN}|g" \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__EXTRA_PATH__|${EXTRA_PATHS}|g" \
    "$SERVICE_TEMPLATE" > "$SERVICE_DEST"

info "service 文件已写入: $SERVICE_DEST"

# ---------- 4. 启用 linger ----------
LINGER_FILE="/var/lib/systemd/linger/$USER"
if [[ ! -f "$LINGER_FILE" ]]; then
    warn "需要启用 linger 以支持用户服务在登出后继续运行。"
    if sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
        info "linger 已启用"
    else
        warn "无法自动启用 linger，请手动执行: sudo loginctl enable-linger $USER"
    fi
else
    info "linger 已启用"
fi

# ---------- 5. 验证 user bus ----------
if ! systemctl --user status >/dev/null 2>&1; then
    warn "无法连接 systemd user bus。"
    warn "请确保有完整的 user session。"
    error "中止部署。请解决上述问题后重试。"
fi

# ---------- 6. 启用并启动服务 ----------
info "重新加载 systemd 用户配置..."
systemctl --user daemon-reload

info "启用开机自启..."
systemctl --user enable "$SERVICE_NAME"

info "启动服务..."
systemctl --user restart "$SERVICE_NAME"

# ---------- 7. 输出状态 ----------
echo ""
echo "=========================================="
info "部署完成！"
echo "=========================================="
echo ""
systemctl --user status "$SERVICE_NAME" --no-pager || true
echo ""
echo "常用命令:"
echo "  systemctl --user status $SERVICE_NAME      # 查看状态"
echo "  systemctl --user restart $SERVICE_NAME     # 重启"
echo "  systemctl --user stop $SERVICE_NAME        # 停止"
echo "  journalctl --user -u $SERVICE_NAME -f      # 实时日志"
echo ""
