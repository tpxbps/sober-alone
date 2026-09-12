import { stressSelection } from "./selectionStress";
import { createServer, type ServerResponse } from "node:http";
import { expect, test, type Page } from "@playwright/test";

const question = (id: string) => ({
  id, title: "您来确定剧情走向：", question: id === "q1" ? "这起案件的核心冲突是什么？" : "谁最想隐瞒这段往事？",
  options: [
    { id: "a", label: "旧案复仇", impact: "将人物关系串联到十年前的旧案" },
    { id: "b", label: "共同秘密", impact: "让每个人都隐瞒一部分真相" },
  ], recommended_option_id: "a",
});
async function setup(page: Page) {
  let stage = 0, revision = 1, stopped = false, paused = false;
  let savedOutline = "", lastOperation = "start", sequence = 0;
  let answers: Array<Record<string, unknown>> = [];
  const archived: unknown[] = [];
  const commands: Record<string, unknown>[] = [];
  const session = () => ({
    protocol_version: 2, revision, status: stage < 2 ? "awaiting_answer" : "ready",
    segments: [{ id: "s1", content: "浓雾封住了码头，四名故人被困在旧灯塔。午夜，值守人离奇死亡。" },
      ...(stage > 0 ? [{ id: "s2", content: "十年前的失踪案再次浮现，四人的证词无法拼成完整的一夜。" }] : [])],
    decisions: answers, pending_question: stage < 2 ? question(stage === 0 ? "q1" : "q2") : null,
    questions_asked: stage + 1, questions_stopped: stopped,
    final_outline: stage >= 2 ? savedOutline || "# 雾港旧事\n\n四名故人的秘密构成了完整的案件大纲。\n\n## 真相\n守夜人利用旧案引出真正的幕后者。" : "",
    check: stage >= 2 ? { passed: true, issues: [] } : null,
  });
  const state = () => ({
    workflow_mode: "create", script_title: "雾港旧事", script_id: "outline-script",
    user_idea: "雾港灯塔中的旧案", player_count: 4, difficulty: 2, num_clue_rounds: 2,
    outline: session().final_outline || session().segments.map(s => s.content).join("\n\n"),
    outline_session: session(), prompts: {}, characters: [], first_draft: "", character_scripts: {},
    review_opinion: "", final_draft: "", game_data_sections: {}, error_message: "",
  });
  const response = () => ({
    success: true, thread_id: "co-thread", current_step: stage === 3 ? "review_first_draft" : stage < 2 ? "outline_wait" : "review_outline",
    is_complete: false, state: state(),
    interrupt: { step: stage === 3 ? "review_first_draft" : stage < 2 ? "outline_wait" : "review_outline", generated_content: stage === 3 ? "初稿正文" : state().outline, prompt_used: "" },
    outline_progress: { operation_id: lastOperation, revision, seq: 10 + stage + sequence,
      session: session(), live: null, control: { revision, paused, questions_stopped: stopped } },
  });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/game/scripts")) return json({ success: true, scripts: [] });
    if (path.endsWith("/model-health")) return json({ models: [] });
    if (path.endsWith("/capabilities")) return json({ models: [], features: {} });
    if (path.endsWith("/start")) return json({ success: true, thread_id: "co-thread", operation_id: "start", operation_status: "queued", target_step: "generate_outline" });
    if (path.endsWith("/state")) return json(response());
    if (path.includes("/operations/")) return json({ ...response(), operation_id: "start", operation_status: "complete" });
    if (path.endsWith("/history")) return json({ success: true, checkpoints: [
      { checkpoint_id: "now", current_step: "generate_outline", state: state() }, ...archived,
    ] });
    if (path.endsWith("/progress-stream")) return route.fulfill({ contentType: "text/event-stream",
      body: "data: " + JSON.stringify({ type: "outline_snapshot", data: response().outline_progress }) + "\n\n" });
    if (path.endsWith("/outline/actions")) {
      const cmd = route.request().postDataJSON();
      commands.push(cmd);
      lastOperation = cmd.request_id; sequence++;
      if (cmd.action === "save") savedOutline = cmd.content;
      if (cmd.action === "pause") paused = true;
      if (cmd.action === "continue") paused = false;
      if (cmd.action === "stop_questions") { stopped = true; stage = 2; }
      if (cmd.action === "answer" || cmd.action === "rewrite") {
        if (cmd.action === "rewrite") {
          archived.push({ checkpoint_id: "old-" + revision, current_step: "review_outline", state: structuredClone(state()) });
          revision += 1; stage = 0; answers = [];
        }
        const q = question(stage === 0 ? "q1" : "q2");
        answers.push({ source: "user", choice: cmd.option_id ? "旧案复仇" : "", other_text: cmd.other_text,
          question: q, option_id: cmd.option_id, segment_index: stage + 1 });
        stage = stopped ? 2 : stage + 1;
        paused = false;
      }
      return json({ success: true, thread_id: "co-thread", operation_id: cmd.request_id, operation_status: "complete", target_step: "outline_wait" });
    }
    if (path.endsWith("/resume")) { commands.push(route.request().postDataJSON()); stage = 3; return json({ ...response(), operation_id: "draft", operation_status: "complete" }); }
    return json({ success: true });
  });
  return commands;
}
async function begin(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /创作工坊/ }).click();
  await page.getByPlaceholder(/描述你想要创作的剧本杀故事构想/).fill("雾港灯塔中的旧案");
  await page.getByRole("button", { name: "开始创作" }).click();
  await expect(page.getByTestId("outline-workspace")).toBeVisible();
  await expect(page.getByText("您来确定剧情走向：")).toBeVisible();
}

test("大纲共创：标题、自由回答、改写与全文确认", async ({ page }) => {
  const commands = await setup(page);
  await begin(page);
  await expect(page.getByRole("dialog", { name: "创作小助手" })).not.toBeVisible();
  await page.getByRole("radio", { name: /旧案复仇/ }).click();
  await page.getByLabel("其他想法或补充说明").fill("希望有一名完全不知情的角色");
  await page.getByRole("button", { name: "按此方向继续" }).click();
  await expect(page.getByText("谁最想隐瞒这段往事？")).toBeVisible();
  await expect(page.getByRole("button", { name: /暂停创作|停止创作|重新整理/ })).toHaveCount(0);
  await page.getByRole("button", { name: "从这里修改" }).first().click();
  await page.getByLabel("其他想法或补充说明").fill("改为共同秘密，并保留温情结局");
  await page.getByRole("button", { name: "从这里重写后续", exact: true }).click();
  await expect(page.getByText("版本 2", { exact: true })).toBeVisible();
  await page.getByLabel("查看大纲版本").selectOption("1");
  await expect(page.getByText("正在查看旧版本；内容不会加入当前创作。")).toBeVisible();
  await expect(page.getByRole("button", { name: "停止提问" })).not.toBeVisible();
  await page.getByLabel("查看大纲版本").selectOption("");
  await page.getByRole("button", { name: "停止提问" }).click();
  await expect(page.getByRole("button", { name: "确认大纲，进入初稿" })).toBeVisible();
  await expect(page.getByTestId("outline-final-message")).toContainText("守夜人利用旧案");
  await page.reload();
  await expect(page.getByTestId("outline-final-message")).toHaveCount(1);
  await expect(page.getByText("完整大纲已整理", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新整理" })).toHaveCount(0);
  await page.getByRole("button", { name: "当前大纲", exact: true }).click();
  await expect(page.getByRole("heading", { name: "真相", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/outline-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "编辑全文", exact: true }).click();
  await page.getByLabel("编辑完整大纲").fill("# 雾港旧事\n人工调整后的大纲");
  await page.getByRole("button", { name: "确认大纲，进入初稿" }).click();
  await expect(page.getByText("初稿正文")).toBeVisible();
  expect(commands.find(c => c.action === "save")?.content).toBe("# 雾港旧事\n人工调整后的大纲");
  expect(commands.find(c => c.action === "confirm")?.content).toBe("# 雾港旧事\n人工调整后的大纲");
  expect(commands.filter(c => c.action === "answer")).toHaveLength(1);
  expect(commands.some(c => c.action === "rewrite")).toBe(true);
});

test("窄屏共创和小助手开关保留输入", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await begin(page);
  await page.getByLabel("其他想法或补充说明").fill("窄屏下保留这个输入");
  await page.getByRole("button", { name: "创作小助手", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "创作小助手" })).toBeVisible();
  await page.getByPlaceholder("输入消息...").fill("小助手中独立保留的草稿");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "创作小助手", exact: true }).click();
  await expect(page.getByPlaceholder("输入消息...")).toHaveValue("小助手中独立保留的草稿");
  await page.keyboard.press("Escape");
  await expect(page.getByLabel("其他想法或补充说明")).toHaveValue("窄屏下保留这个输入");
  await page.getByRole("button", { name: "当前大纲", exact: true }).click();
  await page.getByRole("button", { name: "共创对话", exact: true }).click();
  await expect(page.getByLabel("其他想法或补充说明")).toHaveValue("窄屏下保留这个输入");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/outline-mobile.png", fullPage: true });
});


test("首段在后台操作结束前流式显示，调度占位与最终正文原位保留", async ({ page }) => {
  await setup(page);
  let stream: ServerResponse | undefined;
  let step = "init";
  let seq = 1;
  const session = { protocol_version: 2, revision: 1, status: "writing", segments: [] as Array<{ id: string; content: string }>, decisions: [], pending_question: null, final_outline: "" };
  let live: { segment_id: string; attempt: number; text: string } | null = { segment_id: "s1", attempt: 1, text: "" };
  const snapshot = () => ({ operation_id: "stream-op", revision: 1, seq, session, live, control: { revision: 1, paused: false, questions_stopped: false } });
  const server = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Cache-Control": "no-cache" });
    if (req.method === "OPTIONS") { res.end(); return; }
    stream = res;
    res.write("data: " + JSON.stringify({ type: "outline_snapshot", data: snapshot() }) + "\n\n");
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as { port: number };
  const emit = (type: string, data: unknown) => stream!.write("data: " + JSON.stringify({ type, data }) + "\n\n");
  await page.route("**/progress-stream", route => route.continue({ url: `http://127.0.0.1:${address.port}/events` }));
  await page.route("**/operations/*", route => route.fulfill({ json: { operation_status: "running" } }));
  await page.route("**/state", route => route.fulfill({ json: { success: true, thread_id: "co-thread", current_step: step,
    state: { outline_session: session, user_idea: "流式回归", prompts: {}, script_title: "流式大纲", outline: session.final_outline },
    interrupt: step === "review_outline" ? { step } : null, outline_progress: snapshot() } }));
  try {
    await page.goto("/");
    await page.getByRole("button", { name: /创作工坊/ }).click();
    await expect(page.getByLabel("结局模式")).toHaveCount(0);
    await page.getByPlaceholder(/描述你想要创作的剧本杀故事构想/).fill("流式回归");
    await page.getByRole("button", { name: "开始创作" }).click();
    await expect(page.getByTestId("outline-workspace")).toBeVisible();
    await expect.poll(() => Boolean(stream)).toBe(true);
    const node = await page.getByTestId("outline-workspace").elementHandle();
    for (const chunk of ["第一批文字正在到达", "，后半段随后到达。"] ) {
      emit("outline_delta", { operation_id: "stream-op", revision: 1, seq: ++seq, segment_id: "s1", attempt: 1, offset: Array.from(live!.text).length, text: chunk });
      live!.text += chunk;
      await expect(page.getByTestId("outline-workspace")).toContainText(live!.text);
    }
    const ticking = setInterval(() => {
      const chunk = "续写。";
      emit("outline_delta", { operation_id: "stream-op", revision: 1, seq: ++seq, segment_id: "s1", attempt: 1, offset: Array.from(live!.text).length, text: chunk });
      live!.text += chunk;
    }, 30);
    try { await stressSelection(page, page.locator("article .markdown-content p").first(), 30); }
    finally { clearInterval(ticking); }
    // A pending operation and an init checkpoint must not unmount the SSE consumer.
    await page.waitForTimeout(2700);
    expect(await node!.evaluate(el => el.isConnected)).toBe(true);
    session.segments = [{ id: "s1", content: live!.text }];
    live = null; session.status = "directing"; seq++;
    emit("outline_segment_complete", snapshot());
    await expect(page.getByTestId("outline-writing-status")).toContainText("正在评估大纲后续发展");
    session.status = "finalizing"; live = { segment_id: "final", attempt: 1, text: "# 完整故事\n整理中的最终正文。" }; seq++;
    emit("outline_snapshot", snapshot());
    await expect(page.getByTestId("outline-final-message")).toContainText("整理中的最终正文");
    const finalNode = await page.getByTestId("outline-final-message").elementHandle();
    session.final_outline = live.text; session.status = "ready"; live = null; step = "review_outline"; seq++;
    emit("outline_segment_complete", snapshot());
    await expect(page.getByText("完整大纲已整理", { exact: true })).toBeVisible();
    expect(await finalNode!.evaluate(el => el.isConnected)).toBe(true);
    await expect(page.getByTestId("outline-final-message")).toHaveCount(1);
    await page.reload();
    await expect(page.getByTestId("outline-final-message")).toContainText("整理中的最终正文");
  } finally {
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  }
});

test("操作受理后状态查询失败不会锁住按钮，放弃确认框覆盖时间线", async ({ page }) => {
  await setup(page);
  await begin(page);
  await page.getByRole("radio", { name: /旧案复仇/ }).click();
  await page.route("**/state", route => route.fulfill({ status: 500, json: { detail: "测试状态查询失败" } }));
  await page.getByRole("button", { name: "按此方向继续" }).click();
  await expect(page.getByRole("button", { name: "停止提问", exact: true })).toBeEnabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.getByRole("button", { name: "放弃此剧本", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "放弃此剧本" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("opacity", "1");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../output/playwright/revised-discard-mobile.png", animations: "disabled" });
  const cancel = dialog.getByRole("button", { name: "取消", exact: true });
  expect(await cancel.evaluate(el => getComputedStyle(el).cursor)).toBe("pointer");
  const box = (await cancel.boundingBox())!;
  expect(await cancel.evaluate((el, p) => el.contains(document.elementFromPoint(p.x, p.y)), { x: box.x + box.width / 2, y: box.y + box.height / 2 })).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "放弃此剧本", exact: true })).toBeFocused();
});


test("大厅与共创正文连续选择后仍能取消选择、操作按钮和弹层", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await setup(page);
  await page.goto("/");
  await stressSelection(page, page.getByRole("heading", { name: "独醒", exact: true }));
  await begin(page);
  await stressSelection(page, page.locator("[data-testid=outline-workspace] article p").first());
  await page.getByRole("button", { name: "放弃此剧本", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "放弃此剧本" })).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await stressSelection(page, page.locator("[data-testid=outline-workspace] article p").first(), 15);
  await page.getByRole("button", { name: "当前大纲", exact: true }).click();
  await expect(page.getByRole("button", { name: "当前大纲", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.mouse.click(10, 10);
  expect(await page.evaluate(() => getSelection()?.toString())).toBe("");
  expect(errors).toEqual([]);
});


test("保存大纲留在确认节点，刷新保留全文，失败时不丢草稿也不进入初稿", async ({ page }) => {
  const commands = await setup(page);
  await begin(page);
  await page.getByRole("button", { name: "停止提问", exact: true }).click();
  await page.getByRole("button", { name: "编辑全文", exact: true }).click();
  const content = "# 手动保存的大纲\n保留最新剧情和末尾空格  ";
  await page.getByLabel("编辑完整大纲").fill(content);
  await page.getByRole("button", { name: "保存大纲", exact: true }).click();
  await expect(page.getByText("大纲已保存", { exact: true })).toBeVisible();
  expect(commands.filter(c => c.action === "confirm")).toHaveLength(0);
  await page.reload();
  await expect(page.getByTestId("outline-final-message")).toContainText("保留最新剧情和末尾空格");
  await page.getByRole("button", { name: "编辑全文", exact: true }).click();
  await expect(page.getByLabel("编辑完整大纲")).toHaveValue(content);
  await page.getByLabel("编辑完整大纲").fill(content + "\n尚未保存的修改");
  await page.route("**/outline/actions", route => route.fulfill({ status: 500, json: { detail: "保存测试失败" } }));
  await page.getByRole("button", { name: "确认大纲，进入初稿", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("保存测试失败");
  await expect(page.getByLabel("编辑完整大纲")).toHaveValue(content + "\n尚未保存的修改");
  await expect(page.getByRole("button", { name: "保存大纲", exact: true })).toBeEnabled();
  expect(commands.filter(c => c.action === "confirm")).toHaveLength(0);
});
