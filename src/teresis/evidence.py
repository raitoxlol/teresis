from dataclasses import dataclass, field

from . import temporal as _temporal
from .store import Memory
from .text import estimate_tokens

ITEM_CHARS = 1200  # per memory in the injected block, so one legacy row cannot crowd out the rest


def _trim(text: str, n: int) -> str:
    text = (text or '').strip()
    return text if len(text) <= n else text[: n - 1] + '…'


def render_content(memory: Memory) -> str:
    """The text injected for one memory: trimmed, plus the day it was saved when it says
    "tomorrow" or "next week" (detected on the full content, so a trimmed phrase still counts)."""
    return _temporal.with_saved_note(memory.content, memory.created_at,
                                     display_content=_trim(memory.content, ITEM_CHARS))


@dataclass
class EvidencePacket:
    """At most ``limit`` memories in at most ``budget`` estimated tokens of rendered text.

    ``text`` may start with a lead block (the Hermes review note); the budget covers it too.
    """
    limit: int
    budget: int
    text: str = ''
    ids: set[str] = field(default_factory=set)
    _section: str = ''

    @property
    def full(self) -> bool:
        return len(self.ids) >= self.limit or self.budget <= 0

    def add(self, memory: Memory, section: str, *, via: str = '') -> bool:
        if self.full or memory.id in self.ids:
            return False
        label = memory.kind + (f' {memory.key}' if memory.key else '')
        ref = f'; linked from {via}' if via else ''
        # The budget check below covers the whole rendered line: header, saved-date note and citation.
        line = f'- [{label}] {render_content(memory)} (id {memory.id}{ref})'
        header = '' if self._section == section else ('\n' if self.text else '') + '## ' + section + '\n'
        fragment = ('\n' if self.text else '') + header + line
        if estimate_tokens(self.text + fragment) > self.budget:
            return False
        self.text += fragment
        self.ids.add(memory.id)
        self._section = section
        return True
