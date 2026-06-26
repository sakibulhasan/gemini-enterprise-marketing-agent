"""
conftest.py
===========

Pytest configuration for the data-generation test suite.

The pipeline modules import each other as *siblings* (``import config``,
``import gcp_utils``), so the ``data_generation`` directory must be importable.
Inserting it onto ``sys.path`` lets the tests ``import contractors_pipeline`` etc.
exactly the way the pipelines import each other at runtime.

The tests only exercise the PURE data-generation functions (``generate`` /
``build_recommendation`` / ``_target_months``). Those functions perform no GCP
calls — the BigQuery / Cloud Storage clients in ``gcp_utils`` are created lazily —
so the suite runs offline without any credentials.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
