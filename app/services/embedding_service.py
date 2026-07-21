import os

from sentence_transformers import SentenceTransformer
from starlette.concurrency import run_in_threadpool

model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    cache_folder=os.getenv("HF_HOME", "./.hf_cache")
)

def generate_embeddings_sync(texts: list[str]):
    embeddings = model.encode(texts)
    embeddings_list = embeddings.tolist()
    return embeddings_list


async def get_embeddings(texts: list[str]):
    if not texts:
        return []
    embedding_list = await run_in_threadpool(generate_embeddings_sync, texts)
    return embedding_list


async def get_embedding(text: str):
    if not text:
        return []
    result = await get_embeddings([text])
    return result[0]
