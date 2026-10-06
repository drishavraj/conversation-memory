const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
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
  const taskList = ['transcription','translation','summary','extraction','answer'];
  const aiSettings = {
    version:0,
    defaults:Object.fromEntries(taskList.map(task=>[task,{provider:'gemini',model:'configured-gemini'}])),
    catalog:[
      {provider:'gemini',model:'configured-gemini',tasks:taskList,available:true,key_variable:'GEMINI_API_KEY',note:'Original-language audio and structured text.'},
      {provider:'openai',model:'gpt-4.1-mini',tasks:taskList.slice(1),available:true,key_variable:'OPENAI_API_KEY',note:'Structured text.'},
      {provider:'sarvam',model:'saaras:v4',tasks:['transcription'],available:true,key_variable:'SARVAM_API_KEY',note:'Mixed-language batch transcription.'}
    ],
    embedding:{model:'configured-embedding'}
  };
  let uploadedOptions, failMutation = true, failUpload = true;
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
        environment: "development",
        configured: true,
        supabase_url: "https://example.supabase.co",
        supabase_publishable_key: "sb_publishable_test",
      };
    else if (url.pathname === "/api/ai-settings") {
      if(route.request().method()==='PUT') {
        const body=route.request().postDataJSON();
        if(body.expected_version!==aiSettings.version)throw new Error('Settings version missing');
        aiSettings.defaults=body.defaults;aiSettings.version++;
      }
      data=aiSettings;
    }
    else if (url.pathname === "/api/entries/upload") {
      const body=route.request().postData();
      if(!body.includes('saaras:v4') || !body.includes('"en","hi","mr"'))throw new Error('Upload lost processing choices');
      await new Promise(resolve => setTimeout(resolve, 500));
      if (failUpload) { failUpload=false; return route.fulfill({status:503,json:{detail:'Test upload failure'}}); }
      uploadedOptions=true; data=entry;
    }
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
    else if (url.pathname === "/api/actions") {
      await new Promise(resolve => setTimeout(resolve, 400));
      data = [item,{...item, id:'action2', text:'Unchanged task', status:'active'}].filter(i=>i.status === url.searchParams.get('status'));
    }
    else if (url.pathname === "/api/chat")
      data = {
        status: "answered",
        claims: [{ text: item.text, source_ids: ["action1"] }],
        sources: [
          { ...item, source_title: entry.title, event_at: entry.event_at },
        ],
      };
    else if (url.pathname === "/api/entries/text") data = entry;
    else if (url.pathname === "/api/knowledge/action1") {
      const body=route.request().postDataJSON();
      if(body.status) {
        await new Promise(resolve=>setTimeout(resolve,400));
        if(failMutation) {failMutation=false;return route.fulfill({status:503,json:{detail:'Test update failure'}});}
        item.status=body.status; item.version++;
      }
      data = item;
    }
    await route.fulfill({ json: data });
  });
  await page.route("https://example.supabase.co/**", (route) =>
    route.fulfill({ json: { user, all: [], totp: [], phone: [] } }),
  );
  await page.goto((process.env.UI_BASE_URL || "http://localhost:8000") + "/");
  await page.getByRole("heading", { name: "To-dos", exact:true }).waitFor();
  await page.getByRole("heading", { name: "Overdue" }).waitFor();
  await page.locator('#todo-action2 summary').click();
  await page.evaluate(()=>{window.unchangedRow=document.querySelector('#todo-action2');window.actionsHost=document.querySelector('#actionRows');});
  const complete=page.getByRole('button',{name:'Complete: Send the updated API document.'});
  await complete.click();
  await page.locator('#todo-action1 [aria-busy="true"]').waitFor();
  await page.getByText('Test update failure',{exact:true}).waitFor();
  if(await complete.isDisabled())throw new Error('Failed completion cannot be retried');
  await complete.click();
  await page.locator('#todo-action1').waitFor({state:'detached'});
  if(!await page.evaluate(()=>window.unchangedRow===document.querySelector('#todo-action2') && window.actionsHost===document.querySelector('#actionRows') && document.querySelector('#todo-action2 details').open))throw new Error('Completion replaced unrelated content');
  item.status='active';
  await page.screenshot({path:"/tmp/todos-light.png",fullPage:true});
  await page.locator('[data-nav="Capture"]').click();
  await page.locator('#saveCapture:not([disabled])').waitFor();
  await page.locator('.env-banner').getByText('DEVELOPMENT · Test environment').waitFor();
  await page.locator('#settingsNav').click();
  await page.getByLabel('Colour mode').selectOption('dark');
  if(await page.locator('html').getAttribute('data-appearance')!=='dark')throw new Error('Dark mode failed');
  await page.reload();
  await page.getByRole('heading',{name:'To-dos',exact:true}).waitFor();
  if(await page.locator('html').getAttribute('data-appearance')!=='dark')throw new Error('Dark preference not persisted');
  await page.screenshot({path:'/tmp/todos-dark.png',fullPage:true});
  await page.locator('#settingsNav').click();
  await page.getByText('AI model defaults',{exact:true}).click();
  await page.getByLabel('Summary', {exact:true}).selectOption('openai|gpt-4.1-mini');
  await page.getByRole('button',{name:'Save defaults',exact:true}).click();
  await page.getByText('Defaults saved. New uploads will use these choices.').waitFor();
  await page.screenshot({ path: "/tmp/memory-settings.png", fullPage: true });
  await page.locator('[data-nav="Capture"]').click();
  await page.locator('#saveCapture:not([disabled])').waitFor();
  if(await page.locator('#capture-summary').inputValue()!=='openai|gpt-4.1-mini')throw new Error('Default did not reach capture');
  await page.screenshot({ path: "/tmp/memory-desktop.png", fullPage: true });
  await page.locator('[data-nav="Library"]').click();
  await page.getByRole("heading", { name: "Product review" }).waitFor();
  entry.status='processing';
  entry.processing_config={models:{summary:{provider:'gemini',model:'test-model'}}};
  entry.completed_stages=[];
  await page.locator("[data-entry]").click();
  await page.getByRole("heading", { name: "Original text" }).waitFor();
  await page.locator('#processingDetails summary').click();
  await page.evaluate(()=>{window.originalSection=document.querySelector('#entryOriginal');window.processingDisclosure=document.querySelector('#processingDetails');});
  entry.completed_stages=['summary'];
  await page.getByText(/1 processing stages completed/).waitFor();
  if(!await page.evaluate(()=>window.originalSection===document.querySelector('#entryOriginal') && window.processingDisclosure===document.querySelector('#processingDetails') && window.processingDisclosure.open))throw new Error('Polling replaced content or collapsed processing details');
  entry.status='ready';
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await page.getByLabel("Reason for correction").fill("Clarify wording");
  await page.getByRole("button", { name: "Save correction" }).click();
  await page.locator("dialog").waitFor({ state: "detached" });
  await page.locator('[data-nav="Library"]').click();
  await page.locator('[data-view="Ask"]').click();
  await page.getByLabel("Ask your memory").fill("What did I commit to?");
  await page.getByRole("button", { name: "Find an answer" }).click();
  await page.getByRole("button", { name: "Source 1" }).click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.locator('[data-nav="Actions"]').click();
  await page.getByRole("button", { name: "Complete: Send the updated API document." }).waitFor();
  await page.screenshot({ path: "/tmp/memory-actions.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[data-nav="Capture"]').click();
  await page.screenshot({ path: "/tmp/memory-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Record / audio", exact: true }).click();
  await page
    .getByRole("button", { name: "Record conversation", exact: true })
    .waitFor();
  await page.locator('#saveCapture:not([disabled])').waitFor();
  await page.getByText('Processing options', {exact:true}).click();
  await page.getByLabel('Transcription',{exact:true}).selectOption('sarvam|saaras:v4');
  for(const name of ['English','Hindi','Marathi'])await page.getByLabel(name,{exact:true}).check();
  await page.getByText('Title & date',{exact:true}).click();
  await page.getByLabel('Title (optional)',{exact:true}).fill('Mixed meeting');
  await page.getByText('Upload an audio file',{exact:true}).click();
  await page.getByLabel('Audio file',{exact:true}).setInputFiles({name:'meeting.wav',mimeType:'audio/wav',buffer:Buffer.from('RIFF0000WAVEaudio')});
  await page.screenshot({path:'/tmp/memory-model-mobile.png',fullPage:true});
  await page.getByLabel('Theme',{exact:true}).selectOption('office');
  await page.locator('#saveCapture').click();
  await page.locator('#captureResult progress').waitFor();
  await page.getByText('Test upload failure',{exact:true}).waitFor();
  if(!await page.getByLabel('Audio file',{exact:true}).evaluate(el=>el.files.length===1))throw new Error('Failed upload lost file');
  await page.locator('#saveCapture').click();
  await page.locator('#captureResult progress').waitFor();
  await page.getByRole('heading',{name:'Original text'}).waitFor();
  if(!uploadedOptions)throw new Error('Upload not submitted');
  await page.locator('[data-nav="Capture"]').click();
  await page.locator('#record').click();
  await page.getByText('Recording · 0:00',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.getByRole('button',{name:'Resume',exact:true}).waitFor();
  await page.getByRole('button',{name:'Resume',exact:true}).click();
  await page.waitForTimeout(1200);
  await page.getByRole('button',{name:'Finish recording',exact:true}).click();
  await page.getByLabel('Recording playback').waitFor();
  page.once('dialog',d=>d.dismiss());
  await page.locator('[data-nav="Library"]').click();
  await page.getByLabel('Recording playback').waitFor();
  await page.screenshot({path:'/tmp/record-review-dark.png',fullPage:true});
  await page.getByRole('button',{name:'Discard recording',exact:true}).click();
  if(await page.locator('audio').count())throw new Error('Discard left recording preview');
  await page.locator('#settingsNav').click();
  await page.getByLabel('Colour mode').selectOption('system');
  await page.emulateMedia({colorScheme:'light'});
  if(await page.locator('html').getAttribute('data-appearance')!=='light')throw new Error('System light failed');
  await page.emulateMedia({colorScheme:'dark'});
  await page.waitForFunction(()=>document.documentElement.dataset.appearance==='dark');
  await page.locator('[data-nav="Capture"]').click();
  await page.getByRole("button", { name: "Document", exact: true }).click();
  await page.getByLabel("Document", { exact: true }).waitFor();
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw new Error("Mobile overflow");
  await page.setViewportSize({width:320,height:700});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Small phone overflow');
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
  await loginPage.getByRole("heading", { name: "To-dos",exact:true }).waitFor();
  console.log(
    "Password login requires MFA before private API requests: passed.",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
