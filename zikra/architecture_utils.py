"""Validation shared by architecture commands and scheduled generation."""

import os
import re

_PROJECT_RE = re.compile(r'[^a-z0-9]+')
_VALID_ENVIRONMENTS = ('dev', 'prod')


def canonical_project(value, default: str = 'global') -> str:
    """Return the canonical, URL-safe project identifier used by Zikra."""
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValueError('project must be a string')
    value = _PROJECT_RE.sub('-', value.strip().lower()).strip('-')
    if not value:
        raise ValueError('project must not be empty')
    if len(value) > 100:
        raise ValueError('project must be 100 characters or fewer')
    return value


def required_text(value, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{field} must be a string')
    value = value.strip()
    if not value:
        raise ValueError(f'{field} is required')
    if len(value) > max_length:
        raise ValueError(f'{field} must be {max_length} characters or fewer')
    return value


def optional_text(value, field: str, max_length: int):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'{field} must be a string or null')
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise ValueError(f'{field} must be {max_length} characters or fewer')
    return value


def environment(value, allow_all: bool = False):
    if value is None:
        return None
    allowed = _VALID_ENVIRONMENTS + (('all',) if allow_all else ())
    if value not in allowed:
        raise ValueError(f"environment must be one of {allowed} or null")
    return value


def absolute_repo_path(value) -> str:
    value = required_text(value, 'repo_path', 1000)
    normalized = os.path.normpath(value)
    if not os.path.isabs(normalized):
        raise ValueError('repo_path must be absolute')
    return normalized
