# Pretix Project Blueprint

## Overview

Pretix is an open-source ticketing platform. The goal is to maintain and enhance its functionality based on user requests, ensuring stability and robustness.

## Existing Style, Design, and Features

*   **Initial State:** This is a large, existing Django project named "pretix". The full feature set is being determined through code analysis.
*   **Dependencies:** `django-cors-headers` has been added to `pyproject.toml`.

## Current Task: Fix `ImproperlyConfigured` Database Backend

### Plan Overview

The application is failing during the `migrate` command because the Django database `ENGINE` setting is incorrect. It's set to `django.db.backends.sqlite`, but it should be `django.db.backends.sqlite3`. The plan is to find the configuration file where this is set and correct the typo.

### Actionable Steps

1.  **Locate Configuration:** Inspect the project's settings files (`pretix.cfg`, `src/pretix/settings.py`, `src/pretix/_base_settings.py`, `deployment/docker/production_settings.py`) to find the `DATABASES` setting.
2.  **Correct Setting:** Change the `ENGINE` value from `django.db.backends.sqlite` to `django.db.backends.sqlite3`.
3.  **Notify User:** Inform the user that the configuration has been fixed and they should be able to proceed.