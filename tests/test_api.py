from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import document_service

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


def test_search_returns_cache_hit_on_repeated_query():
    unique_phrase = "cache hit unique marker phrase alpha"
    client.post(
        "/api/documents",
        json={"title": "Cache Hit Doc", "content": unique_phrase},
    )

    first_response = client.get("/api/search", params={"q": unique_phrase, "top_k": 3})
    assert first_response.status_code == 200
    assert first_response.headers["X-Cache"] == "MISS"

    second_response = client.get("/api/search", params={"q": unique_phrase, "top_k": 3})
    assert second_response.status_code == 200
    assert second_response.headers["X-Cache"] == "HIT"
    assert second_response.json() == first_response.json()


def test_search_returns_cache_miss_on_new_query():
    unique_phrase = "cache miss unique marker phrase beta never seen before"

    response = client.get("/api/search", params={"q": unique_phrase, "top_k": 3})
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"


def test_search_cache_invalidated_after_document_completion():
    unique_phrase = "invalidation unique marker phrase gamma"

    first_response = client.get("/api/search", params={"q": unique_phrase, "top_k": 5})
    assert first_response.status_code == 200
    assert first_response.headers["X-Cache"] == "MISS"

    cached_response = client.get("/api/search", params={"q": unique_phrase, "top_k": 5})
    assert cached_response.headers["X-Cache"] == "HIT"

    client.post(
        "/api/documents",
        json={"title": "Invalidation Doc", "content": unique_phrase},
    )

    after_completion_response = client.get("/api/search", params={"q": unique_phrase, "top_k": 5})
    assert after_completion_response.status_code == 200
    assert after_completion_response.headers["X-Cache"] == "MISS"

    contents = [r["content"] for r in after_completion_response.json()]
    assert any(unique_phrase in c for c in contents)


def test_search_different_top_k_produces_different_cache_key():
    unique_phrase = "top k unique marker phrase delta"
    client.post(
        "/api/documents",
        json={"title": "Top K Doc", "content": unique_phrase},
    )

    response_top_k_three = client.get("/api/search", params={"q": unique_phrase, "top_k": 3})
    assert response_top_k_three.status_code == 200
    assert response_top_k_three.headers["X-Cache"] == "MISS"

    response_top_k_five = client.get("/api/search", params={"q": unique_phrase, "top_k": 5})
    assert response_top_k_five.status_code == 200
    assert response_top_k_five.headers["X-Cache"] == "MISS"


def test_create_duplicate_completed_document_returns_409():
    content = "Unique content for duplicate check completed."

    first_resp = client.post(
        "/api/documents",
        json={"title": "Original Completed", "content": content}
    )
    assert first_resp.status_code == 202
    doc_id = first_resp.json()["id"]

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"

    duplicate_resp = client.post(
        "/api/documents",
        json={"title": "Duplicate Completed", "content": content}
    )
    assert duplicate_resp.status_code == 409
    data = duplicate_resp.json()
    assert data["detail"] == "Document with identical content already exists"
    assert data["existing_document_id"] == doc_id


def test_create_duplicate_processing_document_returns_409():
    content = "Unique content for duplicate check processing."

    with patch("app.api.documents.process_document_background", new_callable=AsyncMock):
        first_resp = client.post(
            "/api/documents",
            json={"title": "Original Processing", "content": content}
        )
        assert first_resp.status_code == 202
        doc_id = first_resp.json()["id"]

        duplicate_resp = client.post(
            "/api/documents",
            json={"title": "Duplicate Processing", "content": content}
        )
        assert duplicate_resp.status_code == 409
        data = duplicate_resp.json()
        assert data["detail"] == "Document with identical content already exists"
        assert data["existing_document_id"] == doc_id


def test_different_content_creates_new_document_successfully():
    resp_one = client.post(
        "/api/documents",
        json={"title": "Doc One", "content": "Content number one."}
    )
    resp_two = client.post(
        "/api/documents",
        json={"title": "Doc Two", "content": "Content number two."}
    )

    assert resp_one.status_code == 202
    assert resp_two.status_code == 202
    assert resp_one.json()["id"] != resp_two.json()["id"]


def test_document_fields_and_latency_lifecycle():
    content = "Lifecycle test content for hashes and latencies."

    with patch("app.api.documents.process_document_background", new_callable=AsyncMock):
        create_resp = client.post(
            "/api/documents",
            json={"title": "Lifecycle Doc", "content": content}
        )
        doc_id = create_resp.json()["id"]

        processing_detail = client.get(f"/api/documents/{doc_id}").json()

        assert processing_detail.get("chunking_time_ms") is None
        assert processing_detail.get("embedding_time_ms") is None
        assert processing_detail.get("total_processing_time_ms") is None

    completed_resp = client.post(
        "/api/documents",
        json={"title": "Lifecycle Doc Actual", "content": "Completely new distinct text to process."}
    )
    comp_doc_id = completed_resp.json()["id"]

    completed_detail = client.get(f"/api/documents/{comp_doc_id}").json()
    assert completed_detail["status"] == "completed"

    assert completed_detail["chunking_time_ms"] is not None
    assert completed_detail["chunking_time_ms"] > 0

    assert completed_detail["embedding_time_ms"] is not None
    assert completed_detail["embedding_time_ms"] > 0

    assert completed_detail["total_processing_time_ms"] is not None
    assert completed_detail["total_processing_time_ms"] > 0

    expected_total = completed_detail["chunking_time_ms"] + completed_detail["embedding_time_ms"]
    assert completed_detail["total_processing_time_ms"] == expected_total


def test_content_hash_unique_constraint_returns_409_on_race():
    """
    Simulates two near-simultaneous identical POSTs both passing the application-level
    get_document_by_hash() pre-check (because neither has committed yet when the other
    checks). get_document_by_hash is mocked to return None for the first two calls —
    the pre-check on request 1 and the pre-check on request 2 — so both requests reach
    db.commit(). The first commit succeeds and creates the row. The second commit hits
    the real UNIQUE constraint on documents.content_hash (added in
    add_unique_constraint_to_content_hash) and raises IntegrityError, which
    create_document() catches, rolls back, and turns into a 409 — using a *real*
    (unmocked) get_document_by_hash() call to resolve existing_document_id, which is why
    the mock only forces None for the first two calls and falls through to the real
    function afterwards.
    """
    content = "Race condition content for unique constraint test."

    real_get_document_by_hash = document_service.get_document_by_hash
    call_count = {"n": 0}

    def fake_get_document_by_hash(db, content_hash):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return None
        return real_get_document_by_hash(db, content_hash)

    with patch("app.api.documents.get_document_by_hash", side_effect=fake_get_document_by_hash):
        first_resp = client.post(
            "/api/documents",
            json={"title": "Race First", "content": content}
        )
        assert first_resp.status_code == 202
        doc_id = first_resp.json()["id"]

        second_resp = client.post(
            "/api/documents",
            json={"title": "Race Second", "content": content}
        )

    assert call_count["n"] == 3
    assert second_resp.status_code == 409
    data = second_resp.json()
    assert data["detail"] == "Document with identical content already exists"
    assert data["existing_document_id"] == doc_id


def test_content_hash_is_correctly_stored_after_creation():
    content = "Content hash verification test content."

    response = client.post(
        "/api/documents",
        json={"title": "Hash Check Doc", "content": content}
    )
    assert response.status_code == 202

    expected_hash = document_service.hash_content(content)

    from app.database.db import get_db
    db = next(get_db())
    try:
        stored_doc = document_service.get_document_by_hash(db, expected_hash)
        assert stored_doc is not None
        assert stored_doc.content_hash == expected_hash
    finally:
        db.close()


def test_system_live_always_returns_200():
    response = client.get("/system/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_system_ready_returns_200_when_all_dependencies_available():
    with patch("app.api.system.check_database", return_value="ok"), \
            patch("app.api.system.check_redis", return_value="ok"), \
            patch("app.api.system.check_embedding_model", new_callable=AsyncMock, return_value="ok"):
        response = client.get("/system/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"


def test_system_ready_returns_503_when_database_unreachable():
    with patch("app.api.system.check_database", return_value="unreachable"), \
            patch("app.api.system.check_redis", return_value="ok"), \
            patch("app.api.system.check_embedding_model", new_callable=AsyncMock, return_value="ok"):
        response = client.get("/system/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unavailable"


def test_system_ready_returns_503_when_redis_unreachable():
    with patch("app.api.system.check_database", return_value="ok"), \
            patch("app.api.system.check_redis", return_value="unreachable"), \
            patch("app.api.system.check_embedding_model", new_callable=AsyncMock, return_value="ok"):
        response = client.get("/system/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unavailable"


def test_system_ready_checks_structure_is_correct_in_both_cases():
    with patch("app.api.system.check_database", return_value="ok"), \
            patch("app.api.system.check_redis", return_value="ok"), \
            patch("app.api.system.check_embedding_model", new_callable=AsyncMock, return_value="ok"):
        response_ok = client.get("/system/ready")
        data_ok = response_ok.json()
        assert "checks" in data_ok
        assert data_ok["checks"] == {
            "database": "ok",
            "redis": "ok",
            "embedding_model": "ok"
        }

    with patch("app.api.system.check_database", return_value="unreachable"), \
            patch("app.api.system.check_redis", return_value="unreachable"), \
            patch("app.api.system.check_embedding_model", new_callable=AsyncMock, return_value="unreachable"):
        response_err = client.get("/system/ready")
        data_err = response_err.json()
        assert "checks" in data_err
        assert data_err["checks"] == {
            "database": "unreachable",
            "redis": "unreachable",
            "embedding_model": "unreachable"
        }


def test_document_metadata_is_stored_and_returned_via_get_by_id():
    metadata = {"source": "docs.fastapi.tiangolo.com", "author": "tiangolo"}

    create_resp = client.post(
        "/api/documents",
        json={"title": "Metadata Doc", "content": "Content for metadata storage test.", "metadata": metadata}
    )
    assert create_resp.status_code == 202
    doc_id = create_resp.json()["id"]

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["metadata"] == metadata


def test_document_without_metadata_returns_null():
    create_resp = client.post(
        "/api/documents",
        json={"title": "No Metadata Doc", "content": "Content with no metadata supplied at all."}
    )
    assert create_resp.status_code == 202
    doc_id = create_resp.json()["id"]

    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["metadata"] is None


def test_search_results_include_document_metadata():
    unique_phrase = "metadata search unique marker phrase epsilon"
    metadata = {"source": "unit-test", "tag": "epsilon"}

    client.post(
        "/api/documents",
        json={"title": "Metadata Search Doc", "content": unique_phrase, "metadata": metadata}
    )

    response = client.get("/api/search", params={"q": unique_phrase})
    assert response.status_code == 200
    results = response.json()
    matching = [r for r in results if unique_phrase in r["content"]]
    assert len(matching) > 0
    assert matching[0]["metadata"] == metadata


def test_create_document_invalid_metadata_type_returns_422():
    response = client.post(
        "/api/documents",
        json={
            "title": "Bad Metadata Doc",
            "content": "Content with an invalid metadata type.",
            "metadata": "this should be a dict, not a string"
        }
    )
    assert response.status_code == 422
