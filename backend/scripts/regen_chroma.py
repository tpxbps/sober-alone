"""
清空 ChromaDB 并重新生成"旅途"剧本的向量数据。

使用方法: cd backend && PYTHONPATH=. python scripts/regen_chroma.py
"""

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BACKEND_ROOT = Path(__file__).parent.parent
CHROMA_ROOT = BACKEND_ROOT / "data" / "chroma"
DB_PATH = BACKEND_ROOT / "data" / "game_data.db"
KEEP_SCRIPT_ID = "af72e045-729c-47ca-a0ba-be11ad33bb80"  # 旅途


def wipe_chroma():
    """清空 ChromaDB 数据目录中的所有内容"""
    print(f"ChromaDB path: {CHROMA_ROOT}")

    if not CHROMA_ROOT.exists():
        print("ChromaDB directory does not exist, creating fresh.")
        CHROMA_ROOT.mkdir(parents=True, exist_ok=True)
        return

    # Delete everything inside
    for item in CHROMA_ROOT.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
            print(f"  Removed dir: {item.name}")
        else:
            item.unlink()
            print(f"  Removed file: {item.name}")

    print("ChromaDB wiped clean.\n")


async def vectorize_lvtu():
    """重新向量化旅途剧本"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    script_id = KEEP_SCRIPT_ID

    characters = []
    character_scripts = {}
    for r in c.execute(
        "SELECT character_id, name, gender, character_script FROM characters WHERE script_id=?",
        (script_id,),
    ):
        characters.append(
            {"character_id": r[0], "name": r[1], "gender": r[2]}
        )
        if r[3]:
            character_scripts[r[1]] = r[3]

    conn.close()

    print(f"Vectorizing 旅途 (script_id={script_id})")
    print(f"  Characters: {len(characters)}")
    for ci in characters:
        script_len = len(character_scripts.get(ci["name"], ""))
        print(f"    {ci['name']} ({ci['gender']}): {script_len} chars")

    from app.script_editor.services.chroma_ingest import ingest_script_async

    await ingest_script_async(
        script_id=script_id,
        characters=characters,
        character_scripts=character_scripts,
    )

    print("\nVectorization complete.")

    # Verify
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.PersistentClient(
        path=str(CHROMA_ROOT),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection_name = f"script_{script_id.replace('-', '_')}"
    try:
        col = client.get_collection(collection_name)
        print(f"  Collection '{collection_name}': {col.count()} documents")
    except Exception as e:
        print(f"  Verification failed: {e}")


async def main():
    print("=" * 60)
    print("Step 1: Wipe ChromaDB")
    print("=" * 60)
    wipe_chroma()

    print("=" * 60)
    print("Step 2: Re-vectorize 旅途")
    print("=" * 60)
    await vectorize_lvtu()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
