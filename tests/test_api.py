from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_post_document_returns_202_processing():
    payload = {"title": "Valid Title", "content": "Valid Content"}
    response = client.post("/api/documents", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "processing"
    assert data["chunk_count"] == 0
    assert "id" in data
    assert data["title"] == "Valid Title"


def test_get_document_after_processing_returns_completed_with_chunk_count():
    response = client.post(
        "/api/documents",
        json={
            "title": "Completed Doc",
            "content": "FastAPI is a modern, fast web framework for building APIs with Python.",
        },
    )
    doc_id = response.json()["id"]

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "completed"
    assert data["chunk_count"] > 0


def test_failed_processing_sets_status_failed():
    with patch(
            "app.services.document_service.get_embeddings",
            side_effect=Exception("embedding model crashed"),
    ):
        response = client.post(
            "/api/documents",
            json={"title": "Doomed Doc", "content": "This will fail during embedding."},
        )
    doc_id = response.json()["id"]

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "failed"
    assert data["chunk_count"] == 0


def test_search_excludes_processing_documents():
    unique_phrase = "zzqxv unmistakable marker phrase for processing exclusion test"

    with patch(
            "app.api.documents.process_document_background",
            new_callable=AsyncMock,
    ):
        client.post(
            "/api/documents",
            json={"title": "Stuck Processing Doc", "content": unique_phrase},
        )

    response = client.get("/api/search", params={"q": unique_phrase})
    assert response.status_code == 200
    results = response.json()
    contents = [r["content"] for r in results]
    assert not any(unique_phrase in c for c in contents)


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


def test_search_scores_are_sorted_descending():
    client.post(
        "/api/documents",
        json={
            "title": "Python",
            "content": (
                "Python programming language. "
                "FastAPI framework. SQLAlchemy ORM."
            ),
        },
    )

    response = client.get(
        "/api/search",
        params={"q": "FastAPI framework"}
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert results[0]["score"] > 0.5
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)


def test_create_document_empty_content_returns_422():
    response = client.post(
        "/api/documents",
        json={
            "title": "Test",
            "content": "",
        },
    )
    assert response.status_code == 422
    assert (
            "Content cannot be empty or contain only whitespaces"
            in str(response.json())
    )


def test_create_document_whitespace_content_returns_422():
    response = client.post(
        "/api/documents",
        json={
            "title": "Test",
            "content": "   ",
        },
    )

    assert response.status_code == 422

    assert (
            "Content cannot be empty or contain only whitespaces"
            in str(response.json())
    )


def test_exception_handler_returns_expected_format():
    with patch(
            "app.api.search.get_embedding",
            side_effect=Exception("boom")
    ):
        response = client.get(
            "/api/search",
            params={"q": "test"}
        )

    assert response.status_code == 500

    data = response.json()

    assert data["detail"] == "Internal Server Error"

    assert "request_id" in data
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0

    assert "boom" not in str(data)
    assert "traceback" not in str(data).lower()
