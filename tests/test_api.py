from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_post_document_returns_201_with_chunk_count():
    payload = {"title": "Valid Title", "content": "Valid Content"}
    response = client.post("/api/documents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "chunk_count" in data
    assert isinstance(data["chunk_count"], int)
    assert data["chunk_count"] > 0


def test_search_returns_list_with_correct_structure():
    client.post("/api/documents", json={
        "title": "Search Test",
        "content": "FastAPI is a modern web framework for building APIs"
    })
    response = client.get("/api/search", params={"q": "web framework"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "chunk_id" in first
    assert "document_title" in first
    assert "content" in first
    assert "score" in first