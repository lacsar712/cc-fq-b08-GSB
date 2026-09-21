"""Pytest bootstrap: point the app at a throwaway sqlite file before any app import."""

import os
import tempfile

_fd, _db_path = tempfile.mkstemp(prefix="fastq_qc_test_", suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
