import { useState, useEffect, useCallback, useRef } from "react";
import { X } from "lucide-react";

interface WhackAMoleProps {
  onClose: () => void;
  isModal?: boolean;
}

const GRID_SIZE = 9;
const ROUND_DURATION = 30;
const MOLE_MAX_MS = 1600;
const SPAWN_MIN_MS = 300;
const SPAWN_MAX_MS = 700;

const HIT_EMOJIS = [
  "💫",
  "😵",
  "😣",
  "😭",
  "🤯",
  "⭐",
  "💥",
  "🔥",
  "💀",
  "😵‍💫",
  "🥴",
  "🙅",
  "😤",
];
const FIREWORK_COLORS = [
  "#ff6b6b",
  "#ffd93d",
  "#6bcb77",
  "#4d96ff",
  "#ff6bcb",
  "#ff9f43",
  "#a29bfe",
  "#00d2d3",
  "#f368e0",
  "#ff6348",
];

interface EmojiData {
  id: number;
  emoji: string;
  x: number;
  y: number;
  dx: number;
  born: number;
}
interface FireworkGroup {
  id: number;
  cx: number;
  cy: number;
  particles: { angle: number; color: string; distance: number }[];
}

let gc = 0;

export function WhackAMole({ onClose, isModal = true }: WhackAMoleProps) {
  const [moles, setMoles] = useState<number[]>(Array(GRID_SIZE).fill(0)); // timestamps, 0 = inactive
  const [hits, setHits] = useState<boolean[]>(Array(GRID_SIZE).fill(false)); // true = showing 💥
  const [score, setScore] = useState(0);
  const [timeLeft, setTimeLeft] = useState(ROUND_DURATION);
  const [emojis, setEmojis] = useState<EmojiData[]>([]);
  const [fireworkGroups, setFireworkGroups] = useState<FireworkGroup[]>([]);
  const [gameOver, setGameOver] = useState(false);
  const [gameKey, setGameKey] = useState(0);

  const holeRefs = useRef<(HTMLDivElement | null)[]>([]);
  const gridRef = useRef<HTMLDivElement>(null);
  const aliveRef = useRef(true);
  const gameOverRef = useRef(false);
  const lastSpawnRef = useRef(0);
  const elapsedRef = useRef(0);
  // Refs for latest state (avoid stale closures in interval)
  const molesRef = useRef(moles);
  const scoreRef = useRef(score);
  const hitsRef = useRef(hits);

  // Keep refs in sync
  useEffect(() => {
    molesRef.current = moles;
  }, [moles]);
  useEffect(() => {
    scoreRef.current = score;
  }, [score]);
  useEffect(() => {
    hitsRef.current = hits;
  }, [hits]);

  // Main game tick — single interval handles countdown, mole spawning, hiding, emoji cleanup
  useEffect(() => {
    const startTime = Date.now();
    gameOverRef.current = false;
    lastSpawnRef.current = 0;
    let countdownAcc = 0;
    let lastTick = startTime;

    const tick = () => {
      if (!aliveRef.current || gameOverRef.current) return;
      const now = Date.now();
      const dt = now - lastTick;
      lastTick = now;
      const elapsed = now - startTime;
      elapsedRef.current = Math.floor(elapsed / 1000);

      // Countdown
      countdownAcc += dt;
      if (countdownAcc >= 1000) {
        countdownAcc -= 1000;
        setTimeLeft((t) => {
          if (t <= 1) {
            gameOverRef.current = true;
            setGameOver(true);
            return 0;
          }
          return t - 1;
        });
        if (gameOverRef.current) return;
      }

      // Hide expired moles (check every tick)
      setMoles((prev) => {
        let changed = false;
        const next = [...prev];
        for (let i = 0; i < GRID_SIZE; i++) {
          if (next[i] > 0 && now - next[i] >= MOLE_MAX_MS) {
            next[i] = 0;
            changed = true;
          }
        }
        return changed ? next : prev;
      });

      // Spawn new moles
      const maxActive = elapsed < 10000 ? 3 : elapsed < 20000 ? 4 : 5;
      const timeSinceSpawn = now - lastSpawnRef.current;
      if (
        timeSinceSpawn >=
        SPAWN_MIN_MS + Math.random() * (SPAWN_MAX_MS - SPAWN_MIN_MS)
      ) {
        setMoles((prev) => {
          const activeCount = prev.filter((t) => t > 0).length;
          if (activeCount >= maxActive) return prev;
          const inactive = prev
            .map((t, i) => (t === 0 && !hitsRef.current[i] ? i : -1))
            .filter((i) => i >= 0);
          if (inactive.length === 0) return prev;
          const idx = inactive[Math.floor(Math.random() * inactive.length)];
          const next = [...prev];
          next[idx] = now; // timestamp = appeared at
          lastSpawnRef.current = now;
          return next;
        });
      }

      // Cleanup old emojis
      setEmojis((prev) =>
        prev.length > 0 ? prev.filter((e) => now - e.born < 700) : prev
      );
      // Cleanup old fireworks
      setFireworkGroups((prev) =>
        prev.length > 0 ? prev.filter((g) => now - g.id < 1200) : prev
      );
    };

    const interval = setInterval(tick, 80);
    return () => clearInterval(interval);
  }, [gameKey]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const whack = useCallback((index: number) => {
    // Check if mole is active using ref (avoids stale closure)
    if (molesRef.current[index] === 0) return;

    // Immediately deactivate mole
    setMoles((prev) => {
      if (prev[index] === 0) return prev; // already gone
      const next = [...prev];
      next[index] = 0;
      return next;
    });

    // Show hit animation
    setHits((prev) => {
      const next = [...prev];
      next[index] = true;
      return next;
    });
    setTimeout(() => {
      if (!aliveRef.current) return;
      setHits((prev) => {
        const next = [...prev];
        next[index] = false;
        return next;
      });
    }, 200);

    // Score — direct increment, outside setMoles
    setScore((s) => s + 1);

    // Spawn emoji
    const holeEl = holeRefs.current[index];
    const gridEl = gridRef.current;
    if (holeEl && gridEl) {
      const hr = holeEl.getBoundingClientRect();
      const gr = gridEl.getBoundingClientRect();
      const relX = ((hr.left + hr.width / 2 - gr.left) / gr.width) * 100;
      const relY = ((hr.top - gr.top) / gr.height) * 100;
      const dx = (Math.random() > 0.5 ? 1 : -1) * (10 + Math.random() * 8);
      setEmojis((prev) => [
        ...prev,
        {
          id: Date.now() + gc++,
          emoji: HIT_EMOJIS[Math.floor(Math.random() * HIT_EMOJIS.length)],
          x: relX,
          y: relY,
          dx,
          born: Date.now(),
        },
      ]);
    }
  }, []);

  const handleRestart = () => {
    setMoles(Array(GRID_SIZE).fill(0));
    setHits(Array(GRID_SIZE).fill(false));
    setScore(0);
    setTimeLeft(ROUND_DURATION);
    setGameOver(false);
    setEmojis([]);
    setFireworkGroups([]);
    gameOverRef.current = false;
    setGameKey((k) => k + 1);
  };

  // Game-over fireworks
  useEffect(() => {
    if (!gameOver) return;
    const burst = () => {
      if (!aliveRef.current) return;
      setFireworkGroups((prev) => {
        const trimmed = prev.length >= 5 ? prev.slice(-4) : prev;
        const newGroups: FireworkGroup[] = [];
        for (let g = 0; g < 2; g++) {
          const cx = 10 + Math.random() * 80;
          const cy = 10 + Math.random() * 80;
          const particleCount = 8 + Math.floor(Math.random() * 6);
          const particles = [];
          for (let i = 0; i < particleCount; i++) {
            particles.push({
              angle:
                (Math.PI * 2 * i) / particleCount + (Math.random() - 0.5) * 0.3,
              color:
                FIREWORK_COLORS[
                  Math.floor(Math.random() * FIREWORK_COLORS.length)
                ],
              distance: 30 + Math.random() * 50,
            });
          }
          newGroups.push({ id: Date.now() + gc++, cx, cy, particles });
        }
        return [...trimmed, ...newGroups];
      });
    };
    burst();
    const interval = setInterval(burst, 300);
    return () => clearInterval(interval);
  }, [gameOver]);

  const gameContent = (
    <div
      className="relative bg-card border border-border/50 rounded-2xl shadow-2xl p-4 w-[320px] select-none overflow-hidden"
      style={{ contain: "layout style paint" }}
    >
      <button
        onClick={onClose}
        className="absolute top-2.5 right-2.5 text-muted-foreground hover:text-foreground transition-colors z-40"
      >
        <X className="w-4 h-4" />
      </button>

      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold">打地鼠</h3>
          <p className="text-[10px] text-muted-foreground">
            点击冒出的地鼠得分!
          </p>
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-primary">{score}</div>
          <div
            className={`text-[10px] font-mono ${
              timeLeft <= 5
                ? "text-red-400 animate-pulse"
                : "text-muted-foreground"
            }`}
          >
            {timeLeft}s
          </div>
        </div>
      </div>

      <div className="w-full h-1 bg-secondary rounded-full mb-3 overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-1000 ease-linear rounded-full"
          style={{ width: `${(timeLeft / ROUND_DURATION) * 100}%` }}
        />
      </div>

      <div
        ref={gridRef}
        className="relative grid grid-cols-3 gap-2 mx-auto"
        style={{ width: "fit-content" }}
      >
        {moles.map((appearedAt, i) => (
          <div
            key={i}
            ref={(el) => {
              holeRefs.current[i] = el;
            }}
            onClick={() => whack(i)}
            className="w-[88px] h-[88px] rounded-full bg-secondary/60 border-2 border-border/40 flex items-center justify-center cursor-pointer relative overflow-hidden active:scale-90 transition-transform"
          >
            <div className="absolute inset-2 rounded-full bg-secondary/80" />
            {appearedAt > 0 && (
              <div className="text-3xl animate-[mole-pop_0.2s_ease-out] z-10">
                🐹
              </div>
            )}
            {hits[i] && (
              <div className="text-2xl animate-[hit-boom_0.2s_ease-out_forwards] z-10">
                💥
              </div>
            )}
          </div>
        ))}

        {emojis.map((fe) => (
          <div
            key={fe.id}
            className="absolute pointer-events-none z-20"
            style={
              {
                left: `${fe.x}%`,
                top: `${fe.y}%`,
                animation: "emoji-float 0.6s ease-out forwards",
                willChange: "transform, opacity",
                "--emoji-dx": `${fe.dx}px`,
              } as React.CSSProperties
            }
          >
            <span className="text-2xl relative inline-flex items-center justify-center w-8 h-8">
              <span className="absolute inset-0 rounded-full bg-white/20 backdrop-blur-[1px]" />
              <span className="relative">{fe.emoji}</span>
            </span>
          </div>
        ))}
      </div>

      {gameOver && (
        <div className="absolute inset-0 bg-card/85 backdrop-blur-sm rounded-2xl flex flex-col items-center justify-center gap-3 z-30 overflow-hidden">
          {fireworkGroups.map((group) => (
            <div
              key={group.id}
              className="absolute inset-0 pointer-events-none z-30"
            >
              {group.particles.map((p, pi) => (
                <div
                  key={pi}
                  className="absolute"
                  style={
                    {
                      left: `${group.cx}%`,
                      top: `${group.cy}%`,
                      animation: "firework-bloom 0.9s ease-out forwards",
                      "--fw-dx": `${Math.cos(p.angle) * p.distance}px`,
                      "--fw-dy": `${Math.sin(p.angle) * p.distance}px`,
                    } as React.CSSProperties
                  }
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{
                      backgroundColor: p.color,
                      boxShadow: `0 0 4px ${p.color}`,
                    }}
                  />
                </div>
              ))}
            </div>
          ))}
          <div className="text-3xl relative z-30">🎉</div>
          <h3 className="text-lg font-bold relative z-30">时间到!</h3>
          <p className="text-sm text-muted-foreground relative z-30">
            最终得分: <span className="text-primary font-bold">{score}</span>
          </p>
          <div className="flex gap-2 relative z-30">
            <button
              onClick={handleRestart}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
            >
              再来一局
            </button>
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-secondary text-sm font-medium hover:bg-secondary/80 transition-colors"
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );

  if (isModal) {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        {gameContent}
      </div>
    );
  }
  return gameContent;
}

export function MoleTrigger({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-amber-500/20 hover:bg-amber-500/40 transition-all animate-bounce cursor-pointer"
      title="打地鼠小游戏"
    >
      <span className="text-sm leading-none">🐹</span>
    </button>
  );
}
