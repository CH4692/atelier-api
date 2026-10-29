// Execute the emitted page script without adding a browser-testing dependency.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const script = require("node:fs").readFileSync(0, "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));
const account = { email: "admin@example.test", role: "admin" };
const response = (status, body = account) => ({
  status, ok: status >= 200 && status < 300, json: async () => body
});

async function exercise(origin) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: "", hidden: false, disabled: false,
      addEventListener(type, handler) { this[type] = handler; }
    });
    return elements.get(id);
  };
  let config;
  let nextResponse = response(401);
  let throwNetworkError = false;
  let pending;
  const requests = [];
  const SwaggerUIBundle = value => { config = value; };
  SwaggerUIBundle.presets = { apis: {} };
  vm.runInNewContext(script, {
    URL, SwaggerUIBundle,
    window: { location: { origin, href: origin + "/docs" } },
    document: { getElementById: element },
    fetch: (url, options) => {
      const path = new URL(url, origin + "/docs");
      assert.equal(path.origin, origin);
      assert.equal(options.credentials, "same-origin");
      assert.equal(options.cache, "no-store");
      assert.equal(options.headers?.Origin, undefined);
      assert.equal(options.headers?.Cookie, undefined);
      if (options.method === "POST") {
        assert.equal(options.headers["X-CSRF-Protection"], "1");
        assert.equal(element("login-password").value, "");
      }
      requests.push({ path: path.pathname, options });
      if (throwNetworkError) return Promise.reject(new Error("offline"));
      if (pending) return new Promise(resolve => { pending.resolve = resolve; });
      return Promise.resolve(nextResponse);
    }
  });
  await flush();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, "/api/v1/auth/me");
  assert.equal(element("session-status").textContent, "Not authenticated.");
  assert.equal(element("session-logout").hidden, true);
  const wrappers = config.plugins[0]().wrapComponents;
  assert.equal(wrappers.authorizeBtn()(), null);
  assert.equal(wrappers.authorizeOperationBtn()(), null);

  async function submit() {
    element("login-email").value = account.email;
    element("login-password").value = "test-password";
    let prevented = false;
    const completion = element("login-form").submit({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(element("login-password").value, "");
    return completion;
  }
  pending = {};
  const login = submit();
  assert.equal(element("login-submit").disabled, true);
  assert.equal(element("session-logout").disabled, true);
  const request = requests.at(-1);
  assert.equal(request.path, "/api/v1/auth/login");
  assert.equal(request.options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.options.body), { email: account.email, password: "test-password" });
  pending.resolve(response(200));
  pending = null;
  await login;
  assert.match(element("session-status").textContent, /Authenticated as admin@example.test \(admin\)/);
  assert.equal(element("session-logout").hidden, false);
  assert.equal(element("session-login").open, false);
  assert.equal(element("login-submit").disabled, false);

  for (const status of [401, 403, 422, 429, 500]) {
    nextResponse = response(status, { detail: "do not display raw server data" });
    await submit();
    assert.match(element("session-status").textContent, /^Login failed/);
    assert.doesNotMatch(element("session-status").textContent, /raw server/);
    assert.equal(element("login-submit").disabled, false);
  }
  nextResponse = response(401);
  const failure = { status: 401, url: origin + "/api/v1/customers" };
  assert.equal(config.responseInterceptor(failure), failure);
  await flush();
  assert.equal(requests.at(-1).path, "/api/v1/auth/me");
  assert.match(element("session-status").textContent, /^Session expired/);

  nextResponse = response(200);
  await submit();
  nextResponse = response(403);
  await element("session-logout").click();
  assert.match(element("session-status").textContent, /^Logout failed/);
  assert.equal(element("session-logout").hidden, false);
  nextResponse = response(204);
  await element("session-logout").click();
  assert.equal(requests.at(-1).path, "/api/v1/auth/logout");
  assert.match(element("session-status").textContent, /^Not authenticated/);
  assert.equal(element("session-logout").hidden, true);
  throwNetworkError = true;
  await submit();
  assert.match(element("session-status").textContent, /^Login failed/);
  assert.equal(element("login-submit").disabled, false);
  await element("session-logout").click();
  assert.match(element("session-status").textContent, /^Logout failed/);
}

(async () => {
  for (const origin of ["http://127.0.0.1:8000", "http://localhost:8000"]) await exercise(origin);
})().catch(error => { console.error(error); process.exitCode = 1; });
