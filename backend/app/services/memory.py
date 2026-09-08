import json
import logging
import re

from langchain_openai import ChatOpenAI

from app.config import Settings
from app.models import MemoryRepo

logger = logging.getLogger(__name__)

# 定义了记忆条目的标准化分类体系
ALLOWED_TYPES = {"identity", "preference", "ongoing", "decision", "general"}


def summarize(repo: MemoryRepo) -> str:
    return repo.summary()


# 从 LLM 的非结构化响应中安全地提取 JSON 数组，实现了三层容错机制
def _extract_json_array(content: str) -> list[dict]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not match:
        logger.warning("记忆提炼: LLM 输出中未找到 JSON 数组，已忽略。输出片段: %.200s", text)
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


# 记忆提取器，负责从对话中提取长期记忆
# 包括从对话中提炼 JSON 数组、解析 JSON 数组、保存记忆条目等操作
class MemoryExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    # 从对话中提取长期记忆
    # 包括从对话中提炼 JSON 数组、解析 JSON 数组、保存记忆条目等操作
    # 返回保存的条数
    # 可选参数：对话ID、用户文本、助手文本
    def extract_and_save(self, conversation_id: str, user_text: str, assistant_text: str) -> int:
        """对话结束后提炼长期记忆。无 API Key 时静默跳过，返回 0。"""
        if not self.settings.deepseek_api_key:
            return 0
        repo = MemoryRepo(self.settings.db_path)
        existing = [entry["content"] for entry in repo.list_entries()]
        existing_block = "\n".join(f"- {text}" for text in existing) or "（无）"
        prompt = (
            "从下面的对话中提炼值得长期记住的用户事实。"
            "只输出 JSON 数组，不要输出其他文字。每项格式为 {\"type\": \"identity|preference|ongoing|decision|general\", \"content\": \"一句话\"}。"
            "原则：只保存高置信度、有长期价值的内容；如果某条与已记忆内容含义重复，就丢弃它；不要保存随口的闲聊。\n\n"
            f"已有记忆：\n{existing_block}\n\n"
            f"对话：\n用户：{user_text[:2000]}\n助手：{assistant_text[:2000]}"
        )
        model = ChatOpenAI(
            model=self.settings.deepseek_model,
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
            temperature=0,
        )
        response = model.invoke([{"role": "user", "content": prompt}])
        saved = 0
        for item in _extract_json_array(str(response.content)):
            type_ = str(item.get("type", "general"))
            content = str(item.get("content", "")).strip()
            if type_ not in ALLOWED_TYPES or not content or len(content) > 200:
                continue
            if content in existing or content in [e["content"] for e in repo.list_entries()]:
                continue
            repo.create_entry(type_, content, source_conversation_id=conversation_id, manual=False)
            existing.append(content)
            saved += 1
        return saved



