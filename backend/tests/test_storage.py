from app.config import get_settings
from app.models import init_db
from app.models import ConversationRepo, DocumentRepo, MemoryRepo


def test_conversation_roundtrip():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "你好")
    repo.append_message(conv_id, "assistant", "你好，我是助手")

    convs = repo.list_conversations()
    assert convs[0]["id"] == conv_id
    assert [m["role"] for m in repo.list_messages(conv_id)] == ["user", "assistant"]


def test_memory_and_document_repos():
    settings = get_settings()
    init_db(settings.db_path)
    memory = MemoryRepo(settings.db_path)
    memory.create_entry("preference", "喜欢简洁回答", manual=True)
    entries = memory.list_entries()
    assert len(entries) == 1
    assert "喜欢简洁回答" in memory.summary()
    assert memory.delete_entry(entries[0]["id"]) is True
    assert memory.list_entries() == []

    docs = DocumentRepo(settings.db_path)
    doc_id = docs.register("a.md", "a.md", "md", "hash-1")
    docs.set_status(doc_id, "completed", chunk_count=2)
    row = docs.get_by_path("a.md")
    assert row["status"] == "completed"
    assert row["chunk_count"] == 2
    assert len(docs.list_documents()) == 1




def test_delete_conversation_removes_all_messages():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "这条会一起删")
    repo.append_message(conv_id, "assistant", "这条也会一起删")

    assert repo.delete_conversation(conv_id) is True
    assert repo.get(conv_id) is None
    assert repo.list_messages(conv_id) == []
    assert repo.delete_conversation(conv_id) is False
