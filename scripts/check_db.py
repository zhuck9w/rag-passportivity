"""Проверка связки embedder + db: вставить тестовый чанк, найти, удалить."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import db
from chunker import Chunk
from embedder import embed_texts
from notion_reader import Card

config.require("SUPABASE_URL", "SUPABASE_SECRET_KEY", "VOYAGE_API_KEY")

text = "[Тест — Smoke | Раздел: Проверка] тестовая запись для проверки поиска"
[vec] = embed_texts([text])
print("размер вектора:", len(vec))
assert len(vec) == config.EMBED_DIM

card = Card(page_id="smoke-test", program="Smoke", country="Тест", status="Actual",
            owners="", url="", last_edited="2026-01-01T00:00:00.000Z")
db.replace_page_chunks(card, [Chunk(content=text, section="Проверка", index=0)], [vec])

hits = db.search(vec, country="Тест", k=1)
assert hits and hits[0]["page_id"] == "smoke-test"
print("найдено:", hits[0]["content"][:50], "| similarity:", round(hits[0]["similarity"], 3))
assert "Тест" in db.list_countries()

db.delete_pages(["smoke-test"])
assert db.search(vec, country="Тест", k=1) == []
print("удалено. всё работает")
