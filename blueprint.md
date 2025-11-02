# Pretix Project Blueprint

## Overview

Pretix is an open-source ticketing platform. The goal is to maintain and enhance its functionality based on user requests, ensuring stability and robustness, and making it ready for deployment.

## Existing Style, Design, and Features

*   **Initial State:** This is a large, existing Django project named "pretix".
*   **Dependency Management:** `pyproject.toml` is used for managing dependencies.

## Completed Tasks

*   **Fixed `ModuleNotFoundError: No module named 'corsheaders'`**:
    *   Added `django-cors-headers` to the `dependencies` list in `pyproject.toml`.

## Current Task: Fix `ImproperlyConfigured: 'django.db.backends.sqlite'`

### Plan Overview

The application is failing during the Docker build process (`python src/manage.py migrate`) because the Django database backend is incorrectly configured as `django.db.backends.sqlite` instead of the correct `django.db.backends.sqlite3`. The plan is to locate the source of this misconfiguration and correct it.

### Actionable Steps

1.  **Investigate Configuration:** Systematically check the configuration files to find where the `database.backend` is being set to the incorrect value `sqlite`.
    *   Re-read `pretix.cfg` to confirm its content.
    *   Analyze `src/pretix/settings.py` to understand how the configuration is loaded and if it's being overridden.
    *   Examine `Dockerfile` for any relevant environment variables.
2.  **Correct Configuration:** Once the source of the error is found, update the configuration from `sqlite` to `sqlite3`.
