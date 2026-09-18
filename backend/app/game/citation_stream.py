"""Bounded incremental citation filtering without buffering normal speech."""

import re

from app.game.clues import CLUE_ID_SOURCE, parse_clue_citations


class CitationStreamFilter:
    MAX_PENDING = 4096

    def __init__(self, clues):
        self.clues = list(clues)
        self.pending = ""
        self.previous = ""
        self.fence = ""
        self.line_start = True
        self.indented = False

    @staticmethod
    def _possible_id(word):
        word = word.lower()
        return (
            "clue-".startswith(word)
            or re.fullmatch(r"c[0-9]{0,4}", word) is not None
            or re.fullmatch(r"clue-[a-z0-9]{0,12}", word) is not None
        )

    def _end(self, text, final):
        if text.startswith("\\"):
            return 2 if len(text) >= 2 else (1 if final else None)
        if text.startswith("`"):
            marker = re.match(r"`+", text)[0]
            close = text.find(marker, len(marker))
            if close >= 0:
                return close + len(marker)
            if not final and len(text) < self.MAX_PENDING:
                return None
            if not final:
                self.fence = marker
            return len(text)
        prefix = re.match(r"`*\\?", text).end()
        body = text[prefix:]
        wait = not final and len(text) < self.MAX_PENDING
        if not body:
            return None if wait else len(text)
        if body.startswith("["):
            from app.game.citation_syntax import ID, bracket_end

            end = bracket_end(text, prefix)
            if end is None:
                return None if wait else 1
            if end == len(text) and wait:
                return None
            if text[end : end + 1] == "[" and not ID.fullmatch(text[prefix + 1 : end - 1]):
                group_end = bracket_end(text, end)
                if group_end is None:
                    return None if wait else end
                end = group_end
            link_start = end + (1 if text[end : end + 1] == "\\" else 0)
            if link_start == len(text) and wait:
                return None
            if text[link_start : link_start + 1] == "(":
                close_link = text.find(")", link_start + 1)
                if close_link < 0:
                    return None if wait else end
                end = close_link + 1
            while text[end : end + 1] == "`":
                end += 1
            if end == len(text) and wait:
                return None
            return end
        if body[0].lower() == "c":
            word = re.match(r"[\w-]+", body).group()
            if len(word) == len(body) and wait and self._possible_id(word):
                return None
            if re.fullmatch(CLUE_ID_SOURCE, word, re.IGNORECASE):
                end = prefix + len(word)
                while text[end : end + 1] == "`":
                    end += 1
                if end == len(text) and wait:
                    return None
                return end
        return max(1, prefix)

    def feed(self, text, *, final=False):
        self.pending += text
        data = self.pending
        result = []
        cursor = 0
        while cursor < len(data):
            if self.line_start and not self.fence:
                rest = data[cursor:]
                if rest.startswith("\t") or rest.startswith("    "):
                    self.indented = True
                elif not final and rest.strip(" ") == "" and len(rest) < 4:
                    break
                self.line_start = False
            if self.indented:
                newline = data.find("\n", cursor)
                end = len(data) if newline < 0 else newline + 1
                result.append(data[cursor:end])
                cursor = end
                if newline >= 0:
                    self.indented = False
                    self.line_start = True
                continue
            if self.fence:
                end = data.find(self.fence, cursor)
                if end >= 0:
                    end += len(self.fence)
                    result.append(data[cursor:end])
                    cursor = end
                    self.fence = ""
                    continue
                safe_end = len(data) if final else max(cursor, len(data) - len(self.fence) + 1)
                result.append(data[cursor:safe_end])
                cursor = safe_end
                break
            if data[cursor] in "`~":
                marker = re.match(r"[`~]+", data[cursor:])[0]
                if cursor + len(marker) == len(data) and not final:
                    break
                if len(marker) >= 3 and len(set(marker)) == 1:
                    self.fence = marker
                    result.append(marker)
                    cursor += len(marker)
                    continue
            char = data[cursor]
            previous = data[cursor - 1] if cursor else self.previous
            candidate = char in "[`\\" or (
                char.lower() == "c"
                and not (previous.isalnum() or (previous and previous in "_#/[\\-"))
            )
            if candidate:
                size = self._end(data[cursor:], final)
                if size is None:
                    break
                segment = data[cursor : cursor + size]
                # Sentinels preserve exact spacing between streamed pieces.
                cleaned, _, _ = parse_clue_citations(
                    "§" + segment + "§", self.clues, strip_unknown=True
                )
                result.append(cleaned[1:-1])
                cursor += size
            else:
                result.append(char)
                cursor += 1
                if char == "\n":
                    self.line_start = True
        if cursor:
            self.previous = data[cursor - 1]
        self.pending = data[cursor:]
        return "".join(result)

    def finish(self):
        return self.feed("", final=True)
