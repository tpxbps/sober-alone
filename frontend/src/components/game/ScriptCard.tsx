import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { StoryCover } from "@/components/lobby/StoryCover";
import {
  Users,
  Clock,
  MoreVertical,
  Trash2,
  Sparkles,
  Pencil,
} from "lucide-react";
import { ScriptRating } from "./ScriptRating";
import type { Script } from "@/types/game";
import { editorApi } from "@/lib/editorApi";
import { getScriptDisplayTags } from "@/lib/scriptDisplay";

interface ScriptCardProps {
  script: Script;
  onClick: () => void;
  onDeleted?: () => void;
  onEdit?: () => void;
  quiet?: boolean;
  selected?: boolean;
  previewsEnabled?: boolean;
}

export function ScriptCard({ script, onClick, onDeleted, onEdit, quiet = false, selected = false, previewsEnabled = true }: ScriptCardProps) {
  const displayTags = getScriptDisplayTags(script);

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
      whileTap={quiet ? undefined : { scale: 0.995 }}
      data-script-id={script.script_id}
      data-selected={selected || undefined}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      onClick={onClick}
      className="lobby-card relative group cursor-pointer overflow-hidden border border-border/50"
    >
      {/* Cover Image */}
      <div className="relative h-48 overflow-hidden">
        <StoryCover src={script.cover_image_url} variants={script.cover_image_variants} alt={script.title} loading="lazy" className="card-cover-media w-full h-full object-cover" />

        {/* Overlay gradient */}
        <div className="absolute inset-0 bg-gradient-to-t from-background/30 via-transparent to-transparent" />
        {/* Local single-user script menu */}
        {script.can_manage && (
          <div ref={menuRef} className="absolute top-3 left-3 z-10">
            <button
              aria-label={`管理剧本 ${script.title}`}
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
                    setShowMenu(false);
                    onEdit?.();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-secondary/50 transition-colors"
                >
                  <Pencil className="w-3.5 h-3.5" />
                  编辑剧本
                </button>
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

      </div>

      {/* Info section */}
      <div className="card-info p-4 space-y-3">
        <h3 className="card-title"><button data-script-open type="button" aria-label={"打开剧本 " + script.title} onClick={event => { event.stopPropagation(); onClick(); }}>{script.title}</button></h3>
        {/* Tags */}
        {displayTags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {displayTags.slice(0, 3).map((tag, index) =>
              tag === "创作工坊" ? (
                <span
                  key={tag}
                  className="px-2 py-0.5 text-xs rounded-full bg-primary/15 text-primary flex items-center gap-1 font-medium"
                >
                  <Sparkles className="w-3 h-3" />
                  创作工坊
                </span>
              ) : (
                  <span
                    key={`${tag}-${index}`}
                    className="px-2 py-0.5 text-xs rounded-full bg-secondary/50 text-secondary-foreground"
                  >
                    {tag}
                  </span>
              ),
            )}
          </div>
        )}

        {/* Stats */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
          <div className="flex shrink-0 items-center gap-1">
            <Users className="w-3.5 h-3.5" />
            <span>{script.player_count}人</span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Clock className="w-3.5 h-3.5" />
            <span>{script.estimated_duration}分钟</span>
          </div>
          <ScriptRating script={script} disabled={!previewsEnabled || showMenu || showDeleteConfirm} />
        </div>

        {/* Overview */}
        <p className="card-overview text-sm text-muted-foreground line-clamp-2">
          {script.overview || script.description}
        </p>
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
