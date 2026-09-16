# Cattaraugus County Sales Explorer (Streamlit)

A Streamlit port of the Cattaraugus County Sales Explorer, with the same filtering and
interactive controls as the original R Shiny app and the Jupyter/ipywidgets version.

## Files

- `app.py` — the app itself
- `requirements.txt` — Python dependencies
- `cattco_sales_arms_length_Y_with_2026usd.csv` — the data file the app reads

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

It opens automatically in your browser (usually at `http://localhost:8501`). The app looks
for the CSV in the same folder as `app.py` by default; to point it somewhere else, set the
`CATTCO_DATA_PATH` environment variable to the file's full path before running.

## Deploy to Streamlit Community Cloud (free)

1. **Create a GitHub repo** and push these three files to it (a public repo is required for
   the free tier). Keep the CSV filename exactly as it is, or update `DATA_PATH` in `app.py`
   if you rename it.
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
3. Click **"New app"**, then select your repo, the branch, and `app.py` as the main file
   path.
4. Click **"Deploy"**. The first build takes a few minutes while it installs the
   dependencies; after that, the app is live at a `<your-app-name>.streamlit.app` URL you
   can share with anyone.
5. **Updating the app later**: just push new commits to the repo (a data refresh, a code
   change, etc.) — Streamlit Community Cloud automatically redeploys from the latest commit
   on your chosen branch.

### A couple of things worth knowing

- **Cold starts**: an app with no recent visitors goes to sleep; the next visitor sees a
  short "waking up" delay (usually under a minute) before it's live again. This is normal
  for the free tier.
- **Public repo = public code and data**: anyone can view the source and the CSV in the
  GitHub repo, not just the deployed app. That's fine here since this is public county
  sale-record data, but keep it in mind if you ever reuse this pattern for non-public data.
- **Resource limits**: the free tier is meant for light-to-moderate traffic. If this ends up
  getting heavy public use, Streamlit's paid tiers (or a self-hosted deployment) offer more
  headroom.

## Other hosting options

Since this is a plain Streamlit app, it isn't locked to Streamlit Community Cloud — the same
three files can be deployed with a `Dockerfile` (`CMD streamlit run app.py --server.port=$PORT
--server.address=0.0.0.0`) to Render, Railway, Fly.io, a cloud VM, or similar.
