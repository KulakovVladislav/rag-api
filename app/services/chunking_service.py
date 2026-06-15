def chunk_text(text: str, chunk_size: int = 200, overlap: int = 50):
    if overlap >= chunk_size:
        raise ValueError("invalid overlap")
    if chunk_size <= 0:
        raise ValueError("invalid chunk size")
    start = 0
    chunks = []
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks
