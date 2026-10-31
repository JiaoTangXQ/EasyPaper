def test_register(client):
    response = client.post("/api/auth/register", json={"email": "test@test.com", "password": "test-password-123"})
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@test.com"
    assert "id" in data


def test_register_duplicate(client):
    client.post("/api/auth/register", json={"email": "dup@test.com", "password": "test-password-123"})
    response = client.post("/api/auth/register", json={"email": "dup@test.com", "password": "test-password-123"})
    assert response.status_code == 400


def test_login(client):
    client.post("/api/auth/register", json={"email": "login@test.com", "password": "test-password-123"})
    response = client.post("/api/auth/login", data={"username": "login@test.com", "password": "test-password-123"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"email": "wrong@test.com", "password": "test-password-123"})
    response = client.post("/api/auth/login", data={"username": "wrong@test.com", "password": "badpass"})
    assert response.status_code == 400


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
