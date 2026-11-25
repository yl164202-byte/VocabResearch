import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import test from 'node:test';

const { VOCAB_E2E_URL: projectUrl, VOCAB_E2E_KEY: publishableKey, VOCAB_E2E_CODE: code,
  VOCAB_E2E_PIN: pin, VOCAB_E2E_COURSE: courseId, VOCAB_E2E_CHROME: executablePath } = process.env;
const rpc = projectUrl + '/rest/v1/rpc/vocab_request';

test('live Supabase HTTP and local Chrome against a synthetic course', { timeout: 120000 }, async t => {
  assert.match(projectUrl || '', /^https:\/\/[a-z0-9-]+\.supabase\.co$/);
  assert.match(publishableKey || '', /^sb_publishable_/);
  assert.match(code || '', /^IT_/);
  assert.match(courseId || '', /^IT_/);
  assert.ok(pin);
  const { chromium } = await import(process.env.VOCAB_PLAYWRIGHT_ENTRY || 'playwright-core');
  const assets = new Map();
  const upstream=process.env.VOCAB_E2E_ASSET_BASE;
  const remote=async (path)=>{
    const r=await fetch(upstream+'/'+path);
    assert.equal(r.status,200,'published asset '+path);
    return r;
  };
  for (const [file,type] of [['index.html','text/html'],['app.js','text/javascript'],['style.css','text/css']]) {
    assets.set('/'+file,[type,upstream?Buffer.from(await (await remote(file)).arrayBuffer()):await readFile(new URL('../student/'+file,import.meta.url))]);
  }
  const json = (path,data) => assets.set(path,['application/json',JSON.stringify(data)]);
  const names=['v1','v2'].map(v=>upstream?courseId+'__'+v+'.json':v+'.json');
  const config=upstream?await (await remote('backend.json')).json():{projectUrl,publishableKey};
  assert.equal(config.projectUrl,projectUrl);
  assert.ok(config.publishableKey===publishableKey,'Published key differs from the selected project key');
  assert.deepEqual(Object.keys(config).sort(),['projectUrl','publishableKey']);
  json('/backend.json',config);
  if(upstream){
    const index=await (await remote('lessons/index.json')).json();
    assert.ok(names.every(x=>index.files.includes(x)&&!index.hidden?.includes(x)));
  }
  json('/lessons/index.json',{files:names});
  const lessons=[];
  for (const [i,version] of ['v1','v2'].entries()) {
    const document=upstream?await (await remote('lessons/'+names[i])).json():
      {schema:'vocab-research-1',id:courseId,version,title:'合成教材',clozeGrading:'server',
       availableLanguages:['en'],words:[{id:'W1',word:'甲',pinyin:'jiǎ',meanings:{en:'alpha'},sentence:'這是＿＿個例子。'}]};
    assert.equal(document.clozeGrading,'server');
    assert.ok(document.words.every(w=>!('accepted' in w)));
    lessons.push(document);
    json('/lessons/'+names[i],document);
  }
  const server = createServer((req,res) => {
    const asset=assets.get(new URL(req.url,'http://localhost').pathname);
    if (!asset) {res.writeHead(404).end();return;}
    res.writeHead(200,{'Content-Type':asset[0]+'; charset=utf-8','Cache-Control':'no-store'}).end(asset[1]);
  });
  await new Promise((resolve,reject)=>server.listen(0,'127.0.0.1',resolve).once('error',reject));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const url='http://127.0.0.1:'+server.address().port+'/index.html';
  const browser=await chromium.launch({executablePath,headless:true,args:['--disable-background-networking']});
  t.after(()=>browser.close());
  const context=await browser.newContext();
  const first=await context.newPage();
  const second=await context.newPage();
  const start=async(page,index='0')=>{
    await page.goto(url);
    await page.locator('#course option').nth(1).waitFor({state:'attached'});
    await page.selectOption('#course',index);
    await page.fill('#student',code);
    await page.fill('#pin',pin);
    await page.click('#start');
  };
  const sync=async(page,re)=>page.waitForFunction(re=>new RegExp(re).test(document.querySelector('#sync').textContent),re,{timeout:15000});
  const assertRpc=async(packet)=>{
    const r=await fetch(rpc,{method:'POST',headers:{apikey:publishableKey,'content-type':'application/json'},body:JSON.stringify({packet})});
    assert.equal(r.status,200);
    return r.json();
  };
  await t.test('HTTP protocol and private schema access',async()=>{
    const requestId=randomUUID();
    const ack=await assertRpc({operation:'version',requestId});
    assert.equal(ack.requestId,requestId);
    assert.equal(ack.protocol,'supabase-v1');
    const denied=await fetch(projectUrl+'/rest/v1/students?select=code&limit=0',{
      headers:{apikey:publishableKey,'Accept-Profile':'vocab_private'},
    });
    assert.ok([400,401,403,404,406].includes(denied.status));
  });
  let firstAccepted=false;
  let gradingInterrupted=false;
  let acceptedIds=[];
  await first.route(rpc,async route=>{
    const {packet}=route.request().postDataJSON();
    if(packet.operation==='grade_cloze'&&!gradingInterrupted){
      gradingInterrupted=true;
      await route.abort('internetdisconnected');
      return;
    }
    if(packet.operation!=='events'||firstAccepted){await route.continue();return;}
    firstAccepted=true;
    const result=await route.fetch();
    assert.equal(result.status(),200);
    const ack=await result.json();
    assert.equal(ack.ok,true);
    acceptedIds=ack.eventIds;
    await route.abort('failed');
  });
  await t.test('opening a second tab cannot start the same daily session',async()=>{
    await start(first);
    await first.locator('#next').waitFor();
    await sync(first,'未收到後端確認');
    await start(second);
    await sync(second,'另一個分頁');
    assert.equal(await second.locator('#workspace').isVisible(),false);
  });
  await t.test('lost acknowledgement retains events and retry sends identical event IDs',async()=>{
    assert.equal(acceptedIds.length,1);
    assert.match(await first.locator('#pending').textContent(),/1 筆/);
    await first.locator('#researchDetails summary').click();
    const replay=first.waitForResponse(r=>r.url()===rpc);
    await first.click('#retry');
    const ack=await (await replay).json();
    assert.deepEqual(ack.eventIds,acceptedIds);
    await first.waitForFunction(()=>/0 筆/.test(document.querySelector('#pending').textContent));
  });
  if(process.env.VOCAB_E2E_CODE2) await t.test('another student and concurrent duplicate batches remain isolated',async()=>{
    const identity={studentCode:process.env.VOCAB_E2E_CODE2,pin:process.env.VOCAB_E2E_PIN2,
      courseId,courseVersion:'v1',protocol:'supabase-v1'};
    const status=await assertRpc({...identity,operation:'daily_status',requestId:randomUUID()});
    assert.equal(status.status,'not_started');
    const sessionId=randomUUID();
    const current=await assertRpc({...identity,sessionId,practiceDate:status.practiceDate,
      operation:'daily_start',requestId:randomUUID()});
    assert.equal(current.status,'in_progress');
    const event={studentCode:identity.studentCode,courseId,courseVersion:'v1',sessionId,
      practiceDate:status.practiceDate,study:'vocab',mode:'practice',stage:'card',
      action:'session_start',eventId:randomUUID()};
    const results=await Promise.all([1,2].map(()=>assertRpc({...identity,operation:'events',
      requestId:randomUUID(),events:[event]})));
    assert.ok(results.every(result=>result.ok&&result.eventIds[0]===event.eventId));
  });
  const words=lessons[0].words;
  const pick=async(word,meaning)=>{
    await first.locator('[data-left]').filter({hasText:word}).click();
    await first.locator('[data-right]').filter({hasText:meaning}).click();
  };
  await t.test('flashcards render and matching progress survives re-login',async()=>{
    await first.locator('#flip').click();
    assert.match(await first.locator('#flip').innerText(),new RegExp(words[0].meanings.en));
    for(const word of words) await first.click('#next');
    if(words.length>1){
      await pick(words[0].word,words[1].meanings.en);
      await first.getByText(/配對錯誤/).waitFor();
      await start(first);
      await first.waitForFunction(()=>document.querySelector('#matchStatus')?.textContent.includes('錯誤 1 次'));
    }
    for(const word of words) await pick(word.word,word.meanings.en);
    await first.click('#nextGroup');
  });
  await t.test('cloze preserves offline text, then accepts retry and a reviewed alternate answer',async()=>{
    const input=(word)=>first.locator('[data-fill="'+word.id+'"]');
    await input(words[0]).fill('錯誤');
    for(const word of words.slice(1)) await input(word).fill(word.word);
    await first.click('#submitCloze');
    await first.getByText(/判分未完成/).waitFor();
    assert.equal(await input(words[0]).inputValue(),'錯誤');
    await first.click('#submitCloze');
    await first.getByText(/尚未全對/).waitFor();
    await first.click('#submitCloze');
    await input(words[0]).fill('第一');
    for(const word of words.slice(1)) await input(word).fill(word.word);
    await first.click('#submitCloze');
    await sync(first,'Supabase 已確認並鎖定');
  });
  await t.test('completed student is locked after refresh, second tab and another version',async()=>{
    await start(first);
    await sync(first,'已達標完成');
    await start(second);
    await sync(second,'已達標完成');
    const fresh=await browser.newContext();
    const page=await fresh.newPage();
    await start(page,'1');
    await sync(page,'已達標完成');
    assert.equal(await page.locator('#workspace').isVisible(),false);
    await fresh.close();
  });
});
