const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {}),
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(7000);
  page.on("response", (r) => {
    if (r.status() > 399) console.log(r.status(), r.url());
  });
  let errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const jwt = (claims) =>
    [
      "eyJhbGciOiJFUzI1NiJ9",
      Buffer.from(
        JSON.stringify({
          iss: "https://example.supabase.co/auth/v1",
          aud: "authenticated",
          sub: "owner",
          role: "authenticated",
          exp: Math.floor(Date.now() / 1000) + 3600,
          iat: Math.floor(Date.now() / 1000),
          aal: "aal2",
          amr: [
            { method: "password", timestamp: Math.floor(Date.now() / 1000) },
            { method: "totp", timestamp: Math.floor(Date.now() / 1000) },
          ],
          ...claims,
        }),
      ).toString("base64url"),
      "c2lnbmF0dXJl",
    ].join(".");
  const token = jwt({});
  const user = {
    id: "owner",
    email: "rishav@example.com",
    aud: "authenticated",
    role: "authenticated",
    app_metadata: {},
    user_metadata: {},
  };
  await page.addInitScript(
    ({ token, user }) =>
      localStorage.setItem(
        "sb-example-auth-token",
        JSON.stringify({
          access_token: token,
          refresh_token: "test-refresh",
          expires_at: Math.floor(Date.now() / 1000) + 3600,
          expires_in: 3600,
          token_type: "bearer",
          user,
        }),
      ),
    { token, user },
  );
  const entry = {
    id: "entry1",
    title: "Product review",
    original_text: "Rishav: I will send the updated API document tomorrow.",
    theme_id: "office",
    status: "ready",
    event_at: "2026-10-01T06:30:00Z",
    input_type: "text",
  };
  const item = {
    id: "action1",
    kind: "action",
    text: "Send the updated API document.",
    theme_id: "office",
    owner: "Rishav",
    certainty: "explicit",
    status: "active",
    due_date: "2026-10-02",
    evidence: entry.original_text,
    version: 1,
    source_entry_id: "entry1",
  };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let data = {};
    if (url.pathname === "/api/ui-config")
      data = {
        configured: true,
        supabase_url: "https://example.supabase.co",
        supabase_publishable_key: "sb_publishable_test",
      };
    else if (url.pathname === "/api/session")
      data = { status: "authenticated" };
    else if (url.pathname === "/api/entries") data = [entry];
    else if (url.pathname.endsWith("/knowledge"))
      data = {
        summary: "Rishav committed to sending the document.",
        english_text: entry.original_text,
        items: [item],
      };
    else if (url.pathname === "/api/entries/entry1") data = entry;
    else if (url.pathname === "/api/actions") data = [item];
    else if (url.pathname === "/api/chat")
      data = {
        status: "answered",
        claims: [{ text: item.text, source_ids: ["action1"] }],
        sources: [
          { ...item, source_title: entry.title, event_at: entry.event_at },
        ],
      };
    else if (url.pathname === "/api/entries/text") data = entry;
    else if (url.pathname === "/api/knowledge/action1")
      data = { ...item, status: "completed" };
    await route.fulfill({ json: data });
  });
  await page.route("https://example.supabase.co/**", (route) =>
    route.fulfill({ json: { user, all: [], totp: [], phone: [] } }),
  );
  await page.goto((process.env.UI_BASE_URL || "http://localhost:8000") + "/");
  await page.getByRole("heading", { name: "Keep the thought." }).waitFor();
  await page.screenshot({ path: "/tmp/memory-desktop.png", fullPage: true });
  await page.locator('[data-nav="Library"]').click();
  await page.getByRole("heading", { name: "Product review" }).waitFor();
  await page.locator("[data-entry]").click();
  await page.getByRole("heading", { name: "Original text" }).waitFor();
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await page.getByLabel("Reason for correction").fill("Clarify wording");
  await page.getByRole("button", { name: "Save correction" }).click();
  await page.locator("dialog").waitFor({ state: "detached" });
  await page.locator('[data-nav="Ask"]').click();
  await page.getByLabel("Ask your memory").fill("What did I commit to?");
  await page.getByRole("button", { name: "Find an answer" }).click();
  await page.getByRole("button", { name: "Source 1" }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.locator('[data-nav="Actions"]').click();
  await page.getByRole("button", { name: "Mark complete" }).waitFor();
  await page.screenshot({ path: "/tmp/memory-actions.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[data-nav="Capture"]').click();
  await page.screenshot({ path: "/tmp/memory-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Audio", exact: true }).click();
  await page
    .getByRole("button", { name: "Record audio", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "Document", exact: true }).click();
  await page.getByLabel("Document", { exact: true }).waitFor();
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw new Error("Mobile overflow");
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(
    "UI navigation, source citation, correction dialog, media tabs and mobile layout passed.",
  );
  const loginPage = await browser.newPage();
  loginPage.setDefaultTimeout(8000);
  loginPage.on("console", (m) => console.log("login:", m.text()));
  loginPage.on("pageerror", (e) => console.log("login error", e.message));
  const mfaUser = {
    ...user,
    factors: [{ id: "factor1", factor_type: "totp", status: "verified" }],
  };
  let authenticatedRequests = 0;
  await loginPage.route("**/api/**", async (r) => {
    const path = new URL(r.request().url()).pathname;
    if (path === "/api/ui-config")
      return r.fulfill({
        json: {
          configured: true,
          supabase_url: "https://example.supabase.co",
          supabase_publishable_key: "sb_publishable_test",
        },
      });
    authenticatedRequests++;
    return r.fulfill({ json: { status: "authenticated" } });
  });
  const authResponse = (aal) => ({
    access_token: jwt({ aal }),
    refresh_token: "refresh",
    token_type: "bearer",
    expires_in: 3600,
    user: mfaUser,
  });
  await loginPage.route("https://example.supabase.co/**", async (r) => {
    const path = new URL(r.request().url()).pathname;
    return r.fulfill({
      json: path.endsWith("/token")
        ? authResponse("aal1")
        : path.endsWith("/challenge")
          ? { id: "challenge1" }
          : path.endsWith("/verify")
            ? authResponse("aal2")
            : mfaUser,
    });
  });
  await loginPage.goto(
    (process.env.UI_BASE_URL || "http://localhost:8000") + "/",
  );
  await loginPage
    .getByLabel("Email", { exact: true })
    .fill("rishav@example.com");
  await loginPage
    .getByLabel("Password", { exact: true })
    .fill("testing-password");
  await loginPage.getByRole("button", { name: "Sign in", exact: true }).click();
  await loginPage.waitForTimeout(1000);
  await loginPage.getByLabel("Six-digit authenticator code").waitFor();
  if (authenticatedRequests) throw new Error("Private API accessed before MFA");
  await loginPage.getByLabel("Six-digit authenticator code").fill("123456");
  await loginPage.getByRole("button", { name: "Verify and continue" }).click();
  await loginPage.getByRole("heading", { name: "Keep the thought." }).waitFor();
  console.log(
    "Password login requires MFA before private API requests: passed.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
