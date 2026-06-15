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


def test_get_documents_list_returns_200():
    response = client.get("/api/documents", params={"limit": 5, "offset": 0})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        first_document = data[0]
        assert "id" in first_document
        assert "title" in first_document
        assert "chunk_count" in first_document


def test_get_document_by_id_returns_200():
    create_resp = client.post("/api/documents", json={"title": "Temp", "content": "Some content here"})
    doc_id = create_resp.json()["id"]

    response = client.get(f"/api/documents/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == doc_id
    assert data["content"] == "Some content here"


def test_get_document_by_id_returns_404():
    non_existent_id = 999999
    response = client.get(f"/api/documents/{non_existent_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


def test_delete_document_returns_204():
    create_resp = client.post("/api/documents", json={"title": "To Delete", "content": "Delete me"})
    doc_id = create_resp.json()["id"]

    response = client.delete(f"/api/documents/{doc_id}")
    assert response.status_code == 204


def test_delete_document_returns_404():
    non_existent_id = 999999
    response = client.delete(f"/api/documents/{non_existent_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
