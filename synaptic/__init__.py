"""synaptic: a SynapCores-backed intelligence and memory layer for BitCracker V2.

BitCracker V2 is fast at checking passwords (a CUDA kernel does ~11M/s). But on a
real personal recovery the hard part isn't speed, it's deciding which candidates
are worth checking and not re-checking a keyspace you already swept.

synaptic puts that decision layer in SynapCores Community Edition, an AI-native
database with SQL, vector search, a property graph, in-database AutoML, and an
embedded LLM behind one REST gateway:

- graph   a knowledge graph of the owner's memory hints; GraphRAG assembles
          ordered candidate tokens from it.
- llm     free-text memory ("my dog's name and the year") into structured hints
          (optional; falls back to plain parsing if the model is cold).
- automl  an in-database "password-like" classifier ranks candidates so the
          search tries the plausible ones first.
- vector  candidate embeddings dedup against what was already tried.
- sql     a run ledger records which wallet and how much keyspace was swept,
          never the recovered password.

It runs against a local SynapCores instance and only ever touches wallets the
operator owns. This is self-recovery tooling, the same category as the btcrecover
fork it builds on.
"""

__version__ = "0.1.0"

from .client import SynapCoresClient, SynapCoresError
from .config import Settings

__all__ = ["Settings", "SynapCoresClient", "SynapCoresError", "__version__"]
