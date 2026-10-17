# CLAUDE.md

## 隐私与开源规范（最高优先级）

本仓库是**公开开源**的，任何提交都不能带上维护者的个人隐私或部署信息：

- **禁止提交**：API Key / Token（DeepSeek、Discord 等）、服务器 IP / 域名 / SSH 别名、真实用户名、个人本地路径（如 `/Users/<name>`、`/home/<name>`）、邮箱、频道/服务器 ID、代理节点配置。
- 真实配置只放 `.env`（已 gitignore）；`.env.example` 只能用占位符（如 `your_token_here`、`/home/youruser/projects`）。
- 运行时数据（`sessions.json`、`workspaces.json`、`log/`、agent 会话目录）不入库，新增此类文件时同步更新 `.gitignore`。
- 代码注释、README、示例、commit message 里同样不能出现上述信息，用通用示例代替。
- 提交前自查：`git diff --cached | grep -nE 'sk-|[0-9]{1,3}(\.[0-9]{1,3}){3}|/Users/|/home/'`。

## 架构要点

- Agent 是 [pi](https://pi.dev)，以 `pi -p --mode json` 子进程方式调用（`pi_agent.py`），解析 JSONL 事件流驱动 Discord 实时进度（`runner.py`）。
- 子进程必须 `stdin=DEVNULL`，否则 pi 会一直等 stdin 卡住；stdout 行可能很大（`agent_end` 带整轮消息），StreamReader `limit` 要调大。
- pi 会话按工作目录分目录存放在 `DATA_DIR/pi-sessions/<cwd-slug>/`，文件名 `<时间>_<session-id>.jsonl`。
- 网络：模型 API 直连（子进程会清掉代理环境变量），只有 Discord（`DISCORD_PROXY`）和 github.com（`GIT_PROXY`）走代理。
- pi 插件在容器内用 `pi install npm:<包>@<版本>` 安装（固定版本），落在 `DATA_DIR_HOST/pi-home`（挂载为 `/root/.pi`），重建镜像不丢；新插件带来新工具名时，同步更新 `runner.py` 的 `TOOL_ICONS`。
- 部署用 docker compose；bot 代码以 bind mount 方式挂载（本仓库同时也是一个工作区），改代码后 `/restart` 即生效，改依赖才需要 `--build`。
