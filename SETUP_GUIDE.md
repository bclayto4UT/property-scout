# 🏠 Property Scout — Setup Guide
*Get the web app live in ~15 minutes, free forever.*

---

## What you'll end up with

A private link like `https://yourname-property-scout.streamlit.app` that your wife
and mother can open on any phone or computer. It shows a filterable table and map
of every property your scraper has found, color-coded by investment tier.

---

## Step 1 — Create a GitHub repository

1. Go to **github.com** and sign in (or create a free account).
2. Click the **+** icon (top right) → **New repository**.
3. Name it `property-scout`.
4. Set it to **Private** ✅ (your data stays private).
5. Click **Create repository**.

---

## Step 2 — Add the app files

In your new repo, upload these files (drag & drop works):

| File | Where to get it |
|---|---|
| `app.py` | The file included with this guide |
| `requirements.txt` | The file included with this guide |
| `data/properties.db` | Your SQLite database from the scraper |

> **Tip:** To upload `data/properties.db`, create a folder called `data` first by
> clicking **Add file → Create new file**, typing `data/placeholder.txt`, and saving.
> Then you can drag your `.db` file into the `data/` folder.

---

## Step 3 — Deploy on Streamlit Community Cloud (free)

1. Go to **share.streamlit.io** and sign in with your GitHub account.
2. Click **New app**.
3. Fill in:
   - **Repository:** `yourname/property-scout`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Deploy!**

Streamlit will build the app (takes ~1 minute). You'll get a URL like:
`https://yourname-property-scout.streamlit.app`

---

## Step 4 — Share with family

Send the URL to your wife and mother. That's it — they just open the link.

To **restrict access** so only they can see it:
- In Streamlit Cloud, go to your app → **Settings → Sharing**
- Add their email addresses as viewers (they'll need a free Streamlit account)

---

## Step 5 — Updating data after each scraper run

When you run your scraper and get a new `properties.db`, just re-upload it to
GitHub:

1. In your repo, click on `data/properties.db`
2. Click the pencil/edit icon → **Upload a new version**
3. Drop in your new `.db` file and commit

The app will automatically reload within a minute. No action needed from your
wife or mother — the link stays the same forever.

---

## Troubleshooting

**"No data found" message on the app**
→ Make sure `data/properties.db` is in the repo and the scraper has been run at least once.

**App won't build**
→ Check that `requirements.txt` is in the root of the repo (not inside `data/`).

**Map shows no pins**
→ Your properties need latitude/longitude data. Check that your scraper's Redfin
results include the LATITUDE/LONGITUDE columns — they sometimes depend on the
region type used in `config.py`.

---

## Optional: Custom subdomain name

In Streamlit Cloud → your app → Settings, you can change the URL from the
auto-generated one to something like `property-scout-smith.streamlit.app`.
