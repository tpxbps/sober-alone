"""Bounded incremental citation filtering without buffering normal speech."""

import re

from app.game.clues import CLUE_ID_SOURCE, parse_clue_citations


class CitationStreamFilter:
    MAX_PENDING = 256

    def __init__(self, clues):
        self.clues = list(clues)
        self.pending = ""
        self.previous = ""

    @staticmethod
    def _possible_id(word):
        word = word.lower()
        return (
            "clue-".startswith(word)
            or re.fullmatch(r"c[0-9]{0,4}", word) is not None
            or re.fullmatch(r"clue-[a-z0-9]{0,12}", word) is not None
        )

    def _end(self, text, final):
        prefix = re.match(r"`*\\?", text).end()
        body = text[prefix:]
        wait = not final and len(text) < self.MAX_PENDING
        if not body:
            return None if wait else len(text)
        if body.startswith("["):
            closing = text.find("]", prefix + 1)
            if closing < 0:
                return None if wait else 1
            end = closing + 1
            if end == len(text) and wait:
                return None
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
            char = data[cursor]
            previous = data[cursor - 1] if cursor else self.previous
            candidate = char in "[`\\" or (
                char.lower() == "c"
                and not (previous.isalnum() or (previous and previous in "_#/-"))
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
        if cursor:
            self.previous = data[cursor - 1]
        self.pending = data[cursor:]
        return "".join(result)

    def finish(self):
        return self.feed("", final=True)
