from dataclasses import dataclass, field

from .store import Memory
from .text import estimate_tokens


@dataclass
class EvidencePacket:
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
        line = f'- [{label}] {memory.content} (id {memory.id}{ref})'
        header = '' if self._section == section else ('\n' if self.text else '') + '## ' + section + '\n'
        fragment = ('\n' if self.text else '') + header + line
        if estimate_tokens(self.text + fragment) > self.budget:
            return False
        self.text += fragment
        self.ids.add(memory.id)
        self._section = section
        return True
