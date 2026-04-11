import { motion } from "framer-motion";
import { Users, Clock, Star } from "lucide-react";
import type { Script } from "@/types/game";
import { DIFFICULTY_COLORS } from "@/types/game";

interface ScriptCardProps {
  script: Script;
  onClick: () => void;
}

export function ScriptCard({ script, onClick }: ScriptCardProps) {
  const difficultyInfo =
    DIFFICULTY_COLORS[script.difficulty] || DIFFICULTY_COLORS[1];

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

        {/* Difficulty badge */}
        <div
          className={`absolute top-3 right-3 px-2 py-1 rounded-full text-xs font-medium
                        ${difficultyInfo.bg} ${difficultyInfo.text} border border-current/20`}
        >
          {difficultyInfo.label}
        </div>

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
        {script.tags && (
          <div className="flex flex-wrap gap-1.5">
            {script.tags
              .split(",")
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
            <span>{script.difficulty}.0</span>
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
    </motion.div>
  );
}
