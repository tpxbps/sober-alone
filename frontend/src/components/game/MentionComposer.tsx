import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { Search } from "lucide-react";

import type { Character, PublicClue } from "@/types/game";

export interface MentionComposerHandle {
  focus: () => void;
  insertMention: (character: Character) => void;
  clear: () => void;
}

interface MentionComposerProps {
  characters: Character[];
  clues: PublicClue[];
  disabled?: boolean;
  maxLength?: number;
  onChange: (text: string) => void;
  onCtrlEnter: () => void;
  onEnter: () => void;
}

type Trigger = { kind: "mention" | "clue"; query: string } | null;

function serialize(root: HTMLElement): string {
  const walk = (node: Node): string => {
    if (node instanceof HTMLElement && node.dataset.mentionName) {
      return `@${node.dataset.mentionName}`;
    }
    if (node instanceof HTMLElement && node.dataset.clueId) {
      return `[${node.dataset.clueId}]`;
    }
    if (node.nodeName === "BR") return "\n";
    if (node.nodeType === Node.TEXT_NODE) return node.textContent || "";
    return Array.from(node.childNodes).map(walk).join("");
  };
  const value = walk(root).replace(/\u00a0/g, " ").replace(/\u200b/g, "");
  const hasChip = Boolean(root.querySelector("[data-mention-name], [data-clue-id]"));
  return !hasChip && value.trim().length === 0 ? "" : value;
}

export const MentionComposer = forwardRef<MentionComposerHandle, MentionComposerProps>(
  function MentionComposer(
    { characters, clues, disabled, maxLength = 3000, onChange, onCtrlEnter, onEnter },
    forwardedRef,
  ) {
    const editorRef = useRef<HTMLDivElement>(null);
    const listboxRef = useRef<HTMLDivElement>(null);
    const savedRangeRef = useRef<Range | null>(null);
    const triggerRangeRef = useRef<Range | null>(null);
    const [trigger, setTrigger] = useState<Trigger>(null);
    const [activeIndex, setActiveIndex] = useState(0);

    const options = useMemo(() => {
      const needle = (trigger?.query || "").toLocaleLowerCase();
      if (trigger?.kind === "clue") {
        return clues
          .filter((item) =>
            `${item.summary} ${item.content} ${item.id}`.toLocaleLowerCase().includes(needle),
          )
          .map((clue) => ({ kind: "clue" as const, clue }));
      }
      if (trigger?.kind === "mention") {
        return characters
          .filter((item) => item.name.toLocaleLowerCase().includes(needle))
          .map((character) => ({ kind: "mention" as const, character }));
      }
      return [];
    }, [characters, clues, trigger]);

    useEffect(() => {
      if (!trigger || options.length === 0) return;
      const selected = listboxRef.current?.querySelector<HTMLElement>(
        '[role="option"][aria-selected="true"]',
      );
      selected?.scrollIntoView({ block: "nearest" });
    }, [activeIndex, options.length, trigger]);

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

    const closePicker = () => {
      triggerRangeRef.current = null;
      setTrigger(null);
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
        const mentionMatch = before.match(/@([^@\s]*)$/);
        const clueMatch = before.match(/\/([^/\s]*)$/);
        const match = mentionMatch || clueMatch;
        if (match) {
          const nextTrigger: Exclude<Trigger, null> = {
            kind: mentionMatch ? "mention" : "clue",
            query: match[1],
          };
          const triggerRange = range.cloneRange();
          triggerRange.setStart(range.startContainer, range.startOffset - match[0].length);
          triggerRangeRef.current = triggerRange;
          setTrigger((current) => {
            if (current?.kind !== nextTrigger.kind || current.query !== nextTrigger.query) {
              setActiveIndex(0);
            }
            return nextTrigger;
          });
          return;
        }
      }
      closePicker();
    };

    const insertionRange = (root: HTMLElement) => {
      const selection = window.getSelection();
      const range = triggerRangeRef.current || savedRangeRef.current || document.createRange();
      if (!root.contains(range.commonAncestorContainer)) {
        range.selectNodeContents(root);
        range.collapse(false);
      }
      range.deleteContents();
      return { range, selection };
    };

    const finishInsert = (range: Range, selection: Selection | null, chip: HTMLElement) => {
      range.insertNode(chip);
      const spacer = document.createTextNode(" ");
      chip.after(spacer);
      range.setStartAfter(spacer);
      range.collapse(true);
      selection?.removeAllRanges();
      selection?.addRange(range);
      savedRangeRef.current = range.cloneRange();
      closePicker();
      emit();
    };

    const insertMention = (character: Character) => {
      const root = editorRef.current;
      if (!root || disabled) return;
      root.focus();
      const { range, selection } = insertionRange(root);
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
      finishInsert(range, selection, chip);
    };

    const insertClue = (clue: PublicClue) => {
      const root = editorRef.current;
      if (!root || disabled) return;
      root.focus();
      const { range, selection } = insertionRange(root);
      const chip = document.createElement("span");
      chip.contentEditable = "false";
      chip.dataset.clueId = clue.id;
      chip.title = clue.content;
      chip.className = "inline-flex items-center gap-1 mx-0.5 px-1.5 py-0.5 rounded-full border border-amber-400/30 bg-amber-400/10 text-amber-200 align-middle select-all";
      chip.append(document.createTextNode(`⌕ ${clue.summary}`));
      finishInsert(range, selection, chip);
    };

    const chooseOption = (index: number) => {
      const option = options[index] || options[0];
      if (!option) return;
      if (option.kind === "mention") insertMention(option.character);
      else insertClue(option.clue);
    };

    useImperativeHandle(forwardedRef, () => ({
      focus: () => editorRef.current?.focus(),
      insertMention,
      clear: () => {
        if (editorRef.current) editorRef.current.replaceChildren();
        closePicker();
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
          data-placeholder="输入你的发言，输入 @ 可快捷选择角色，输入 / 可快捷选择线索…"
          onInput={() => { emit(); rememberCaretAndTrigger(); }}
          onKeyUp={(event) => {
            if (["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
            rememberCaretAndTrigger();
          }}
          onMouseUp={rememberCaretAndTrigger}
          onPaste={(event) => {
            event.preventDefault();
            document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
          }}
          onKeyDown={(event) => {
            if (trigger && options.length) {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const delta = event.key === "ArrowDown" ? 1 : -1;
                setActiveIndex((index) => (index + delta + options.length) % options.length);
                return;
              }
              if (event.key === "Enter" || event.key === "Tab") {
                event.preventDefault();
                chooseOption(activeIndex);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closePicker();
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
        {!disabled && trigger && options.length > 0 && (
          <div
            ref={listboxRef}
            role="listbox"
            aria-label={trigger.kind === "mention" ? "可引用角色" : "已公开线索"}
            className="absolute bottom-full left-0 z-50 mb-2 max-h-64 w-72 overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-xl scrollbar-thin"
          >
            {options.map((option, index) => option.kind === "mention" ? (
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                key={option.character.character_id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insertMention(option.character)}
                className={`w-full flex items-center gap-2 rounded-lg p-2 text-left text-sm ${index === activeIndex ? "bg-primary/15" : "hover:bg-secondary/60"}`}
              >
                <span className="w-7 h-7 rounded-full overflow-hidden bg-primary/20 flex items-center justify-center shrink-0">
                  {option.character.avatar_url ? <img src={option.character.avatar_url} alt="" className="w-full h-full object-cover" /> : option.character.name[0]}
                </span>
                <span>@{option.character.name}</span>
              </button>
            ) : (
              <button
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                key={option.clue.id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => insertClue(option.clue)}
                className={`w-full rounded-lg p-2 text-left ${index === activeIndex ? "bg-amber-400/10" : "hover:bg-secondary/60"}`}
              >
                <span className="flex items-center gap-1 text-[10px] text-amber-300/80">
                  <Search className="h-3 w-3" />第 {option.clue.stage} 轮公开线索
                </span>
                <span className="mt-0.5 block text-sm">{option.clue.summary}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  },
);
