# Invoice Extractor

Upload an invoice (PDF, DOCX, DOC, TXT, PNG, JPG) and get structured JSON back — vendor details, line items, taxes, totals, and validation.

## Local development

```bash
uv sync --all-extras
uv run python tests/fixtures/make_fixtures.py
uv run pytest -m "not integration"
```

Run the UI:

```bash
# Set APP_ENV=local to bypass the password gate
APP_ENV=local uv run streamlit run app.py
```

Or with a password:

```bash
APP_PASSWORD=mysecret uv run streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.

2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.

3. Fill in:
   - **Repository**: your GitHub repo
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - Under **Advanced settings**, set Python version to **3.11**.

4. In the app's **Settings > Secrets**, paste your secrets (same keys as `.streamlit/secrets.toml.example`):

   ```toml
   LLM_PROVIDER = "gemini"
   LLM_API_KEY = "your-real-api-key"
   LLM_MODEL = "gemini-3-flash-preview"
   PROMPT_VERSION = "v1"
   APP_PASSWORD = "choose-a-strong-password"
   ```

5. Click **Deploy**. The platform reads `packages.txt` to install system packages (`libmagic1`, `libreoffice-writer-nogui`) and `pyproject.toml` + `uv.lock` for Python dependencies.

6. Share the app URL. Users must enter the `APP_PASSWORD` to access it.

## Tests

```bash
uv run pytest -m "not integration"        # unit tests (no network)
uv run pytest -m integration              # real LLM (needs LLM_API_KEY)
make test-docker                           # run in Docker with LibreOffice
```
