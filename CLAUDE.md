# CLAUDE.md

## 隐私与开源规范（最高优先级）

本仓库是**公开开源**的，任何提交都不能带上维护者的个人隐私或部署信息：

- **禁止提交**：API Key / Token（DeepSeek、Discord 等）、服务器 IP / 域名 / SSH 别名、真实用户名、个人本地路径（如 `/Users/<name>`、`/home/<name>`）、邮箱、频道/服务器 ID、代理节点配置。
- 真实配置只放 `.env`（已 gitignore）；`.env.example` 只能用占位符（如 `your_token_here`、`/home/youruser/projects`）。
- 运行时数据（`sessions.json`、`workspaces.json`、`log/`、agent 会话目录）不入库，新增此类文件时同步更新 `.gitignore`。
- 代码注释、README、示例、commit message 里同样不能出现上述信息，用通用示例代替。
- 提交前自查：`git diff --cached | grep -nE 'sk-|[0-9]{1,3}(\.[0-9]{1,3}){3}|/Users/|/home/'`。
