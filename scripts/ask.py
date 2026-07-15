"""Консольная проверка: что достаёт поиск (и, с --answer, полный ответ)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from retrieval import retrieve

parser = argparse.ArgumentParser()
parser.add_argument("question")
parser.add_argument("--answer", action="store_true", help="сгенерировать полный ответ")
args = parser.parse_args()

config.require("SUPABASE_URL", "SUPABASE_SECRET_KEY", "VOYAGE_API_KEY", "ANTHROPIC_API_KEY")
fragments, query, countries, topic, intent = retrieve(args.question, history=[])
print(f"Переформулировано: {query!r}\nСтраны: {countries}\nТема: {topic}\nIntent: {intent}")

if intent == "smalltalk":
    from answer import pick_smalltalk_reply
    print("\n--- Ответ (детерминированный) ---")
    print(pick_smalltalk_reply(args.question))
    raise SystemExit(0)

if intent == "meta":
    import db
    from answer import about_text
    print("\n--- Ответ (детерминированный) ---")
    print(about_text(db.list_countries()))
    raise SystemExit(0)

for f in fragments:
    print(f"  {f['similarity']:.3f}  {f['content'].splitlines()[0]}")

if args.answer:
    from answer import answer
    print("\n--- Ответ ---")
    print(answer(args.question, fragments, [], resolved=query))
