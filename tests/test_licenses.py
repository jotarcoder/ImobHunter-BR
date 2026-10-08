from imobhunter.server.licenses import hash_device_id, hash_license_key, new_license_key, verify_session_marker


def test_license_key_format_and_hashing():
    key = new_license_key()
    assert key.startswith("IMH-")
    assert len(key.split("-")) == 5
    assert hash_license_key(key) == hash_license_key(key)
    assert hash_license_key(key) != hash_license_key(key + "x")


def test_device_hash_is_one_way_stable():
    assert hash_device_id("machine-123") == hash_device_id("machine-123")
    assert hash_device_id("machine-123") != hash_device_id("machine-456")


def test_admin_panel_is_served():
    from fastapi.testclient import TestClient
    from imobhunter.server.main import app

    response = TestClient(app).get("/admin/")
    assert response.status_code == 200
    assert "Central de licenças" in response.text
    assert "juninhoovf@gmail.com" in response.text
