# AI 私人助手

本地运行的 AI 私人助手：Vue 3 网页流式聊天 + FastAPI + LangChain 单 Agent + DeepSeek + 本地 RAG + 长期记忆 + MCP 工具。

## 环境要求

- Windows 10/11；Python 3.11+；Node 20+；conda 环境 `AI_env`
- DeepSeek API Key（在 https://platform.deepseek.com 获取）
- 嵌入模型位于 `backend/models/bge-large-zh-v1.5`（约 2.5GB，已 gitignore；缺失时程序会尝试从魔搭自动下载）

## 后端依赖安装（AI_env）

已在 `AI_env` 中安装本项目所需依赖（LangChain v1、FastAPI、MCP、Chroma 等）。若换新机器或环境需要重装：

```bash
conda activate AI_env
cd backend
pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic-settings>=2.7" "langchain>=1.0" "langchain-openai>=1.0" "langchain-mcp-adapters>=0.3" "fastmcp>=2.0,<4.0" "mcp>=1.28,<2" "chromadb>=0.6" "sentence-transformers>=3.4" "modelscope>=1.18" "pypdf>=5.1" "python-docx>=1.1" "beautifulsoup4>=4.12" "httpx>=0.27" "pytest>=8.3" "pytest-asyncio>=0.25" "anyio>=4.5" "reportlab>=4.2"
```

## 启动（开发模式）

```bash
conda activate AI_env
cd backend
Copy-Item .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY
python -m uvicorn app.main:app --reload --port 8000
```

另开终端：

```bash
cd frontend
npm install
npm run dev
# 浏览器打开 http://127.0.0.1:5173
```

## 启动（生产/单地址模式）

```bash
cd frontend && npm run build
conda activate AI_env
cd ../backend && python -m uvicorn app.main:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

## 测试

```bash
conda activate AI_env
cd backend && python -m pytest -v
cd frontend && npx vitest run
```

## 使用提示

- 对话：直接聊天；回答引用知识库时会显示来源卡片与工具调用过程。
- 知识库：在“知识库”页上传 Markdown/TXT/PDF/Word，或把文件放进 `knowledge/` 后点扫描。
- 长期记忆：对助手说“记住我叫 XX / 我喜欢简洁回答”，随后可在“长期记忆”页查看、编辑、删除。
- MCP：笔记与网页抓取由本地 MCP Server 提供；新增第三方 MCP Server 时编辑根目录 `mcp_config.json`。

## 数据位置

- 原始文档：`knowledge/`
- SQLite（会话/消息/记忆）：`data/assistant.db`
- 向量库：`data/vectorstore`
- 日志/临时数据：`data/`


