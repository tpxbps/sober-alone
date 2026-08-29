export function getButtonLoadingMessage(step: string): string {
  const messages: Record<string, string> = {
    generate_outline: "正在构思剧本大纲...",
    generate_first_draft: "正在撰写初稿...",
    review_by_llm: "正在审稿并生成终稿（此阶段通常耗时较久）...",
    generate_final_draft: "正在根据审稿意见生成终稿（此阶段通常耗时较久）...",
    convert_to_game_data: "正在转化游戏数据...",
    safety_check: "正在进行剧本合规检查...",
    save_to_database: "正在保存...",
  };
  return messages[step] || "处理中...";
}
