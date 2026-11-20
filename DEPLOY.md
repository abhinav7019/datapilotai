# DataPilot AI: accounts, MySQL, file storage and hosting

## What was added

| Phase | What you get | Where |
|---|---|---|
| 1 Authentication | Register, log in, log out, change password, delete account. Passwords are hashed with PBKDF2-SHA256 (200,000 rounds, random salt). 5 wrong passwords lock the account for 15 minutes. Every query is filtered by the signed-in user's id. | `app.py` (screens), `datapilot_db.py` |
| 2 MySQL | The same helper functions run on SQLite (default) or MySQL. Projects, chat, settings, analysis history and reports work as before. | `datapilot_db.py`, `migrate_sqlite_to_mysql.py` |
| 3 File storage | Cleaned datasets, **original uploaded files** and reports are stored per user, with path/ownership checks, atomic writes and SHA-256 checks. Disk or inside the database. | `datapilot_db.py`, Projects tab |
| 4 Testing + hosting | 100 automated tests, Dockerfile, docker-compose, Streamlit config, this guide. | `tests/`, `Dockerfile`, `docker-compose.yml` |

The old PBI Kit tab is **not** in this version.

## New: look and Analyst Toolkit

**Look.** Sidebar > Theme & background > *Look*:

* **Flex** (new default, inspired by a designer-portfolio site): charcoal / cream palette, big bold type, pill buttons, text-style tabs.
  - *Home page* (shown until you load data): "Hi, I'm DataPilot. I am a [Data Analyst]" on a spiral notepad that rotates its role, a floating 3D dashboard stack, and **four 3D doors** (Insights, Toolkit, Dashboard, Ask AI). Hover a door and it swings open; click it and you walk into that tab. Before data is loaded a click takes you to the "add data" step.
  - *Pull-cord* at the top: pull it (or use the **Dark mode** switch) to flip between dark charcoal and light cream.
  - Top bar with Home / Insights / Toolkit / Dashboard / Ask AI / Projects links and a live clock and date.
  - After you load data the home page shrinks to a slim "Hi, <name>" header with a data-quality chip.
* **Modern**: flat glass cards, soft shadows, pill tabs, spinning 3D cube banner.
* **3D classic**: your original raised look.

**3D background and effects** (all looks): *3D background* = Neural network, Galaxy, Floating shapes or Off. *Interactive effects* = cards tilt toward the mouse, a soft light follows the cursor, numbers count up, a thin bar shows scroll progress. It is drawn on a canvas in the browser (no downloads), pauses when the tab is hidden, uses fewer particles on phones and respects the "reduce motion" setting. Fonts (Plus Jakarta Sans) come from Google Fonts; offline the page falls back to a system font. *Save as my default theme* remembers everything.

**🧰 Analyst Toolkit tab** (logic in `datapilot_tools.py`, needs `scipy`):

| Tool | What it does |
|---|---|
| 🩺 Data quality | Score out of 100, empty cells, duplicates, outliers, numbers stored as text, constant columns, per-column table |
| 🧼 Clean & transform | No-code recipe: remove duplicates, drop/rename columns, fill empty cells, change types, clean text, filter rows, remove outliers, calculated columns (safe formulas), bins, date parts. Undo/clear, download cleaned CSV. Every tab updates instantly. |
| 📐 Pivot table | Rows, columns, values, sum/mean/median/count/max/min, totals, heatmap, CSV |
| 🧪 Statistical tests | t-test (Welch / paired), Mann-Whitney, ANOVA, Chi-square, correlation (Pearson/Spearman/Kendall), normality, A/B test + sample-size planner, each with a plain-English result |
| 📉 Regression | Multiple linear regression with p-values, R², error charts, "predict a new case" form |
| 🧬 Segments | K-means clustering, best-k finder, segment profiles, labelled CSV |
| 🚨 Outliers | IQR or Z-score, chart, outlier rows, one-click removal step |
| 🧾 SQL | Read-only SQL on your data (table `data`), results, chart, CSV |

Notes: the cleaning recipe belongs to the data currently loaded and resets when you load different data. SQL runs on a private in-memory copy: only SELECT is allowed and a query is stopped after 5 seconds.

## Run locally (SQLite, nothing else to install)

```
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address localhost
```

### Your existing data
If `datapilot.db` from the old (no-login) version is next to `app.py`, the app upgrades it automatically. The **first account you create takes over that old data** (shown on the Create account tab). Then every later account starts empty.
On a public server set `DATAPILOT_CLAIM_LEGACY=0`, or claim your data before you publish.

## Use MySQL

1. Create an empty database and a user (MySQL 8 / MariaDB 10.5+):
```sql
CREATE DATABASE datapilot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'datapilot'@'%' IDENTIFIED BY 'a-long-random-password';
GRANT ALL PRIVILEGES ON datapilot.* TO 'datapilot'@'%';
```
2. Set the variables from `.env.example` (`DATAPILOT_DB=mysql`, `MYSQL_*`). Tables are created on first start.
3. Move your old data (optional, keeps ids, passwords and projects):
```
python migrate_sqlite_to_mysql.py --sqlite datapilot.db
```
The SQLite file is only read. Keep a backup anyway. With `DATAPILOT_STORAGE=disk` keep using the same `datapilot_storage/` folder; with `DATAPILOT_STORAGE=db` the files are copied into MySQL (add `--storage path/to/datapilot_storage`).
If MySQL asks for a larger packet for big files, set `max_allowed_packet=128M`.

## File storage modes

* `DATAPILOT_STORAGE=disk` (default): files in `datapilot_storage/` under `DATAPILOT_HOME`. Put that folder on a persistent volume when hosting.
* `DATAPILOT_STORAGE=db`: file bytes live in the `file_store` table. Use this when the host wipes the disk on restart (Streamlit Community Cloud, many free tiers). One database backup then covers everything.

## Hosting

**Docker (any VPS):**
```
echo "MYSQL_PASSWORD=change-me" >> .env && echo "MYSQL_ROOT_PASSWORD=change-me-too" >> .env
docker compose up -d --build        # app on http://localhost:8501
```
Put an HTTPS reverse proxy (Caddy, Nginx, Cloudflare Tunnel) in front before exposing it. Logins are sent in the clear without HTTPS.

**Streamlit Community Cloud:** use an external MySQL (a hosted MySQL such as Aiven or Railway, or your own server). Paste `.streamlit/secrets.toml.example` into *App settings > Secrets* with `DATAPILOT_STORAGE = "db"`.

**Plain server:** `python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501` under systemd, behind HTTPS.

## Admin tasks

```
python manage_users.py list
python manage_users.py reset-password USERNAME
python manage_users.py unlock USERNAME
python manage_users.py make-admin USERNAME
```
Back up: MySQL with `mysqldump datapilot > backup.sql` (and `datapilot_storage/` if files are on disk).

## Tests

```
python -m pytest -q                                   # SQLite (disk + database storage), toolkit and the UI flows
TEST_MYSQL=1 MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=test_db python -m pytest -q
```
**Use an empty test database for the MySQL run: the tests delete all rows.** They cover: password hashing, lock-out, duplicate users, old-data takeover, two users never seeing each other's projects/chats/reports/uploads/settings, path-traversal and cross-user file reads blocked, tampered files detected, unicode and 3 MB files, rollback when a file write fails, account deletion, SQLite to MySQL migration, the login screen, project saving and logout in the real app, plus the toolkit: cleaning steps, formula and SQL injection attempts, statistical tests against known answers, regression recovering a known relationship, clustering, and every toolkit tab rendering.

## Known limits

* Reloading the browser page signs you out (Streamlit starts a new session). Staying signed in across reloads would need cookie-based sessions.
* There is no email password reset. The person running the app uses `manage_users.py`.
* Note: anyone who can reach the server can create an account. For a private deployment put the app behind a VPN, an access proxy, or tell me and I will add an invite code.
* The Flex look was checked in a real headless Chromium (login, landing, doors opening, light/dark cord, dashboard, toolkit, tables) with Streamlit 1.66. Other browsers and Streamlit versions were not tried. The tab and dropdown styles target both the old and the new Streamlit markup. If anything looks off, switch *Look* to *Modern* or *3D classic*.
* Tested on MariaDB 10.11 (MySQL-compatible) and SQLite. The Dockerfile, docker-compose file and Streamlit Cloud settings are written to the documented formats but were not run in this environment.
