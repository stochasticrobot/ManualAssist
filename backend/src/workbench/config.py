"""Locate the project folder and browser files relative to the installed Python code.

The server needs these locations to serve the application and find project files
regardless of the directory from which it was started. This file defines paths; it
does not load credentials or create an analysis."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
