import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Users,
  Clock,
  Star,
  MoreVertical,
  Trash2,
  Sparkles,
} from "lucide-react";
import type { Script } from "@/types/game";
import { DIFFICULTY_COLORS } from "@/types/game";
import { editorApi } from "@/lib/editorApi";

interface ScriptCardProps {
  script: Script;
  onClick: () => void;
  onDeleted?: () => void;
}

export function ScriptCard({ script, onClick, onDeleted }: ScriptCardProps) {
  const difficultyInfo =
    DIFFICULTY_COLORS[script.difficulty] || DIFFICULTY_COLORS[1];

  const [showMenu, setShowMenu] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭菜单
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    if (showMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showMenu]);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await editorApi.deleteScript(script.script_id);
      setShowDeleteConfirm(false);
      setShowMenu(false);
      onDeleted?.();
    } catch {
      // Error handled silently
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <motion.div
      whileHover={{ y: -8, scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      onClick={onClick}
      className="relative group cursor-pointer rounded-xl overflow-hidden border border-border/50
                 bg-gradient-to-br from-card to-card/80 hover:border-primary/50
                 transition-colors duration-150"
    >
      {/* Cover Image */}
      <div className="relative h-48 overflow-hidden">
        {script.cover_image_url ? (
          <img
            src={script.cover_image_url}
            alt={script.title}
            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-primary/20 to-accent/20 flex items-center justify-center">
            <span className="text-4xl text-primary/50 font-bold">
              {script.title[0]}
            </span>
          </div>
        )}

        {/* Overlay gradient */}
        <div className="absolute inset-0 bg-gradient-to-t from-background/90 via-background/20 to-transparent" />
        {script.cover_image_url && (
          <span className="absolute bottom-3 right-3 px-2 py-0.5 rounded bg-black/70 text-white text-[10px]">
            AI 生成图片
          </span>
        )}

        {/* Difficulty badge */}
        <div
          className={`absolute top-3 right-3 px-2 py-1 rounded-full text-xs font-medium
                        ${difficultyInfo.bg} ${difficultyInfo.text} border border-current/20`}
        >
          {difficultyInfo.label}
        </div>

        {/* Local single-user script menu */}
        {script.is_ai_generated && (
          <div ref={menuRef} className="absolute top-3 left-3 z-10">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowMenu(!showMenu);
              }}
              className="p-1.5 rounded-lg bg-background/60 hover:bg-background/80 backdrop-blur-sm transition-colors"
            >
              <MoreVertical className="w-4 h-4" />
            </button>

            {showMenu && (
              <div className="absolute left-0 top-full mt-1 bg-card border border-border rounded-lg shadow-lg py-1 min-w-[120px] z-20">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowDeleteConfirm(true);
                    setShowMenu(false);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-400 hover:bg-secondary/50 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  删除剧本
                </button>
              </div>
            )}
          </div>
        )}

        {/* Title on image */}
        <div className="absolute bottom-3 left-3 right-3">
          <h3 className="text-lg font-bold text-foreground text-glow truncate">
            {script.title}
          </h3>
        </div>
      </div>

      {/* Info section */}
      <div className="p-4 space-y-3">
        {/* Tags */}
        {(script.tags || script.is_ai_generated) && (
          <div className="flex flex-wrap gap-1.5">
            {script.is_ai_generated && (
              <span className="px-2 py-0.5 text-xs rounded-full bg-primary/15 text-primary flex items-center gap-1 font-medium">
                <Sparkles className="w-3 h-3" />
                AI 生成
              </span>
            )}
            {script.tags &&
              script.tags
                .split(",")
                .filter(
                  (tag) =>
                    tag.trim() !== "AI创作" &&
                    tag.trim() !== "AI辅助" &&
                    tag.trim() !== "用户创作"
                )
                .slice(0, 3)
                .map((tag, index) => (
                  <span
                    key={index}
                    className="px-2 py-0.5 text-xs rounded-full bg-secondary/50 text-secondary-foreground"
                  >
                    {tag.trim()}
                  </span>
                ))}
          </div>
        )}

        {/* Stats */}
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Users className="w-4 h-4" />
            <span>{script.player_count}人</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="w-4 h-4" />
            <span>{script.estimated_duration}分钟</span>
          </div>
          <div className="flex items-center gap-1.5 ml-auto">
            <Star className="w-4 h-4 text-warning" />
            <span>5.0</span>
          </div>
        </div>

        {/* Overview */}
        <p className="text-sm text-muted-foreground line-clamp-2">
          {script.overview || script.description}
        </p>
      </div>

      {/* Hover glow effect */}
      <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
        <div className="absolute inset-0 rounded-xl glow" />
      </div>

      {/* Delete confirmation modal */}
      {showDeleteConfirm && (
        <div
          className="absolute inset-0 z-30 bg-background/95 backdrop-blur-sm flex items-center justify-center rounded-xl"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="text-center p-4 space-y-3">
            <p className="text-sm font-medium">确认删除「{script.title}」？</p>
            <p className="text-xs text-muted-foreground">此操作不可恢复</p>
            <div className="flex items-center gap-2 justify-center">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowDeleteConfirm(false);
                }}
                className="px-3 py-1.5 text-sm rounded-lg bg-secondary hover:bg-secondary/80 transition-colors"
              >
                取消
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete();
                }}
                disabled={isDeleting}
                className="px-3 py-1.5 text-sm rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50"
              >
                {isDeleting ? "删除中..." : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
