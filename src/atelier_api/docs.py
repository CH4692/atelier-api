"""Serve development Swagger UI with browser-managed session authentication."""

from starlette.requests import Request
from starlette.responses import HTMLResponse


async def swagger_ui(request: Request) -> HTMLResponse:
    """Add the CSRF marker without reading cookies or overriding browser Origin.

    A real JavaScript function is needed for requestInterceptor; FastAPI's
    swagger_ui_parameters serializes values as JSON and cannot express it.
    Relative URLs keep documentation and API requests on the browser's host.
    """
    return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
  <title>Atelier API - Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.0/swagger-ui.css">
  <style>
    .session-panel { max-width: 1400px; margin: 24px auto; padding: 20px;
      border: 1px solid #d3d3d3; border-radius: 6px; font: 16px sans-serif; }
    .session-panel summary { cursor: pointer; font-weight: 600; }
    .session-panel form { display: flex; flex-wrap: wrap; align-items: end; gap: 16px; }
    .session-panel label { display: grid; gap: 6px; }
    .session-panel input, .session-panel button { padding: 8px; font: inherit; }
  </style>
</head>
<body>
  <section class="session-panel" aria-label="Browser session">
    <p id="session-status" role="status" aria-live="polite">Checking session…</p>
    <details id="session-login">
      <summary>Log in with email and password</summary>
      <p>Use your existing workshop account. Your browser manages the session cookie.</p>
      <form id="login-form" method="post" action="./api/v1/auth/login">
        <label>Email <input id="login-email" type="email" autocomplete="username" required></label>
        <label>Password <input id="login-password" type="password"
          autocomplete="current-password" required></label>
        <button id="login-submit" type="submit">Log in</button>
      </form>
    </details>
    <button id="session-logout" type="button" hidden>Log out</button>
  </section>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.0/swagger-ui-bundle.js"></script>
  <script>
    const status = document.getElementById("session-status");
    const loginSection = document.getElementById("session-login");
    const loginForm = document.getElementById("login-form");
    const email = document.getElementById("login-email");
    const password = document.getElementById("login-password");
    const loginButton = document.getElementById("login-submit");
    const logoutButton = document.getElementById("session-logout");
    let authenticated = false;
    let busy = false;

    function showAccount(account) {
      authenticated = true;
      status.textContent = `Authenticated as ${account.email} (${account.role}).`;
      loginSection.open = false;
      logoutButton.hidden = false;
    }

    function showSignedOut(message) {
      authenticated = false;
      status.textContent = message;
      logoutButton.hidden = true;
    }

    function authRequest(action, options = {}) {
      return fetch(`./api/v1/auth/${action}`, {
        credentials: "same-origin",
        cache: "no-store",
        ...options
      });
    }

    async function checkSession() {
      try {
        const response = await authRequest("me");
        if (response.ok) {
          showAccount(await response.json());
        } else if (response.status === 401) {
          showSignedOut(authenticated ? "Session expired. Please log in again." : "Not authenticated.");
        } else {
          status.textContent = "Unable to check authentication status.";
        }
      } catch {
        status.textContent = "Unable to reach the API. Check your connection.";
      }
    }

    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = JSON.stringify({ email: email.value, password: password.value });
      password.value = "";
      if (busy) return;
      busy = true;
      loginButton.disabled = logoutButton.disabled = true;
      status.textContent = "Logging in…";
      try {
        const response = await authRequest("login", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
          body
        });
        if (response.ok) {
          showAccount(await response.json());
        } else {
          const messages = {
            401: "Login failed. Invalid credentials.",
            403: "Login failed. Request forbidden; check the configured allowed origins.",
            422: "Login failed. Check your email and password.",
            429: "Login failed. Too many attempts; try again later."
          };
          status.textContent = messages[response.status] || "Login failed. Please try again later.";
        }
      } catch {
        status.textContent = "Login failed. Unable to reach the API.";
      } finally {
        busy = false;
        loginButton.disabled = logoutButton.disabled = false;
      }
    });

    logoutButton.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      loginButton.disabled = logoutButton.disabled = true;
      try {
        const response = await authRequest("logout", {
          method: "POST", headers: { "X-CSRF-Protection": "1" }
        });
        if (response.ok) {
          showSignedOut("Not authenticated. Logged out successfully.");
        } else {
          status.textContent = "Logout failed. Your session may still be active; try again.";
        }
      } catch {
        status.textContent = "Logout failed. Unable to reach the API.";
      } finally {
        busy = false;
        loginButton.disabled = logoutButton.disabled = false;
      }
    });

    const ui = SwaggerUIBundle({
      url: "./openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      displayRequestDuration: true,
      presets: [SwaggerUIBundle.presets.apis],
      // Keep cookie security in OpenAPI, but replace manual token-entry controls.
      plugins: [() => ({ wrapComponents: {
        authorizeBtn: () => () => null,
        authorizeOperationBtn: () => () => null
      } })],
      responseInterceptor: (response) => {
        if (!busy && ((response.status === 401 && authenticated) ||
            (response.ok && /[/]auth[/](login|logout)$/.test(new URL(response.url, window.location.href).pathname)))) {
          void checkSession();
        }
        return response;
      },
      requestInterceptor: (request) => {
        const url = new URL(request.url, window.location.href);
        if (url.origin === window.location.origin) {
          request.credentials = "same-origin";
          // Swagger's OpenAPI fetch can omit the method; Fetch defaults to GET.
          const method = (request.method || "GET").toUpperCase();
          if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
            request.headers["X-CSRF-Protection"] = "1";
          }
        }
        return request;
      }
    });
    void checkSession();
  </script>
</body>
</html>""")
