from dataclasses import dataclass

from app.services.rag import VectorStore


TOKENS = "番茄炒蛋怎么做需要长期记忆存于SQLite更新后的内容"


@dataclass
class FakeEmbedder:
    def _vec(self, text: str) -> list[float]:
        return [1.0 if ch in text else 0.0 for ch in TOKENS]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def test_vector_store_roundtrip(tmp_path):
    store = VectorStore(tmp_path / "chroma", FakeEmbedder())
    count = store.replace_document(1, ["番茄炒蛋需要鸡蛋和番茄", "长期记忆存于 SQLite"], "/k/a.md")
    assert count == 2

    hits = store.search("怎么做番茄炒蛋", top_k=1)
    assert len(hits) == 1
    assert hits[0].document_id == 1
    assert "番茄" in hits[0].excerpt

    store.replace_document(1, ["更新后的内容"], "/k/a.md")
    hits = store.search("怎么做番茄炒蛋", top_k=1)
    assert hits[0].excerpt == "更新后的内容"

    store.delete_document(1)
    assert store.search("番茄炒蛋", top_k=5) == []



