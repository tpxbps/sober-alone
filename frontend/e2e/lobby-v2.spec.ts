import { expect, test, type Page, type Route } from "@playwright/test";

const story = { script_id: "v2-a", title: "雾中来信", difficulty: 1, player_count: 4, estimated_duration: 30, overview: "一封迟到的信，四个未曾坦白的人。", tags: "悬疑", cover_image_url: "/lobby/theatre.webp", ai_review: { score: 78, model: "gpt-6-astra", dimensions: [{key:"logic",label:"逻辑完整性",weight:30,score:4}] } };
const other = { ...story, script_id: "v2-b", title: "深海回声", difficulty: 3 };
const people = [
  { character_id: "human", name: "赵屿", occupation: "广播主持人", profile: "留守旧电台的主持人。", avatar_url: "/lobby/dragon.png" },
  { character_id: "a", name: "很长很长的姓名用来验证人物侧栏不会溢出", occupation: "担任多个不同职务并拥有特别长的完整职业描述", profile: "完整的角色简介。", avatar_url: "/lobby/dragon.png" },
  { character_id: "b", name: "顾宁", occupation: "节目制作人", profile: "节目制作人。", avatar_url: "/lobby/dragon.png" },
  { character_id: "c", name: "程宇", occupation: "工程师", profile: "工程师。", avatar_url: "/lobby/dragon.png" },
];
const send = (route: Route, data: unknown) => route.fulfill({contentType:"application/json", body:JSON.stringify(data)});
async function fixture(page: Page, options: { failCreate?: boolean; failInit?: boolean; deferCharacters?: boolean; deferHealth?: boolean; deferInit?: boolean } = {}) {
  const seen = { creates:0, states:0, histories:0, body:null as null | Record<string, unknown>, release:() => {} };
  const held = new Promise<void>(resolve => { seen.release = resolve; });
  await page.route(url => !["127.0.0.1","localhost"].includes(url.hostname), route => route.abort());
  await page.route("**/audio/**", route => route.abort());
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if(path.endsWith("/game/scripts")) return send(route,{success:true,scripts:[story,other]});
    if(path.endsWith("/characters")) {
      if(options.deferCharacters && path.includes("v2-a")) await held;
      return send(route,{success:true,characters:path.includes("v2-b") ? [{...people[0],name:"新故事角色"},...people.slice(1)] : people});
    }
    if(path.endsWith("/capabilities")) return send(route,{models:["deepseek-flash","hy3"].map(model=>({id:model,name:model,model,provider:"deepseek",provider_name:"DeepSeek",configured:true})),features:{rag:{enabled:false},image:{enabled:false},static_tts:{enabled:false},streaming_tts:{enabled:false}}});
    if(path.endsWith("/model-health") || path.endsWith("/model-health/refresh")) { if(options.deferHealth) await held; return send(route,{models:[{model:"deepseek-flash",status:"normal",message:"响应正常"},{model:"hy3",status:"slow",message:"响应较慢"}]}); }
    if(path.endsWith("/create")) {
      seen.creates++; seen.body=route.request().postDataJSON();
      if(options.failCreate && seen.creates===1) return send(route,{success:false,error:"创建失败，请重试"});
      await new Promise(resolve=>setTimeout(resolve,250));
      return send(route,{success:true,session_id:"v2-session"});
    }
    if(path.endsWith("/state")) {
      seen.states++;
      if(options.deferInit) await held;
      if(options.failInit && seen.states===1) return send(route,{success:false});
      return send(route,{success:true,session_id:"v2-session",status:"playing",current_stage:"intro",current_round:0,
        human_character_id:"human",current_speaker_id:"human",speech_queue:["human"],has_all_spoken:false,script:story,
        characters:people.map(p=>({...p,is_human:p.character_id==="human"})),player_states:people.map(p=>({character_id:p.character_id,character_name:p.name,is_human:p.character_id==="human",remaining_speech_count:1,has_spoken_this_round:false,suspicion_reasons:{},suspected_by:{},player_perspectives:{}})),agent_llm_info:{},votes:{}});
    }
    if(path.endsWith("/records")) { seen.histories++; return send(route,{success:true,records:[],count:0}); }
    return send(route,{success:true,models:[]});
  });
  await page.goto("/");
  await expect(page.getByRole("button",{name:"打开剧本 雾中来信"})).toBeVisible();
  return seen;
}
test.use({reducedMotion:"reduce",video:"on"});
test.describe("页面切换画面连续性", () => {
  test.use({reducedMotion:"no-preference"});
  for (const native of [true, false]) {
    test(native ? "快照叠入保持旧画面，背景节点跨页面保留" : "不支持快照时直接切换，内容与背景不淡空", async ({page}, info) => {
      if (!native) await page.addInitScript(() => Object.defineProperty(document, "startViewTransition", {value:undefined}));
      await fixture(page);
      await expect.poll(() => page.locator(".app-backdrops img").evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
      await page.evaluate(() => {
        const backdrop = document.querySelector(".app-backdrops");
        const frames: Array<{content:number; background:number; retained:boolean}> = [];
        const state = window as unknown as {sceneFrames:typeof frames; sampling:boolean};
        state.sceneFrames = frames; state.sampling = true;
        const sample = () => {
          const surfaces = document.querySelectorAll(".app-screen > div, .lobby-main");
          const content = surfaces.length ? Math.min(...Array.from(surfaces, el => Number(getComputedStyle(el).opacity))) : 0;
          const background = Array.from(document.querySelectorAll(".app-backdrops img"), el => Number(getComputedStyle(el).opacity)).reduce((a,b) => a+b, 0);
          frames.push({content, background, retained:backdrop === document.querySelector(".app-backdrops")});
          if (state.sampling) requestAnimationFrame(sample);
        }; requestAnimationFrame(sample);
      });
      await page.getByRole("button", {name:"打开剧本 雾中来信"}).click();
      await expect(page.locator(".setup-metadata h1")).toHaveText("雾中来信");
      await expect(page.locator(".game-entry-overlay")).toHaveCount(0);
      await page.getByRole("button", {name:"返回列表"}).click();
      await expect(page.locator(".script-setup")).toHaveCount(0);
      await page.getByRole("button", {name:"创作工坊", exact:true}).click();
      await expect(page.getByRole("button", {name:"返回剧本大厅"})).toBeVisible();
      await page.screenshot({path:info.outputPath("workshop-transition.png")});
      await page.getByRole("button", {name:"返回剧本大厅"}).click();
      await expect(page.getByRole("button", {name:"打开剧本 雾中来信"})).toBeVisible();
      await expect(page.locator(".app-backdrops .backdrop-home")).toHaveCSS("opacity", "0.32");
      const frames = await page.evaluate(() => {
        const state = window as unknown as {sceneFrames:Array<{content:number; background:number; retained:boolean}>;sampling:boolean};
        state.sampling = false;
        return state.sceneFrames;
      });
      expect(frames.length).toBeGreaterThan(10);
      expect(frames.every(frame => frame.content === 1 && frame.background >= .3 && frame.retained)).toBe(true);
      await info.attach("navigation-frame-samples", {body:JSON.stringify(frames),contentType:"application/json"});
    });
  }
});
test("初始全量分组、键盘选本、返回原卡片与快速换本取消旧角色", async ({page}) => {
  const seen = await fixture(page,{deferCharacters:true});
  await expect(page.locator(".script-setup")).toHaveCount(0);
  await expect(page.locator(".lobby-difficulty-group")).toHaveCount(2);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".setup-loading")).toBeVisible();
  await page.getByRole("button",{name:"打开剧本 深海回声"}).click();
  await expect(page.getByRole("button",{name:"扮演 新故事角色"})).toBeVisible();
  seen.release();
  await expect(page.getByRole("button",{name:"扮演 赵屿",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:"返回列表"}).click();
  await expect(page.locator("#script-list")).toBeFocused();
  await expect(page.locator(".lobby-card:focus-within")).toHaveCount(0);
  await expect(page.locator(".lobby-heading")).toBeVisible();
  await expect(page.locator(".script-setup")).toHaveCount(0);
});
for (const failure of ["create","init"] as const) {
  test(failure+" 失败可重试、重复点击不重复创建、初始化完成后直接入局", async ({page}, info) => {
    const seen = await fixture(page,{failCreate:failure==="create",failInit:failure==="init"});
    await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
    await expect(page.getByRole("button",{name:"走进故事"})).toBeDisabled();
    await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
    await expect(page.getByRole("combobox")).toHaveCount(3);
    const model = page.getByRole("combobox").first();
    await model.click();
    await page.getByRole("option",{name:"hy3",exact:true}).click();
    await expect(model).toHaveText("hy3");
    await page.getByRole("button",{name:"走进故事"}).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator(".scene-game")).toHaveCount(0);
    // Same-tick duplicate events exercise the guard before React can disable the button.
    await page.getByRole("button",{name:"重试进入故事"}).evaluate((button:HTMLButtonElement)=>{button.click();button.click();});
    await expect(page.locator(".scene-game")).toBeVisible();
    expect(seen.creates).toBe(failure==="create"?2:1);
    expect(seen.states).toBe(failure==="init"?2:1);
    expect(seen.histories).toBe(1);
    expect((seen.body?.llm_configs as Record<string,{model:string}>).a.model).toBe("hy3");
    await page.setViewportSize({width:1440,height:900});
    const items = page.locator(".character-panel-item");
    await expect(items).toHaveCount(4);
    await expect.poll(async()=>new Set(await items.evaluateAll(nodes=>nodes.map(n=>Math.round(n.getBoundingClientRect().width)))).size).toBe(1);
    expect(await items.evaluateAll(nodes=>nodes.every(n=>n.clientWidth>=n.scrollWidth && Math.round(n.getBoundingClientRect().height)===74))).toBe(true);
    const occupation=items.locator("p").nth(1);
    await expect(occupation).toHaveCSS("text-overflow","ellipsis");
    await items.nth(1).hover();
    await expect(page.getByRole("tooltip").getByText(people[1].occupation,{exact:true})).toBeVisible();
    await page.screenshot({path:info.outputPath("game-long-characters.png")});
  });
}
test("320—1440 像素的列表和原页选角不横向溢出", async ({page},info) => {
  // Six complete open/return flows and full-page captures share this budget.
  test.setTimeout(90_000);
  await fixture(page);
  for(const width of [1440,1280,1024,768,390,320]) {
    await page.setViewportSize({width,height:900});
    await expect(page.getByRole("button",{name:"打开剧本 雾中来信"})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
    await expect(page.getByRole("button",{name:"扮演 赵屿",exact:true})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath("setup-"+width+".png"),fullPage:true});
    await page.getByRole("button",{name:"返回列表"}).click();
  }
});
test("触屏直接选本且卡片描述保持清晰", async ({browser,baseURL}) => {
  const context=await browser.newContext({baseURL,hasTouch:true,isMobile:true,viewport:{width:390,height:844}});
  const page=await context.newPage(); await fixture(page);
  await expect(page.locator(".dream-lobby")).toHaveAttribute("data-renderer","still");
  await expect(page.locator(".card-overview").first()).toHaveCSS("filter","none");
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).tap();
  await expect(page.locator(".script-setup")).toBeVisible(); await context.close();
});
test.describe("动态显现",()=>{
  test.use({reducedMotion:"no-preference",viewport:{width:1280,height:800}});
  test("单画布、即时坐标、跨卡片显现和 WebGL 回退",async({page},info)=>{
    await fixture(page);
    await expect(page.locator(".dream-lobby")).toHaveAttribute("data-renderer",/webgl|fallback/);
    await expect(page.locator(".lobby-atmosphere")).toHaveCount(1);
    await expect.poll(()=>page.evaluate(()=>document.querySelector('.dream-lobby')?.getAttribute('data-renderer')==='fallback' || document.querySelectorAll(".card-cover-media[data-gpu='ready']").length===2)).toBe(true);
    const title=page.getByRole("button",{name:"打开剧本 雾中来信"});
    const rect=(await title.boundingBox())!;
    await page.mouse.move(rect.x+20,rect.y+10);
    const source=await page.evaluate(()=>({renderer:document.querySelector('.dream-lobby')?.getAttribute('data-renderer'),pointer:document.querySelector('.lobby-atmosphere')?.getAttribute('data-pointer')}));
    if(source.renderer==='webgl') expect(source.pointer).toBe((rect.x+20)+","+(rect.y+10));
    await expect(page.locator(".card-overview").first()).toHaveCSS("filter","none");
    await page.screenshot({path:info.outputPath("fluid-revealed.png")});
    for (const [x,y] of [[850,500],[400,290],[750,170],[300,600],[900,400]]) await page.mouse.move(x,y,{steps:10});
    await page.screenshot({path:info.outputPath("fluid-trail.png")});
    await page.mouse.move(1000,90);
    await expect.poll(()=>page.evaluate(()=>getComputedStyle(document.querySelector('.card-overview')!).filter===(document.querySelector('.dream-lobby')?.getAttribute('data-renderer')==='fallback'?'none':'blur(0.65px)'))).toBe(true);
    await page.waitForTimeout(5500); // Include an autonomous current in the acceptance recording.
    await page.screenshot({path:info.outputPath("fluid-ambient.png")});
    await page.locator("canvas").evaluate((canvas:HTMLCanvasElement)=>canvas.getContext("webgl2")?.getExtension("WEBGL_lose_context")?.loseContext());
    await expect(page.locator(".dream-lobby")).toHaveAttribute("data-renderer","fallback");
    await expect(page.locator(".card-overview").first()).toHaveCSS("filter","none");
    await expect(page.locator(".card-cover-media").first()).not.toHaveAttribute("data-gpu","ready");
  });
  test("持续低帧率时退出流体绘制，保持卡片可读且可以选本",async({page})=>{
    // A slow frame scheduler models a device that can present only about 8fps.
    await page.addInitScript(()=>{
      window.requestAnimationFrame=callback=>window.setTimeout(()=>callback(performance.now()),120);
      window.cancelAnimationFrame=window.clearTimeout.bind(window);
    });
    await fixture(page);
    await expect(page.locator('.dream-lobby')).toHaveAttribute('data-renderer','fallback',{timeout:12000});
    await expect(page.locator('.card-overview').first()).toHaveCSS('filter','none');
    await expect(page.locator('.card-cover-media[data-gpu="ready"]')).toHaveCount(0);
    await page.getByRole('button',{name:'打开剧本 雾中来信'}).click();
    await expect(page.getByRole('button',{name:'扮演 赵屿',exact:true})).toBeVisible();
  });
});

test("测速晚到保留自动及手动模型配置",async({page})=>{
  const seen=await fixture(page,{deferHealth:true});
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
  await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
  const model=page.getByRole("combobox").first();
  await model.click();
  await page.getByRole("option",{name:"deepseek-flash",exact:true}).click();
  await model.click();
  await page.getByRole("option",{name:"hy3",exact:true}).click();
  const before = await page.getByRole("combobox").allTextContents();
  seen.release();
  await expect(model.locator("..").getByRole("status")).toHaveText("响应较慢");
  await expect(model).toHaveText("hy3");
  await expect(page.getByRole("combobox")).toHaveText(before);
  await page.getByRole("button", {name:"重新进行模型测速"}).click();
  await expect(page.getByRole("status").filter({hasText:"测速已更新"})).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveText(before);
  await expect(page.getByRole("button",{name:"走进故事"})).toBeEnabled();
});
test("初始资料慢请求期间保持准备遮罩，数据完成才切换",async({page})=>{
  const seen=await fixture(page,{deferInit:true});
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
  await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
  await page.getByRole("button",{name:"走进故事"}).click();
  await expect(page.locator(".game-entry-overlay")).toBeVisible();
  await page.waitForTimeout(950);
  await expect(page.locator(".scene-game")).toHaveCount(0);
  await expect(page.locator(".game-entry-overlay")).toContainText("正在准备故事");
  seen.release();
  await expect(page.locator(".scene-game")).toBeVisible();
  expect(seen.creates).toBe(1); expect(seen.states).toBe(1); expect(seen.histories).toBe(1);
});

test("设置与游戏弹层保持焦点、Escape 关闭并恢复入口，开关与危险按钮对比度一致", async ({page},info) => {
  await fixture(page);
  const settings=page.getByRole("button",{name:"设置",exact:true});
  await settings.click();
  const dialog=page.getByRole("dialog",{name:"设置",exact:true});
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("switch",{name:"大厅动态效果"})).toBeFocused();
  await expect(page.locator("body")).toHaveCSS("overflow","hidden");
  await expect(page.getByRole("switch",{name:"语音播报"})).toBeDisabled();
  for (let i=0;i<12;i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(el=>el.contains(document.activeElement))).toBe(true);
  }
  const contrast=await page.getByRole("switch",{name:"大厅动态效果"}).evaluate(el=>{
    const rgb=(value:string)=>value.match(/[\d.]+/g)!.slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
    const luminance=(value:string)=>rgb(value).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
    const a=luminance(getComputedStyle(el).backgroundColor),b=luminance(getComputedStyle(el.firstElementChild!).backgroundColor);
    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
  });
  expect(contrast).toBeGreaterThan(3);
  await page.screenshot({path:info.outputPath("settings-keyboard.png")});
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(settings).toBeFocused();
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
  await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
  await page.getByRole("button",{name:"走进故事"}).click();
  await expect(page.locator(".scene-game")).toBeVisible();
  await page.getByRole("button",{name:"雾中来信",exact:true}).click();
  await expect(page.getByRole("dialog",{name:"雾中来信",exact:true})).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button",{name:"雾中来信",exact:true})).toBeFocused();
  await page.getByRole("button",{name:"退出游戏"}).click();
  await expect(page.getByRole("dialog",{name:"确认退出",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"确认退出",exact:true})).toHaveCSS("color","rgb(25, 29, 36)");
  await page.setViewportSize({width:320,height:720});
  const box=(await page.getByRole("dialog").boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(16);
  expect(box.x+box.width).toBeLessThanOrEqual(304);
  await page.getByRole("button",{name:"确认退出",exact:true}).click();
  await expect(page.locator(".scene-game")).toHaveCount(0);
  await expect(page.getByRole("button",{name:"打开剧本 雾中来信"})).toBeVisible();
});

test.describe("入局遮罩连续性",()=>{
  test.use({reducedMotion:"no-preference"});
  test("准备时键盘无法进入后台操作，交接光晕覆盖已准备好的游戏",async({page})=>{
    const seen=await fixture(page,{deferInit:true});
    await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
    await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
    await page.getByRole("button",{name:"走进故事"}).click();
    await expect(page.locator(".game-entry-overlay.preparing")).toBeVisible();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(()=>document.activeElement===document.body || document.activeElement===document.documentElement)).toBe(true);
    await expect(page.locator(".lobby-header")).toHaveAttribute("inert","");
    await page.evaluate(()=>{
      const frames:Array<{phase:string;opacity:number;game:boolean}>=[];
      (window as unknown as {entryFrames:typeof frames}).entryFrames=frames;
      // Sample the entire transition; a fixed frame count ends early on
      // fast displays and can miss the already-rendered game handoff.
      const deadline=performance.now()+10_000;
      const sample=()=>{
        const el=document.querySelector(".game-entry-overlay");
        if(el) frames.push({phase:el.className,opacity:Number(getComputedStyle(el).opacity),game:!!document.querySelector(".scene-game")});
        if(performance.now()<deadline && (el || !document.querySelector(".scene-game"))) requestAnimationFrame(sample);
      };requestAnimationFrame(sample);
    });
    seen.release();
    await expect(page.locator(".scene-game")).toBeVisible();
    await expect(page.locator(".game-entry-overlay")).toHaveCount(0);
    const frames=await page.evaluate(()=>(window as unknown as {entryFrames:Array<{phase:string;opacity:number;game:boolean}>}).entryFrames);
    expect(frames.some(f=>f.phase.includes("revealing"))).toBe(true);
    expect(frames.filter(f=>!f.game).every(f=>f.opacity===1)).toBe(true);
    expect(frames.some(f=>f.game && f.phase.includes("arrival"))).toBe(true);
    expect(seen.creates).toBe(1);expect(seen.states).toBe(1);
  });
});


test("详情评分细则与模型异常提示保持可读，键盘返回恢复卡片", async ({page}) => {
  await fixture(page);
  await expect(page.locator(".lobby-heading")).toBeVisible();
  await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
  await expect(page.locator(".lobby-heading")).toHaveCount(0);
  await expect(page.locator(".setup-cover-art")).toHaveCSS("object-fit","cover");
  const score=page.getByRole("button",{name:"AI评分: 78，查看评分细则",exact:true});
  await score.hover();
  await expect(page.locator("[data-rating-explanation]")).toContainText("逻辑完整性");
  await page.mouse.move(1,1);
  await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
  await page.getByRole("combobox").first().click();
  await expect(page.getByRole("option",{name:"deepseek-flash",exact:true})).toHaveText("deepseek-flash");
  await expect(page.getByRole("option",{name:"hy3",exact:true})).toContainText("响应较慢");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(page.getByRole("combobox").first()).toBeFocused();
  await page.getByRole("combobox").first().click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("Escape");
  // A subsequent focus move must win over the menu's deferred restoration.
  await page.getByRole("button",{name:"返回列表"}).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button",{name:"打开剧本 雾中来信"})).toBeFocused();
});

test.describe("持续加载光晕",()=>{
  test.use({reducedMotion:"no-preference"});
  test("慢初始化期间循环呼吸，完成后只创建一次并撤去遮罩",async({page},info)=>{
    const seen=await fixture(page,{deferInit:true});
    await page.getByRole("button",{name:"打开剧本 雾中来信"}).click();
    await page.getByRole("button",{name:"扮演 赵屿",exact:true}).click();
    await page.getByRole("button",{name:"走进故事"}).click();
    await expect(page.locator(".game-entry-overlay.preparing")).toBeVisible();
    const overlay=page.locator(".game-entry-overlay");
    const animation=await overlay.evaluate(el=>({name:getComputedStyle(el,"::before").animationName,iterations:getComputedStyle(el,"::before").animationIterationCount}));
    expect(animation.name).toContain("entry-breathe");
    expect(animation.iterations).toContain("infinite");
    await page.waitForTimeout(1300);
    const first=await overlay.evaluate(el=>Number(getComputedStyle(el,"::before").opacity));
    await page.screenshot({path:info.outputPath("entry-breath-bright.png")});
    await page.waitForTimeout(1600);
    const second=await overlay.evaluate(el=>Number(getComputedStyle(el,"::before").opacity));
    expect(first-second).toBeGreaterThan(.2);
    await page.screenshot({path:info.outputPath("entry-breath-soft.png")});
    await expect(page.locator(".scene-game")).toHaveCount(0);
    seen.release();
    await expect(page.locator(".scene-game")).toBeVisible();
    await expect(overlay).toHaveCount(0);
    expect(seen.creates).toBe(1);
  });
});
