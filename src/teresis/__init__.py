"""teresis: local, zero-dependency long-term memory for agents."""

__version__ = "0.1.0"

from .store import Memory, MemoryStore, RememberResult, Weights, scope_chain  # noqa: E402

__all__ = ["Memory", "MemoryStore", "RememberResult", "Weights", "scope_chain", "__version__"]


def register(ctx) -> None:
    """Hermes directory-plugin entry point; normal Teresis imports stay standalone."""
    from .hermes import TeresisMemoryProvider

    ctx.register_memory_provider(TeresisMemoryProvider())
