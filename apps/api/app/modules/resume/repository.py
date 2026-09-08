"""Queries for the resume module.

Hides every Mongo detail, including index choices. A repository method never
contains a business rule: "active jobs for a user" belongs here, "should this
user see this job" belongs in `service.py`.
"""

from __future__ import annotations
