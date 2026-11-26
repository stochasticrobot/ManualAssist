"""Keep long-running analysis from occupying the browser's request handler.

This file provides one background worker for manual processing and a shared lock
for question answering. They let the server coordinate those activities without
creating a separate set of workers for every browser request."""

from concurrent.futures import ThreadPoolExecutor
import threading

WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="manual-worker")
ANSWER_LOCK = threading.Lock()
