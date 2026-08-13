import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileEdit, X, Save } from "lucide-react";

interface DraftNotebookProps {
  sessionId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function DraftNotebook({
  sessionId,
  open,
  onOpenChange,
}: DraftNotebookProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [content, setContent] = useState(() =>
    localStorage.getItem(
      sessionId ? `draft_notebook_${sessionId}` : "draft_notebook_temp",
    ) || "",
  );

  // 存储 key
  const storageKey = sessionId
    ? `draft_notebook_${sessionId}`
    : "draft_notebook_temp";

  // 保存草稿到 localStorage
  const saveDraft = useCallback(() => {
    localStorage.setItem(storageKey, content);
  }, [content, storageKey]);

  // 自动保存
  useEffect(() => {
    if (isOpen && content) {
      const timer = setTimeout(saveDraft, 1000);
      return () => clearTimeout(timer);
    }
  }, [content, isOpen, saveDraft]);

  const visible = isOpen || !!open;

  const handleOpen = () => {
    setIsOpen(true);
  };

  // 关闭时保存
  const handleClose = () => {
    saveDraft();
    setIsOpen(false);
    onOpenChange?.(false);
  };

  return (
    <>
      {/* Floating button - desktop only (hidden on mobile, toolbar provides button) */}
      <motion.button
        onClick={handleOpen}
        className="fixed bottom-6 right-24 z-40 w-14 h-14 rounded-full
                   bg-primary/90 hover:bg-primary text-foreground
                   shadow-lg hidden lg:flex items-center justify-center
                   transition-colors"
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        title="草稿本"
      >
        <FileEdit className="w-6 h-6" />
      </motion.button>

      {/* Modal */}
      <AnimatePresence>
        {visible && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={handleClose}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="bg-card rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header - 不显示icon */}
              <div className="flex items-center justify-between p-4 border-b border-border/50">
                <h3 className="text-lg font-bold">草稿本</h3>
                <button
                  onClick={handleClose}
                  className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Tips */}
              <div className="px-4 pt-3">
                <p className="text-xs text-muted-foreground">
                  在这里记录你的推理思路、线索整理或发言草稿。内容会自动保存到本地。
                </p>
              </div>

              {/* Content */}
              <div className="p-4">
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="开始记录你的想法...

例如：
- 嫌疑人分析：
  - 张三：动机不明确，但有不在场证明
  - 李四：与被害者有矛盾

- 关键线索：
  - 凶器是...
  - 案发时间是...

- 我的发言思路：
  ..."
                  className="w-full h-[50vh] p-4 rounded-lg bg-secondary/30 border border-border/50
                           focus:outline-none focus:ring-2 focus:ring-primary/50
                           resize-none text-sm leading-relaxed"
                />
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-border/50 bg-secondary/10">
                <span className="text-xs text-muted-foreground">
                  {content.length} 字符 · 自动保存
                </span>
                <button
                  onClick={handleClose}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground font-medium
                           hover:bg-primary/90 transition-colors flex items-center gap-2"
                >
                  <Save className="w-4 h-4" />
                  完成
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
