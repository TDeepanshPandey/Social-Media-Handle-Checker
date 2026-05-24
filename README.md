# Social Media Handle Checker

A Flask web app that checks one or more social usernames, generates social username ideas from a short description, or does both on Instagram, YouTube, and TikTok.

The app uses HTTP profile probes rather than private platform APIs. That keeps it deployable without API keys, but platforms may rate-limit or block automated requests. Those cases are shown as `unknown` so users can verify manually.

Description-based suggestions are enriched with the free Datamuse word-finding API and fall back to local keyword combinations if Datamuse is unavailable. Datamuse can be disabled with `USE_DATAMUSE=false`.

## Features

- Username-only availability checks, including comma-separated lists
- Optional description-based username generation
- User-selectable suggestion counts: 10, 15, 20, 25, 30, or 50
- Datamuse-assisted related-word suggestions with local fallback
- Instagram, YouTube, and TikTok platform checkboxes
- Clickable platform profile URLs in the availability snapshot
- Server-side validation for required fields, username characters, and platform-specific formats
- Clear result states: `available`, `taken`, `invalid`, and `unknown`
- Render free-tier deployment config

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

On Windows (PowerShell), use:

```powershell
.venv\Scripts\Activate.ps1
```

Open `http://localhost:5000`.

## Test

```bash
pip install pytest
pytest
```

## Deploy Free on Render

1. Push this repository to GitHub.
2. Create a free Render account.
3. Choose **New > Blueprint** and connect this repository.
4. Render reads `render.yaml`, installs `requirements.txt`, and starts the app with `gunicorn app:app`.

Free Render web services can spin down after inactivity, so the first request after a quiet period may be slower.

Live app: https://social-media-handle-checker.onrender.com/

## API Acknowledgment

Username suggestions use the Datamuse API: https://www.datamuse.com/api/
