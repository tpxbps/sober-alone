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
  let answers: Array<Record<string, unknown>> = [];
  const archived: unknown[] = [];
  const commands: Record<string, unknown>[] = [];
  const session = () => ({
    protocol_version: 2, revision, status: stage < 2 ? "awaiting_answer" : "ready",
    segments: [{ id: "s1", content: "浓雾封住了码头，四名故人被困在旧灯塔。午夜，值守人离奇死亡。" },
      ...(stage > 0 ? [{ id: "s2", content: "十年前的失踪案再次浮现，四人的证词无法拼成完整的一夜。" }] : [])],
    decisions: answers, pending_question: stage < 2 ? question(stage === 0 ? "q1" : "q2") : null,
    questions_asked: stage + 1, questions_stopped: stopped,
    final_outline: stage >= 2 ? "# 雾港旧事\n\n四名故人的秘密构成了完整的案件大纲。\n\n## 真相\n守夜人利用旧案引出真正的幕后者。" : "",
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
    outline_progress: { operation_id: "op-" + stage + "-" + revision, revision, seq: 10 + stage,
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
    if (path.endsWith("/resume")) { stage = 3; return json({ ...response(), operation_id: "draft", operation_status: "complete" }); }
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

test("大纲共创：标题、自由回答、暂停恢复、改写与全文确认", async ({ page }) => {
  const commands = await setup(page);
  await begin(page);
  await expect(page.getByRole("dialog", { name: "创作小助手" })).not.toBeVisible();
  await page.getByRole("radio", { name: /旧案复仇/ }).click();
  await page.getByLabel("其他想法或补充说明").fill("希望有一名完全不知情的角色");
  await page.getByRole("button", { name: "按此方向继续" }).click();
  await expect(page.getByText("谁最想隐瞒这段往事？")).toBeVisible();
  await page.getByRole("button", { name: "暂停创作", exact: true }).click();
  await expect(page.getByRole("button", { name: "继续创作", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续创作", exact: true }).click();
  await page.getByRole("button", { name: "从这里修改" }).first().click();
  await page.getByLabel("其他想法或补充说明").fill("改为共同秘密，并保留温情结局");
  await page.getByRole("button", { name: "从这里重写后续", exact: true }).click();
  await expect(page.getByText("版本 2", { exact: true })).toBeVisible();
  await page.getByLabel("查看大纲版本").selectOption("1");
  await expect(page.getByText("正在查看旧版本；内容不会加入当前创作。")).toBeVisible();
  await expect(page.getByRole("button", { name: "停止提问，AI 继续完成" })).not.toBeVisible();
  await page.getByLabel("查看大纲版本").selectOption("");
  await page.getByRole("button", { name: "停止提问，AI 继续完成" }).click();
  await expect(page.getByRole("button", { name: "确认大纲，进入初稿" })).toBeVisible();
  await page.getByRole("button", { name: "当前大纲", exact: true }).click();
  await expect(page.getByRole("heading", { name: "真相", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/outline-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "编辑全文", exact: true }).click();
  await page.getByLabel("编辑完整大纲").fill("# 雾港旧事\n人工调整后的大纲");
  await page.getByRole("button", { name: "确认大纲，进入初稿" }).click();
  await expect(page.getByText("初稿正文")).toBeVisible();
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
