from typing import Dict, Optional, Set

# Github only accepts assignees from valid users. We map those users from bitbucket.
USER_MAPPING: Dict[str, str] = {}

# We map bitbucket's issue "kind" to github "labels".
KIND_MAPPING: Dict[str, str] = {
    "bug": "bug",
    "enhancement": "enhancement",
    "proposal": "proposal",
    "task": "task",
}

# We map bitbucket's issue "priority" to github "labels".
PRIORITY_MAPPING: Dict[str, str] = {
    "trivial": "trivial",
    "minor": "minor",
    "major": "major",
    "critical": "critical",
    "blocker": "blocker",
}

# We map bitbucket's issue "component" to github "labels".
COMPONENT_MAPPING: Dict[str, str] = {}

# The only github states are "open" and "closed".
# Therefore, we map some bitbucket states to github "labels".
STATE_MAPPING: Dict[str, Optional[str]] = {
    "on hold": "on hold",
    "invalid": "invalid",
    "duplicate": "duplicate",
    "wontfix": "wontfix",
    "resolved": None,
    "new": None,
    "open": None,
    "closed": None,
    "DECLINED": "declined",
    "MERGED": "merged",
    "SUPERSEDED": "superseeded",
    "OPEN": None,
}

# Bitbucket has several issue and pull request states.
# All states that are not listed in this set will be closed.
OPEN_ISSUE_OR_PULL_REQUEST_STATES: Set[str] = {
    "open",
    "new",
    "on hold",
    "OPEN",
}

# Mapping of known Bitbucket to their corresponding GitHub repo
# This information is used to convert links
KNOWN_REPO_MAPPING: Dict[str, str] = {}
