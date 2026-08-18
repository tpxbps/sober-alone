import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Settings, RefreshCw, PenTool } from "lucide-react";
import { scriptApi } from "@/lib/api";
import { ScriptCard } from "@/components/game/ScriptCard";
import { ScriptDetailModal } from "@/components/game/ScriptDetailModal";
import { SettingsModal } from "@/components/SettingsModal";
import { BookIcon } from "@/components/ui/BookIcon";
import type { Script } from "@/types/game";

interface HomepageProps {
  onStartGame: (sessionId: string) => void;
  onOpenEditor: () => void;
}

export function Homepage({ onStartGame, onOpenEditor }: HomepageProps) {
  const [scripts, setScripts] = useState<Script[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedScript, setSelectedScript] = useState<Script | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  // Load scripts
  const loadScripts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await scriptApi.listScripts();
      setScripts(response.scripts || []);
    } catch (err) {
      console.error("Failed to load scripts:", err);
      setError("加载剧本失败，请稍后重试");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadScripts();
  }, []);

  // Group scripts by difficulty
  const scriptsByDifficulty = scripts.reduce((acc, script) => {
    const key = script.difficulty || 1;
    if (!acc[key]) acc[key] = [];
    acc[key].push({
      ...script,
      estimated_duration: script.estimated_duration ?? 0,
    });
    return acc;
  }, {} as Record<number, Script[]>);

  const difficultyLabels: Record<number, string> = {
    1: "简单",
    2: "中等",
    3: "困难",
    4: "极难",
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-border/50 bg-background/80 backdrop-blur-xl">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            {/* Logo */}
            <div className="flex items-center gap-3">
              <BookIcon size={48} />
              <div>
                <h1 className="text-xl font-bold text-glow">独醒</h1>
                <p className="text-xs text-muted-foreground">AI剧本杀</p>
              </div>
            </div>

            {/* Nav */}
            <nav className="flex items-center gap-4">
              <button
                onClick={onOpenEditor}
                className="relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-sm font-medium"
              >
                <PenTool className="w-4 h-4" />
                <span className="hidden sm:inline">创作工坊</span>
                <span className="absolute -top-1.5 -right-1.5 px-1 py-0.5 rounded text-[9px] leading-none bg-violet-500 text-white">
                  Beta
                </span>
              </button>
              <button
                onClick={loadScripts}
                disabled={isLoading}
                className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                title="刷新剧本"
              >
                <RefreshCw
                  className={`w-5 h-5 ${isLoading ? "animate-spin" : ""}`}
                />
              </button>
              <button
                onClick={() => setShowSettings(true)}
                className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                title="设置"
              >
                <Settings className="w-5 h-5" />
              </button>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-6 py-8 flex-1">
        {/* Hero Section */}
        <div className="text-center mb-12">
          <motion.h2
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-3xl md:text-4xl font-bold mb-4"
          >
            <span className="text-glow">剧本大厅</span>
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="text-muted-foreground max-w-xl mx-auto"
          >
            选择一个剧本，开始你的推理之旅，与AI角色一起揭开真相。
          </motion.p>
        </div>

        {/* Error State */}
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center py-12"
          >
            <p className="text-danger mb-4">{error}</p>
            <button
              onClick={loadScripts}
              className="px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors"
            >
              重试
            </button>
          </motion.div>
        )}

        {/* Loading State */}
        {isLoading && !error && (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="w-12 h-12 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-muted-foreground">加载剧本中...</p>
            </div>
          </div>
        )}

        {/* Scripts Grid */}
        {!isLoading && !error && scripts.length > 0 && (
          <div className="space-y-12">
            {Object.entries(scriptsByDifficulty)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([difficulty, scriptsInGroup], groupIndex) => (
                <motion.section
                  key={difficulty}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: groupIndex * 0.1 }}
                >
                  <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-primary" />
                    {difficultyLabels[Number(difficulty)] || "未知难度"}
                    <span className="text-sm text-muted-foreground font-normal">
                      ({scriptsInGroup.length})
                    </span>
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                    {scriptsInGroup.map((script, index) => (
                      <motion.div
                        key={script.script_id}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.05 }}
                      >
                        <ScriptCard
                          script={script}
                          onClick={() => setSelectedScript(script)}
                          onDeleted={loadScripts}
                        />
                      </motion.div>
                    ))}
                  </div>
                </motion.section>
              ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && !error && scripts.length === 0 && (
          <div className="text-center py-20">
            <div
              className="w-20 h-20 rounded-full bg-secondary/30 mx-auto mb-6
                          flex items-center justify-center"
            >
              <BookIcon size={80} />
            </div>
            <h3 className="text-xl font-semibold mb-2">暂无剧本</h3>
            <p className="text-muted-foreground">
              管理员尚未添加任何剧本，请稍后再来。
            </p>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-border/30 py-6 mt-auto">
        <div className="container mx-auto px-6 text-center text-sm text-muted-foreground">
          <div className="flex flex-wrap items-center justify-center gap-1">
            <p>© 2026 独醒 AI剧本杀 · 众人皆醉我独醒</p>
          </div>
        </div>
      </footer>

      {/* Script Detail Modal */}
      {selectedScript && (
        <ScriptDetailModal
          script={selectedScript}
          open={!!selectedScript}
          onClose={() => setSelectedScript(null)}
          onStartGame={onStartGame}
        />
      )}

      {/* Settings Modal */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} />
        )}
      </AnimatePresence>
    </div>
  );
}
