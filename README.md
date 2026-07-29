# SynapCores application — `synaptic`

Application deliverable for SynapCores' **Founding GTM Engineer / Solutions
Architect** role: build something with SynapCores CE and show it.

**`synaptic/`** is a SynapCores-backed intelligence + memory layer that sits on
top of a MultiBit wallet password-recovery checker. A knowledge graph of the
owner's memory hints generates candidate tokenlists (GraphRAG), in-database
AutoML ranks candidates by likelihood, a SQL/vector ledger stops re-sweeping
keyspace already tried, and the whole loop is exposed over MCP. It exercises
every SynapCores surface — SQL, vector, graph, AutoML, embedded LLM, MCP — and
runs end-to-end against a public, zero-funds test wallet.

Full documentation, architecture, and quickstart: **[synaptic/README.md](synaptic/README.md)**.

```bash
pip install -e "synaptic[dev]"
python -m pytest synaptic/tests/          # DB-free unit tests
python -m synaptic.demo                    # end-to-end (needs a local SynapCores CE)
```

Self-contained: the MultiBit checker and public test wallet are vendored under
`synaptic/vendor/`, so this repo installs, tests, and demos without any other
checkout. See `synaptic/README.md` for how to run SynapCores CE locally.
