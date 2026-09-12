import { LoadingButton } from "./EditorControls";

export function IdeaStage({
  userIdea,
  setUserIdea,
  playerCount,
  setPlayerCount,
  difficulty,
  setDifficulty,
  numClueRounds,
  setNumClueRounds,
  error,
  isStarting,
  onStart,
  moleActive,
}: {
  userIdea: string;
  setUserIdea: (value: string) => void;
  playerCount: number;
  setPlayerCount: (value: number) => void;
  difficulty: number;
  setDifficulty: (value: number) => void;
  numClueRounds: number;
  setNumClueRounds: (value: number) => void;
  error: string | null;
  isStarting: boolean;
  onStart: (params: {
    user_idea: string;
    player_count: number;
    difficulty: number;
    num_clue_rounds: number;
  }) => void;
  moleActive: boolean;
}) {
  return (
    <div className="h-full flex flex-col">
      <div className="p-5 flex-1 overflow-y-auto scrollbar-thin">
        <h3 className="text-lg font-bold mb-4">构思你的剧本</h3>
        <p className="text-xs text-muted-foreground mb-4">
          描述你的剧本创意、故事背景、核心设定等。越详细，AI生成的大纲越贴合你的想法。
        </p>
        <textarea
          value={userIdea}
          onChange={(e) => setUserIdea(e.target.value)}
          placeholder="描述你想要创作的剧本杀故事构想。可以包含：故事背景、人物关系、核心冲突、悬疑元素等。例如：一所与世隔绝的山间别墅中，六位受邀而来的客人发现主人离奇失踪，暴风雪封山之夜，他们必须找出真相……"
          className="w-full h-[30vh] px-4 py-3 rounded-lg border border-border/50 bg-card text-sm resize-none focus:outline-none focus:border-primary/50 transition-colors placeholder:text-muted-foreground/50 scrollbar-thin"
        />
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div>
            <label className="block text-xs font-medium mb-1">
              玩家人数
            </label>
            <select
              value={playerCount}
              onChange={(e) => setPlayerCount(Number(e.target.value))}
              className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
            >
              {[3, 4, 5, 6, 7, 8].map((n) => (
                <option key={n} value={n}>
                  {n}人
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1">难度</label>
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(Number(e.target.value))}
              className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
            >
              {[
                { v: 1, l: "简单" },
                { v: 2, l: "中等" },
                { v: 3, l: "困难" },
                { v: 4, l: "极难" },
              ].map((d) => (
                <option key={d.v} value={d.v}>
                  {d.l}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1">
              线索轮次
            </label>
            <select
              value={numClueRounds}
              onChange={(e) => setNumClueRounds(Number(e.target.value))}
              className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}轮
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-xs text-muted-foreground/60 mt-3">
          预估游戏时长：
          {estimateDuration(playerCount, difficulty, numClueRounds)}
        </p>
        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
      </div>
      <div
        className={`p-4 ${
          moleActive ? "pl-12" : ""
        } border-t border-border/30`}
      >
        <LoadingButton
          isLoading={isStarting}
          loadingText="正在构思剧本大纲..."
          onClick={() =>
            onStart({
              user_idea: userIdea,
              player_count: playerCount,
              difficulty,
              num_clue_rounds: numClueRounds,
            })
          }
          label="开始创作"
          disabled={!userIdea.trim()}
        />
      </div>
    </div>
  );
}

function estimateDuration(
  players: number,
  difficulty: number,
  rounds: number
): string {
  const base = 15 + (players - 3) * 10;
  const diffMult = [1.0, 1.2, 1.5, 1.8][difficulty - 1] ?? 1.0;
  const total = Math.round(base * diffMult + (rounds - 1) * 15);
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours > 0 && mins > 0) return `约${hours}小时${mins}分钟`;
  if (hours > 0) return `约${hours}小时`;
  return `约${mins}分钟`;
}

