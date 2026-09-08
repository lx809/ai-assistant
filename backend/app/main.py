import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BACKEND_DIR, get_settings
from app.controllers import (
    chat_router,
    conversations_router,
    documents_router,
    health_router,
    memory_router,
)
from app.logging_setup import setup_logging
from app.models import init_db
from app.services.agent import AgentService

logger = logging.getLogger(__name__)


# 应用生命周期管理器，负责初始化和关闭数据库连接
# 初始化时创建知识库目录和数据目录
# 关闭时关闭数据库连接
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    logger.info(
        "服务启动: model=%s knowledge_dir=%s mcp_config=%s",
        settings.deepseek_model,
        settings.knowledge_dir,
        settings.mcp_config_path.exists(),
    )
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    app.state.agent_service = AgentService(settings)
    asyncio.create_task(app.state.agent_service.warm_up())
    yield
    logger.info("服务关闭")


# 创建 FastAPI 应用实例
app = FastAPI(title="AI 私人助手", lifespan=lifespan)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(memory_router)
app.include_router(conversations_router)
app.include_router(chat_router)

# 配置静态文件目录，用于服务前端资源
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
