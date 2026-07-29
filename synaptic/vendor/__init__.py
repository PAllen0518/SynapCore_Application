"""Vendored, self-contained dependencies for synaptic.

``multibit_check.py`` is a point-in-time copy of the standalone Python 3
MultiBit Classic checker from the BitCracker V2 project (© 2026 Paul Allen,
GPLv2). ``test-wallets/multibit-wallet.key`` is btcrecover's public test
fixture (documented password ``btcr-test-password``, holds no funds).

They are vendored so synaptic runs, tests, and demos without a BitCracker
checkout. If the upstream checker changes materially, refresh this copy.
"""
