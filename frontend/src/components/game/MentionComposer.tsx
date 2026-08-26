import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { Character } from "@/types/game";

export interface MentionComposerHandle {
  focus: () => void;
  insertMention: (character: Character) => void;
  clear: () => void;
}

interface MentionComposerProps {
  characters: Character[];
  disabled?: boolean;
  maxLength?: number;
  onChange: (text: string) => void;
  onCtrlEnter: () => void;
  onEnter: () => void;
}

function serialize(root: HTMLElement): string {
  const walk = (node: Node): string => {
    if (node instanceof HTMLElement && node.dataset.mentionName) {
      return `@${node.dataset.mentionName}`;
    }
    if (node.nodeName === "BR") return "\n";
    if (node.nodeType === Node.TEXT_NODE) return node.textContent || "";
    return Array.from(node.childNodes).map(walk).join("");
  };
  return walk(root).replace(/\u00a0/g, " ");
}

export const MentionComposer = forwardRef<MentionComposerHandle, MentionComposerProps>(
  function MentionComposer(
    { characters, disabled, maxLength = 3000, onChange, onCtrlEnter, onEnter },
    forwardedRef
  ) {
    const editorRef = useRef<HTMLDivElement>(null);
    const savedRangeRef = useRef<Range | null>(null);
    const triggerRangeRef = useRef<Range | null>(null);
    const [query, setQuery] = useState<string | null>(null);
    const [activeIndex, setActiveIndex] = useState(0);

    const filtered = useMemo(() => {
      const needle = (query || "").toLocaleLowerCase();
      return characters.filter((item) => item.name.toLocaleLowerCase().includes(needle));
    }, [characters, query]);

    const emit = () => {
      const root = editorRef.current;
      if (!root) return;
      const text = serialize(root);
      if (text.length > maxLength) {
        root.textContent = text.slice(0, maxLength);
        onChange(text.slice(0, maxLength));
      } else {
        onChange(text);
      }
    };

    const rememberCaretAndTrigger = () => {
      const root = editorRef.current;
      const selection = window.getSelection();
      if (!root || !selection?.rangeCount) return;
      const range = selection.getRangeAt(0);
      if (!root.contains(range.commonAncestorContainer)) return;
      savedRangeRef.current = range.cloneRange();
      if (range.collapsed && range.startContainer.nodeType === Node.TEXT_NODE) {
        const before = (range.startContainer.textContent || "").slice(0, range.startOffset);
        const match = before.match(/@([^@\s]*)$/);
        if (match) {
          const trigger = range.cloneRange();
          trigger.setStart(range.startContainer, range.startOffset - match[0].length);
          triggerRangeRef.current = trigger;
          setQuery(match[1]);
          setActiveIndex(0);
          return;
        }
      }
      triggerRangeRef.current = null;
      setQuery(null);
    };

    const insertMention = (character: Character) => {
      const root = editorRef.current;
      if (!root || disabled) return;
      root.focus();
      const selection = window.getSelection();
      const range = triggerRangeRef.current || savedRangeRef.current || document.createRange();
      if (!root.contains(range.commonAncestorContainer)) {
        range.selectNodeContents(root);
        range.collapse(false);
      }
      range.deleteContents();
      const chip = document.createElement("span");
      chip.contentEditable = "false";
      chip.dataset.mentionName = character.name;
      chip.className = "inline-flex items-center gap-1 mx-0.5 px-1.5 py-0.5 rounded-full bg-primary/15 text-primary align-middle select-all";
      if (character.avatar_url) {
        const image = document.createElement("img");
        image.src = character.avatar_url;
        image.alt = "";
        image.className = "w-4 h-4 rounded-full object-cover";
        chip.append(image);
      }
      chip.append(document.createTextNode(`@${character.name}`));
      range.insertNode(chip);
      const spacer = document.createTextNode(" ");
      chip.after(spacer);
      range.setStartAfter(spacer);
      range.collapse(true);
      selection?.removeAllRanges();
      selection?.addRange(range);
      savedRangeRef.current = range.cloneRange();
      triggerRangeRef.current = null;
      setQuery(null);
      emit();
    };

    useImperativeHandle(forwardedRef, () => ({
      focus: () => editorRef.current?.focus(),
      insertMention,
      clear: () => {
        if (editorRef.current) editorRef.current.replaceChildren();
        onChange("");
      },
    }));

    return (
      <div className="relative flex-1">
        <div
          ref={editorRef}
          role="textbox"
          aria-multiline="true"
          aria-label="发言输入框"
          contentEditable={!disabled}
          data-placeholder="输入你的发言，输入 @ 可快捷选择角色…"
          onInput={() => {
            emit();
            rememberCaretAndTrigger();
          }}
          onKeyUp={(event) => {
            // Navigation is handled during keydown. Re-running mention detection
            // on keyup would reset activeIndex to the first option.
            if (["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) {
              return;
            }
            rememberCaretAndTrigger();
          }}
          onMouseUp={rememberCaretAndTrigger}
          onPaste={(event) => {
            event.preventDefault();
            document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
          }}
          onKeyDown={(event) => {
            if (query !== null && filtered.length) {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const delta = event.key === "ArrowDown" ? 1 : -1;
                setActiveIndex((index) => (index + delta + filtered.length) % filtered.length);
                return;
              }
              if (event.key === "Enter" || event.key === "Tab") {
                event.preventDefault();
                insertMention(filtered[activeIndex] || filtered[0]);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setQuery(null);
                return;
              }
            }
            if (event.key === "Enter" && event.ctrlKey) {
              event.preventDefault();
              onCtrlEnter();
            } else if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onEnter();
            }
          }}
          className="min-h-[76px] w-full pl-3 pr-14 py-2 lg:pl-4 lg:py-3 rounded-xl bg-secondary/30 border border-border/50 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50 text-sm whitespace-pre-wrap break-words empty:before:content-[attr(data-placeholder)] empty:before:text-muted-foreground/60 empty:before:pointer-events-none"
        />
        {!disabled && query !== null && filtered.length > 0 && (
          <div
            role="listbox"
            aria-label="可引用角色"
            className="absolute bottom-full left-0 mb-2 w-64 max-h-56 overflow-y-auto rounded-xl border border-border bg-popover shadow-xl z-50 p-1"
          >
            {filtered.map((character, index) => (
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                key={character.character_id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insertMention(character)}
                className={`w-full flex items-center gap-2 rounded-lg p-2 text-left text-sm ${index === activeIndex ? "bg-primary/15" : "hover:bg-secondary/60"}`}
              >
                <span className="w-7 h-7 rounded-full overflow-hidden bg-primary/20 flex items-center justify-center shrink-0">
                  {character.avatar_url ? <img src={character.avatar_url} alt="" className="w-full h-full object-cover" /> : character.name[0]}
                </span>
                <span>@{character.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }
);
