"""synaptic - a SynapCores-backed intelligence and memory layer for BitCracker V2.

BitCracker V2 is fast at *checking* passwords (a CUDA kernel does ~11M/s). The
hard part of a real personal recovery is not raw speed - it is deciding *which*
candidates are worth checking and not re-checking a keyspace you already swept.

``synaptic`` puts that decision layer in SynapCores Community Edition, an
AI-native database that unifies SQL, vector search, a property graph, in-database
AutoML, and an embedded LLM behind one REST gateway:

* graph    - a knowledge graph of the wallet owner's own memory hints; GraphRAG
             assembles ordered candidate tokens from it.
* llm      - free-text memory ("my dog's name and the year") -> structured hints
             (optional; degrades to deterministic parsing if the model is cold).
* automl   - an in-database "password-like" classifier ranks candidates so the
             search tries the plausible ones first.
* vector   - candidate embeddings deduplicate against what was already tried.
* sql      - a run ledger records which wallet and how much keyspace was swept
             (never the recovered password itself).

Everything runs against a *local* SynapCores instance. The tooling only ever
operates on wallets the operator owns; it is self-recovery infrastructure, the
same category as the underlying btcrecover fork.
"""

__version__ = "0.1.0"

from .client import SynapCoresClient, SynapCoresError
from .config import Settings

__all__ = ["Settings", "SynapCoresClient", "SynapCoresError", "__version__"]
