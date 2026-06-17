import asyncio
from app.database.db import SessionLocal
from app.database.models import Document, Chunk
from app.services.chunking_service import chunk_text
from app.services.embedding_service import get_embeddings

DATASET = [
    {
        "title": "Culinary: Cooking authentic Ukrainian borscht",
        "content": "For the perfect borscht you need high quality beef on the bone. The meat is cooked for about two hours on low heat, constantly removing the foam. Then sautéed beets with lemon juice, potatoes, fresh cabbage, and fried onions with carrots are added. At the very end, garlic mashed with old lard is put in, and it is left to infuse for 20 minutes."
    },
    {
        "title": "Programming: Python language fundamentals and ecosystem",
        "content": "The Python programming language gained popularity due to its concise syntax and powerful ecosystem of libraries. For working with databases, SQLAlchemy or Tortoise ORM are often used, and for creating high performance APIs, the FastAPI framework is preferred. In the field of artificial intelligence, PyTorch, TensorFlow, and Hugging Face libraries have become the standard."
    },
    {
        "title": "Sports: Evolution of modern European football",
        "content": "Modern football requires maximum physical conditioning and tactical flexibility from players. The high pressing tactic, popularized by German managers, forces teams to defend right in the opponent's half of the pitch. Ball control in the midfield and fast wing attacks involving full-backs play a crucial role."
    },
    {
        "title": "History: The Renaissance era in Italian architecture",
        "content": "The Renaissance brought back strict classical proportions, symmetry, and the order system to European architecture. Filippo Brunelleschi erected the monumental dome of the Santa Maria del Fiore cathedral in Florence, marking the beginning of a new era. Building spaces became centered, logical, and proportioned to human scale, unlike Gothic design."
    }
]


async def main():
    db = SessionLocal()
    try:
        for i in range(1, 51):
            template = DATASET[(i - 1) % len(DATASET)]
            title = f"{template['title']} (Instance #{i})"
            content = f"Document ID-{i}. {template['content']} Additional unique search token: doc_token_{i}."

            db_document = Document(title=title, content=content)
            db.add(db_document)
            db.flush()

            chunked_payload = chunk_text(content)
            vectors = await get_embeddings(chunked_payload)

            chunks_to_insert = [
                Chunk(content=c_content, document_id=db_document.id, embedding=vector)
                for c_content, vector in zip(chunked_payload, vectors)
            ]
            db.add_all(chunks_to_insert)
            db.commit()
            print(f"Inserted document {i}/50 with {len(chunked_payload)} chunks.")
    except Exception as e:
        db.rollback()
        print(f"Execution failed: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
