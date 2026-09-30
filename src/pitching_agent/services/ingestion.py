"""Live ingestion loop: poll primary source, persist raw snapshots, normalize, emit events.

Never calls the LLM. User observations never block this loop.
"""
