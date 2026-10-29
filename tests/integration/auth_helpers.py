"""Share deterministic authentication inputs and login requests."""

ORIGIN = "https://app.example.test"
PASSWORD = "Workshop-test-password!42"
HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


def sign_in(client, name="employee", password=PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": f"{name}@example.com", "password": password},
    )
