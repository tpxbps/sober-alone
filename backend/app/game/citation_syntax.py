"""Small source tokenizer shared in behavior with frontend clueReferences.ts.

Keep source ranges: Markdown is still rendered by Markdown, never by this lexer.
"""

import re
from dataclasses import dataclass

ID_SOURCE = r"(?:c[0-9]{2,4}|clue-[a-z0-9]{12})"
ID = re.compile(rf"^{ID_SOURCE}$", re.I)
SEPARATORS = re.compile(r"[,，、;；\s]+")
BARE = re.compile(rf"(?<![\w\[#/-])({ID_SOURCE})(?![\w\]-])", re.I)
LINK = re.compile(r"\((?:\\.|[^)\n])*\)")


@dataclass
class Token:
    raw: str
    ids: list[str] | None = None
    label: str | None = None
    protected: bool = False
    bare: bool = False


def ids_in(value: str) -> list[str] | None:
    parts = [part.lower() for part in SEPARATORS.split(value.strip()) if part]
    return list(dict.fromkeys(parts)) if parts and all(ID.fullmatch(p) for p in parts) else None


def bracket_end(text: str, start: int) -> int | None:
    cursor = start + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == "]":
            return cursor + 1
        if text[cursor] == "[":
            return None
        cursor += 1
    return None


def tokenize(content: str) -> list[Token]:
    result: list[Token] = []
    cursor = 0
    plain = ""

    def flush():
        nonlocal plain
        if plain:
            # Legacy naked IDs are repaired only in ordinary prose.
            offset = 0
            for match in BARE.finditer(plain):
                result.append(Token(plain[offset : match.start()]))
                result.append(Token(match[0], [match[1].lower()], bare=True))
                offset = match.end()
            result.append(Token(plain[offset:]))
            plain = ""

    while cursor < len(content):
        rest = content[cursor:]
        if (cursor == 0 or content[cursor - 1] == "\n") and re.match(r"(?: {4}|\t)", rest):
            flush()
            end = content.find("\n", cursor)
            end = len(content) if end < 0 else end + 1
            result.append(Token(content[cursor:end], protected=True))
            cursor = end
            continue
        if rest.startswith("\\") and len(rest) > 1:
            flush()
            result.append(Token(rest[:2], protected=True))
            cursor += 2
            continue
        fence = re.match(r"(`{3,}|~{3,})", rest)
        if fence:
            flush()
            marker = fence[0]
            end = content.find(marker, cursor + len(marker))
            end = len(content) if end < 0 else end + len(marker)
            result.append(Token(content[cursor:end], protected=True))
            cursor = end
            continue
        if rest.startswith("`"):
            marker = re.match(r"`+", rest)[0]
            end = content.find(marker, cursor + len(marker))
            if end >= 0:
                flush()
                inside = content[cursor + len(marker) : end].strip()
                old = re.fullmatch(rf"\[({ID_SOURCE})\]", inside, re.I)
                result.append(
                    Token(
                        content[cursor : end + len(marker)],
                        [old[1].lower()] if old else None,
                        protected=not bool(old),
                    )
                )
                cursor = end + len(marker)
                continue
            flush()
            result.append(Token(rest, protected=True))
            break
        if rest.startswith("["):
            end = bracket_end(content, cursor)
            if end:
                label = content[cursor + 1 : end - 1]
                link = LINK.match(content, end)
                if link:
                    flush()
                    legacy = re.fullmatch(rf"\(\s*#clue-ref-({ID_SOURCE})\s*\)", link[0], re.I)
                    result.append(
                        Token(
                            content[cursor : link.end()],
                            [legacy[1].lower()] if legacy else None,
                            protected=not bool(legacy),
                        )
                    )
                    cursor = link.end()
                    continue
                if content[end : end + 1] == "[" and not ids_in(label):
                    group_end = bracket_end(content, end)
                    ids = ids_in(content[end + 1 : group_end - 1]) if group_end else None
                    if ids and label.strip():
                        flush()
                        result.append(Token(content[cursor:group_end], ids, label))
                        cursor = group_end
                        continue
                direct_ids = ids_in(label)
                if direct_ids:
                    flush()
                    result.append(Token(content[cursor:end], direct_ids))
                    cursor = end
                    continue
                # Unknown bracketed prose is opaque to naked-ID repair.
                flush()
                result.append(Token(content[cursor:end], protected=True))
                cursor = end
                continue
            # Never repair a partially typed marker.
            flush()
            result.append(Token(rest, protected=True))
            break
        plain += content[cursor]
        cursor += 1
    flush()
    return result


def normalize(content: str, allowed_ids, *, strip_unknown: bool):
    allowed = set(allowed_ids)
    tokens = tokenize(content)
    explicit = {i for t in tokens if t.ids and not t.bare for i in t.ids if i in allowed}
    refs, unknown, output = [], [], []
    for token in tokens:
        if not token.ids:
            output.append(token.raw)
            continue
        invalid = [i for i in token.ids if i not in allowed]
        unknown.extend(i for i in invalid if i not in unknown)
        if invalid and not strip_unknown:
            output.append(token.raw)
            continue
        ids = [i for i in token.ids if i in allowed]
        if token.bare and ids and ids[0] in explicit:
            continue
        refs.extend(i for i in ids if i not in refs)
        if token.label is not None:
            output.append(f"[{token.label}][{','.join(ids)}]" if ids else token.label)
        elif ids:
            output.append("".join(f"[{id}]" for id in ids))
        elif "#clue-ref-" in token.raw:
            output.append(token.raw[1 : token.raw.index("]")])
    text = "".join(output)
    # Leading indentation can be Markdown code, so preserve it.
    text = text.rstrip() if text.startswith(("    ", "\t")) else text.strip()
    return text, refs, unknown


def speech_text(content: str, clues, allowed_ids) -> str:
    names = {item["id"].lower(): item["summary"] for item in clues}
    allowed = set(allowed_ids)
    parts = []
    for token in tokenize(content):
        if token.ids:
            if token.label is not None:
                parts.append(re.sub(r"\\([\[\]\\])", r"\1", token.label))
            else:
                parts.extend(names[i] for i in token.ids if i in allowed and i in names)
        else:
            parts.append(token.raw)
    return "".join(parts)
