# 项目日志功能方案

## Context

项目目前**零应用级日志**：无 `logging` 使用、无 print、前端无 console。排障只能靠 uvicorn 默认输出和 pytest，像 SSE 流中断、工具调用失败、记忆提炼异常这类问题无处可查。本方案为后端主服务与 MCP 子进程补齐日志：控制台实时查看 + 文件落盘轮转（用户已确认范围）。

关键约束：
- `mcp_server/server.py` 通过 **stdio** 与主进程通信（fastmcp），日志**绝不能进 stdout**，只能写文件，否则会破坏协议。
- 项目零第三方日志依赖，沿用 stdlib `logging`，不引入 loguru/structlog。
- `data/` 已在 .gitignore 中，日志放 `data/logs/` 不污染仓库。
- 敏感信息不入日志：DeepSeek API Key、完整用户消息内容（INFO 级只记长度）。

## 改动清单

### 1. `backend/app/config.py` — 新增 2 个配置项

```python
log_level: str = "INFO"
log_dir: Path = PROJECT_DIR / "data" / "logs"
```

### 2. 新建 `backend/app/logging_setup.py` — 统一日志初始化

- `setup_logging(settings)`：stdlib logging
  - Console handler（简洁格式）+ `RotatingFileHandler(log_dir/"backend.log", maxBytes=5MB, backupCount=5, encoding="utf-8")`
  - 格式：`%(asctime)s %(levelname)-7s [%(name)s] %(message)s`
  - 幂等：重复调用不叠加 handler（uvicorn --reload 与 pytest 场景）
  - 降噪：`httpx`/`httpcore`/`chromadb` 设为 WARNING
  - 在 `main.py` 的 lifespan 中调用（不放模块导入期，避免影响 pytest）

### 3. 各模块加 `logger = logging.getLogger(__name__)` + 关键埋点

| 文件 | 埋点 |
|---|---|
| `main.py` | 启动（配置摘要，不含 key）、关闭 |
| `controllers.py` | chat 流开始（会话ID/消息长度）、流结束（回答长度+耗时）、`error` 事件时 `logger.exception`；文档上传/扫描、删除操作 |
| `services/agent.py` | Agent 构建（工具清单）、重试警告（L269 except 处）、后台任务结果（记忆提炼条数、文件索引结果） |
| `services/rag.py` | `index_path`（文件、新增块数）、`search` 查询命中数（DEBUG 级） |
| `services/memory.py` | 提炼结果（新增条数 / 无新记忆） |

### 4. `backend/mcp_server/server.py` — 独立文件日志

模块顶部配置 FileHandler → `data/logs/mcp_server.log`（仅文件，不进 stdout）；记录 `notes_create`、`web_save` 调用与结果。

### 5. 测试

- 新增 `backend/tests/test_logging_setup.py`：验证 `setup_logging` 幂等、文件 handler 创建、级别生效
- 现有 25 个测试必须全部通过（setup 只在 lifespan 调用，不影响测试）

## 验证步骤

1. `python -m pytest tests/ -q` 全绿
2. 启动后端 → `data/logs/backend.log` 出现启动记录
3. `curl` 发起一次对话 → 日志出现：流开始 → 工具调用（如有）→ 回答长度+耗时
4. 检查 `data/logs/mcp_server.log` 已创建（MCP 子进程初始化记录）
5. 前端无改动，无需重建 dist
