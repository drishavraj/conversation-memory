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
    user_metadata: {full_name: "Rishav Raj"},
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
  const taskList = ['transcription','translation','summary','extraction','answer','reconciliation'];
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
  let projects=[], topics=[], accepted=false, linked=false, threads=[], failNext=false;
  const evidence={id:'k1',version:1,evidence:'We will start with a pilot.',source_entry_id:'e1',source_title:'Pilot review',event_at:'2026-10-06T06:30:00Z'};
  const memory={id:'m1',text:'Start with a pilot.',kind:'decision',certainty:'explicit',version:1,topic_ids:['t1'],evidence:[evidence],needs_review:false};
  const proposal={id:'r1',text:memory.text,kind:'decision',certainty:'explicit',operation:'new',reason:'Explicit decision',evidence:[evidence],current:null,stale:false};
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname,method=route.request().method();let data={};
    if(path==='/api/memories/chats'){
      if(method==='POST'){const payload=route.request().postDataJSON();data={id:'chat-'+(threads.length+1),...payload,project_name:'PNB Edge',topic_name:payload.topic_id?'Demo':null,title:'New chat',version:0,turns:[],has_older:false,pending_turn_id:null,updated_at:new Date().toISOString()};threads.push(data);}else data={items:threads.filter(t=>!new URL(route.request().url()).searchParams.get('topic_id')||t.topic_id===new URL(route.request().url()).searchParams.get('topic_id')),has_more:false};
    }else if(path.startsWith('/api/memories/chats/')){
      const id=path.split('/')[4],t=threads.find(t=>t.id===id);
      if(path.endsWith('/turns/stream')){
        const payload=route.request().postDataJSON();
        if(payload.expected_version!==t.version)throw Error('Wrong chat version');
        const turn={id:'turn-'+(t.turns.length+1),request_id:payload.request_id,question:payload.question,sequence:++t.version,status:failNext?'failed':'completed',response:failNext?null:{status:'answered',claims:[{text:memory.text,source_ids:['m1']}],sources:[memory]},changed_source_ids:[],context_info:{},error:failNext?'answer_generation_unavailable':null};failNext=false;t.turns.push(turn);t.title=payload.question;
        return route.fulfill({contentType:'text/event-stream',body:'event: status\ndata: '+JSON.stringify({message:'Checking evidence…'})+'\n\nevent: result\ndata: '+JSON.stringify({thread_version:t.version,turn})+'\n\n'});
      }else if(path.endsWith('/retry')){const turn=t.turns.at(-1);turn.status='completed';turn.error=null;turn.response={status:'answered',claims:[{text:memory.text,source_ids:['m1']}],sources:[memory]};data={turn,thread_version:t.version};}else data=t;
    }else if(path==='/api/ui-config')data={environment:'development',configured:true,memories_enabled:true,supabase_url:'https://example.supabase.co',supabase_publishable_key:'sb_publishable_test'};
    else if(path==='/api/session')data={status:'authenticated'};
    else if(path==='/api/actions')data=[];
    else if(path==='/api/ai-settings')data=aiSettings;
    else if(path==='/api/entries')data=[{id:'e1',title:'Pilot review',status:'ready',theme_id:'office'}];
    else if(path==='/api/memories/projects'){
      if(method==='POST'){projects.push({id:'p1',...route.request().postDataJSON()});data=projects[0];}else data={items:projects,has_more:false};
    }else if(path==='/api/memories/projects/p1/topics'){topics.push({id:'t1',...route.request().postDataJSON()});data=topics[0];}
    else if(path==='/api/memories/projects/p1/entries'){
      const body=route.request().postDataJSON();if(body.entry_id!=='e1'||body.topic_ids[0]!=='t1')throw Error('Link lost topic scope');linked=true;data={status:'completed'};
    }else if(path==='/api/memories/projects/p1/proposals/r1/review'){
      if(route.request().postDataJSON().decision!=='accept')throw Error('Wrong review action');accepted=true;data={status:'accepted'};
    }else if(path==='/api/memories/projects/p1/ask'){
      const body=route.request().postDataJSON();if(body.topic_id!=='t1'||!accepted)throw Error('Ask escaped accepted topic scope');data={status:'answered',claims:[{text:memory.text,source_ids:['m1']}],sources:[memory],pending_changes:0};
    }else if(path==='/api/memories/projects/p1')data={...projects[0],topics,memories:accepted?[memory]:[],proposals:linked&&!accepted?[proposal]:[],proposal_count:linked&&!accepted?1:0,has_more:false,entries:linked?[{id:'e1',title:'Pilot review',status:'ready',memory_status:'completed',topic_ids:['t1']}]:[]};
    else if(path==='/api/memories/projects/p1/memories/m1/history')data=[{before:null,after:memory,reason:'Verified source',created_at:'2026-10-06T06:30:00Z'}];
    await route.fulfill({json:data});
  });
  await page.route('https://example.supabase.co/**',route=>route.fulfill({json:{user,all:[],totp:[],phone:[]}}));
  await page.goto((process.env.UI_BASE_URL||'http://localhost:8010')+'/');
  await page.locator('#accountToggle').waitFor();
  await page.locator('.account-identity').getByText('Rishav Raj',{exact:true}).waitFor();
  await page.evaluate(()=>document.fonts.ready);
  if(!await page.evaluate(()=>document.fonts.check('14px Inter')))throw Error('Bundled font unavailable');
  await page.locator('#sidebarToggle').click();
  if(!await page.locator('.shell').evaluate(el=>el.classList.contains('sidebar-collapsed')))throw Error('Sidebar did not collapse');
  await page.locator('#accountToggle').click();
  await page.locator('#accountMenu').getByText('rishav@example.com',{exact:true}).waitFor();
  await page.locator('#accountAppearance').selectOption('dark');
  if(await page.locator('html').getAttribute('data-appearance')!=='dark')throw Error('Account appearance failed');
  await page.keyboard.press('Escape');
  if(!await page.locator('#accountMenu').evaluate(el=>el.hidden))throw Error('Escape did not dismiss account menu');
  await page.locator('#sidebarToggle').click();

  await page.locator('[data-nav="Memories"]').click();
  if(await page.locator('#memorySearch').evaluate(el=>el.getBoundingClientRect().top)>160)throw Error('Workspace header too tall');
  await page.getByRole('button',{name:'New project',exact:true}).click();
  await page.getByLabel('Project name').fill('PNB Edge');
  await page.getByRole('dialog').getByLabel('Theme',{exact:true}).selectOption('office');
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.locator('[data-cloud="p1"]').click();
  await page.getByRole('button',{name:'New topic',exact:true}).click();
  await page.getByLabel('Topic name').fill('Demo');
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.locator('[data-cloud="t1"]').click();
  await page.locator('[data-pane="sources"]').click();
  await page.getByRole('button',{name:'Link a conversation',exact:true}).click();
  await page.getByRole('dialog').getByLabel('Conversation',{exact:true}).selectOption('e1');
  await page.getByRole('dialog').getByRole('button',{name:'Save',exact:true}).click();
  await page.locator('[data-pane="overview"]').click();
  await page.getByRole('button',{name:'Review suggestions',exact:true}).click();
  await page.getByLabel('Suggested memory').waitFor();
  await page.getByRole('button',{name:'Accept',exact:true}).click();
  await page.getByText('No suggestions waiting for review.',{exact:true}).waitFor();
  await page.locator('[data-cloud="t1"]').click();
  await page.locator('.memory-fact').getByText('Start with a pilot.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Ask about this',exact:true}).click();
  await page.getByRole('button',{name:'New chat',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill('Where do we stand?');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.locator('.chat-answer').getByText('Start with a pilot.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Source 1',exact:true}).click();
  await page.getByRole('dialog').getByText('We will start with a pilot.',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Back to chat',exact:true}).click();
  await page.getByRole('button',{name:'Expand chat',exact:true}).click();
  await page.getByRole('button',{name:'Return to pane',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).fill('What next?');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn').length===2);
  await page.getByRole('button',{name:'New chat',exact:true}).click();
  await page.getByLabel('Message',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn').length===0&&document.querySelector('[data-composer]'));
  if(await page.locator('.chat-turn').count())throw Error('New thread contains old messages');
  await page.getByLabel('Message',{exact:true}).fill('Keep this draft');
  await page.locator('[data-nav="Chats"]').click();
  await page.locator('[data-thread="chat-2"]').click();
  if(await page.getByLabel('Message',{exact:true}).inputValue()!=='Keep this draft')throw Error('Draft lost on navigation');
  failNext=true;
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByRole('button',{name:'Retry response',exact:true}).click();
  await page.locator('.chat-answer').getByText('Start with a pilot.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'History',exact:true}).click();
  await page.locator('[data-thread="chat-1"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn').length===2);
  if(await page.locator('.chat-turn').count()!==2)throw Error('Saved history lost messages');
  await page.locator('[data-nav="Memories"]').click();
  await page.locator('[data-cloud="p1"]').click();
  await page.locator('[data-cloud="t1"]').click();
  await page.locator('[data-pane="ask"]').click();
  await page.locator('[data-thread="chat-1"]').click();
  await page.screenshot({path:'/tmp/memories-live-desktop.png',fullPage:true});
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844});
    await page.locator('#accountToggle').click();
    if(!await page.locator('#accountMenu').evaluate(el=>{const b=el.getBoundingClientRect();return b.top>=0&&b.left>=0&&b.right<=innerWidth;}))throw Error('Mobile account menu clipped');
    await page.locator('#accountMenu').getByRole('button',{name:'Sign out',exact:true}).waitFor();
    await page.keyboard.press('Escape');

    await page.getByRole('button',{name:'← Back to map',exact:true}).click();
    await page.locator('[data-cloud="t1"]').click();
    await page.locator('.memory-fact').getByText('Start with a pilot.',{exact:true}).waitFor();
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Memories mobile overflow');
    await page.getByRole('button',{name:'Ask about this',exact:true}).click();
  }
  await page.screenshot({path:'/tmp/memories-live-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  for(const count of [1,4,12,30]){
    projects=Array.from({length:count},(_,i)=>({id:'layout-'+i,name:['PNB Genie','CCP','NPCI AtOM','Memory Organization'][i%4]+(i>3?' '+i:''),theme_id:i%4===3?'side-projects':'office'}));
    await page.locator('[data-nav="Actions"]').click();await page.locator('[data-nav="Memories"]').click();
    await page.locator(`[data-cloud="layout-${count-1}"]`).waitFor();
    await page.locator('#memoryFit').click();
    const boxes=await page.locator('[data-cloud]').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}));
    for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const a=boxes[i],b=boxes[j];if(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)throw Error('Cloud collision '+count);}
    const transform=await page.locator('#memoryClouds').evaluate(el=>el.style.transform);
    await page.locator('#memoryZoomIn').click();
    if(transform===await page.locator('#memoryClouds').evaluate(el=>el.style.transform))throw Error('Zoom did not change map');
    await page.locator('#memoryFit').click();
    if(count===4)await page.screenshot({path:'/tmp/memories-four-projects.png',fullPage:true});
    await page.locator('#memoryView').click();
    if(await page.locator('#memoryClouds').getAttribute('class')!=='memory-clouds memory-list')throw Error('List mode failed');
    await page.locator('#memoryView').click();
  }
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Live-data Memories UI: project/topic creation, scoped linking, proposal acceptance, cited Ask, and phone layout passed.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
