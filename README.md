# GapFinder

GapFinder is a FastAPI app that compares your skills with internship and entry-level job listings.

## Run locally

Install the packages in `requirements.txt`, then start the server with:

```powershell
python -m uvicorn main:app --reload
```

By default, account data is stored in `gapfinder.sqlite3` next to `main.py`. Set `GAPFINDER_DB_PATH` to use another persistent SQLite file. The database contains account email addresses, password hashes, profile skills/preferences, and recent listing results. Resume text is used for parsing and tailoring in the current browser session only; it is not saved to the account. The SQLite database is not encrypted at rest; protect the file and its backups.

Passwords are hashed and sessions use signed, HTTP-only cookies. Use HTTPS when hosting the app. Email addresses are not verified and password reset is not available; users should enter an address they control. Account owners can delete their account from the account dialog.

## Search configuration

Set `TINYFISH_API_KEY` in the server environment to enable live searches. `DEMO_ONLY=1` forces sample data. Internship search includes computer science, web development, data science, design, marketing, and business development categories. Graduate mode searches the Internshala jobs page; live results depend on that page and the configured listing service. Search is capped at ten pages per query.

## Interactive roadmap

The roadmap groups skill gaps into weekly plans based on the time you enter, and lets you reorder skills, track them as Not started, Learning, or Practiced, and celebrate completed projects. The roadmap has its own deep-sea scene; subtle drifting bubbles, swimming fish, and underwater light effects continue across the other app views. Animations respect reduced-motion preferences and are toned down in day mode. Weekly hours, progress states, and priority order are stored in the browser; learned skills continue to be saved with your account. During a live opportunity search, you can opt in to a browser notification when the results are ready. Notifications require a secure origin (HTTPS or localhost) and browser permission.

The My goals view adds cosmetic XP for actions such as saving a role, completing a roadmap project, tailoring a resume, and confirming an application. It also tracks a daily skill-practice mission, a weekly suitable-role wishlist mission, and mini-project skill bosses for saved roles. XP, missions, and the wishlist are stored in the current browser and are separate from account-synced profile data. Application confirmations are self-reported; GapFinder does not submit applications.
