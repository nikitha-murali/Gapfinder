import base64, hashlib, hmac, io, os, json, re, logging, secrets, sqlite3, time
from contextlib import contextmanager
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
KEY = os.getenv("TINYFISH_API_KEY")
DEMO_ONLY = os.getenv("DEMO_ONLY") == "1"
API = "https://agent.tinyfish.ai/v1/automation/run-sse"
DB_PATH = os.getenv("GAPFINDER_DB_PATH", os.path.join(BASE, "gapfinder.sqlite3"))
PREVIEW_CACHE_SECONDS = 900
PREVIEW_TIMEOUT_SECONDS = 15
LIVE_TIMEOUT_SECONDS = 180
MAX_PAGES = 10
MAX_RESUME_BYTES = 5_000_000
MAX_RESUME_CHARS = 30_000
SESSION_COOKIE = "gapfinder_session"
SESSION_SECONDS = 60 * 60 * 24 * 14
preview_cache = {"expires_at": 0.0, "payload": None}
logger = logging.getLogger(__name__)

BATCH = 4
CHALLENGE_BATCH = 6

SOURCES = {
    "cs": "https://internshala.com/internships/computer-science-internship",
    "web": "https://internshala.com/internships/web-development-internship",
    "data": "https://internshala.com/internships/data-science-internship",
    "design": "https://internshala.com/internships/design-internship",
    "marketing": "https://internshala.com/internships/marketing-internship",
    "business": "https://internshala.com/internships/business-development-internship",
}
GRADUATE_URL = "https://internshala.com/jobs/"
CHALLENGE_URL = "https://unstop.com/competitions"

INTERN_GOAL = (
    "Return the first {n} internships on this page as JSON with the key 'internships'. "
    "For each one open its page and return: title, company, stipend, deadline, "
    "apply_url (link to that internship's page), skills (list of required skills), "
    "and summary (2 sentences describing what the intern will actually do)."
)
CHALLENGE_GOAL = (
    "Return up to {n} currently open company-sponsored hackathons, case competitions, "
    "or real-world product, engineering, or business problem challenges as JSON with the key 'challenges'. "
    "Use only information visible on the original listing; do not invent company names, skills, rewards, "
    "or dates. For each one return: title, company (the named organiser, if listed), reward (prize or benefit, "
    "if listed), deadline (if listed), apply_url (the original challenge page), skills (skills explicitly "
    "required or clearly relevant to the stated prompt), and summary (a concise description of the actual "
    "task or problem participants are asked to solve)."
)
GRADUATE_GOAL = (
    "Return up to {n} currently open full-time entry-level or graduate jobs from this listing. "
    "Exclude internships and roles requiring substantial prior experience. For each one open its page "
    "and return a JSON object with the key 'jobs'. Each job must contain title, company, salary "
    "(if listed), deadline (if listed), apply_url, skills, and a concise summary of the actual "
    "responsibilities. Do not invent missing details."
)

MODES = {
    "internships": {"file": "sample.json", "key": "internships", "goal": INTERN_GOAL},
    "graduate": {"file": "sample_jobs.json", "key": "jobs", "goal": GRADUATE_GOAL},
    "challenges": {"file": "sample_challenges.json", "key": "challenges", "goal": CHALLENGE_GOAL},
}

# canonical skill -> other ways people write it
SKILLS = {
    "python": ["python3"],
    "java": [],
    "javascript": ["js", "ecmascript"],
    "typescript": [],
    "c++": ["cpp"],
    "c#": ["csharp"],
    "golang": [],
    "rust": [],
    "kotlin": [],
    "swift": [],
    "php": [],
    "ruby": [],
    "scala": [],
    "matlab": [],
    "r programming": [],
    "html": ["html5", "html 5"],
    "css": ["css3"],
    "react": ["react.js", "reactjs"],
    "angular": ["angularjs"],
    "vue": ["vue.js", "vuejs"],
    "next.js": ["nextjs"],
    "node.js": ["nodejs"],
    "express": ["express.js", "expressjs"],
    "django": [],
    "flask": [],
    "fastapi": [],
    "spring boot": ["springboot"],
    "tailwind css": ["tailwind"],
    "bootstrap": [],
    "sql": [],
    "mysql": [],
    "postgresql": ["postgres"],
    "mongodb": ["mongo db"],
    "sqlite": [],
    "firebase": [],
    "redis": [],
    "git": [],
    "github": [],
    "docker": [],
    "kubernetes": [],
    "linux": [],
    "aws": ["amazon web services"],
    "azure": [],
    "gcp": ["google cloud"],
    "ci/cd": ["cicd"],
    "pandas": [],
    "numpy": [],
    "scikit-learn": ["sklearn"],
    "tensorflow": [],
    "pytorch": [],
    "machine learning": ["ml"],
    "deep learning": [],
    "nlp": ["natural language processing"],
    "computer vision": [],
    "opencv": [],
    "data analysis": ["data analytics"],
    "data visualization": ["data visualisation"],
    "power bi": ["powerbi"],
    "tableau": [],
    "excel": ["ms excel", "microsoft excel"],
    "statistics": [],
    "rest api": ["rest apis", "restful api", "restful apis"],
    "graphql": [],
    "ui/ux design": ["ui & ux design", "ui/ux", "ux design", "ui design"],
    "figma": [],
    "software testing": ["manual testing", "qa testing"],
    "selenium": [],
    "postman": [],
    "android development": ["android"],
    "flutter": [],
    "react native": [],
    "cybersecurity": ["cyber security"],
    "networking": [],
    "blockchain": [],
    "ms-office": ["ms office", "microsoft office"],
    "project management": [],
    "problem solving": [],
    "communication": ["communication skills"],
    "teamwork": [],
    "leadership": [],
    "content writing": [],
    "seo": [],
    "digital marketing": [],
    "social media marketing": [],
    "video editing": [],
    "business development": [],
    "public speaking": [],
}

# having the key skill also covers these
IMPLIES = {
    "react": ["javascript"],
    "react native": ["react", "javascript"],
    "next.js": ["react", "javascript"],
    "node.js": ["javascript"],
    "express": ["node.js", "javascript"],
    "typescript": ["javascript"],
    "angular": ["javascript", "typescript"],
    "vue": ["javascript"],
    "django": ["python"],
    "flask": ["python"],
    "fastapi": ["python"],
    "pandas": ["python", "data analysis"],
    "numpy": ["python"],
    "scikit-learn": ["python", "machine learning"],
    "tensorflow": ["python", "machine learning"],
    "pytorch": ["python", "machine learning"],
    "deep learning": ["machine learning"],
    "mysql": ["sql"],
    "postgresql": ["sql"],
    "sqlite": ["sql"],
    "spring boot": ["java"],
    "github": ["git"],
    "tailwind css": ["css"],
    "bootstrap": ["css", "html"],
    "flutter": ["mobile development"],
}


def _build_aliases():
    out = {}
    for canon, alts in SKILLS.items():
        out[canon] = canon
        for a in alts:
            out[a] = canon
    return out


ALIASES = _build_aliases()


def _pattern(terms):
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(r"(?<![a-z0-9+#])(?:" + alts + r")(?![a-z0-9+#])")


PATTERNS = [(canon, _pattern([canon] + alts)) for canon, alts in SKILLS.items()]


def extract_skills(text):
    low = text.lower()
    found = []
    for canon, pat in PATTERNS:
        m = pat.search(low)
        if m:
            found.append((m.start(), canon))
    found.sort()
    return [c for _, c in found]


app = FastAPI()


class Query(BaseModel):
    source: str = "cs"
    demo: bool = True
    mode: str = "internships"
    page: int = 1
    level: str = "fresher"


class AccountCredentials(BaseModel):
    email: str
    password: str


class AccountProfile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    skills: list[str] = Field(default_factory=list)
    learned: list[str] = Field(default_factory=list)
    source: str = "cs"
    level: str = "fresher"
    min_match: int = 0
    results: dict[str, list[dict]] = Field(default_factory=dict)
    results_demo: bool = False
    demo_mode: bool = True


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with database() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                profile TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_attempts (
                id INTEGER PRIMARY KEY,
                remote_address TEXT NOT NULL,
                attempted_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS auth_attempts_address_time
                ON auth_attempts(remote_address, attempted_at);
            """
        )
        if not os.getenv("SESSION_SECRET"):
            connection.execute(
                "INSERT OR IGNORE INTO account_settings (key, value) VALUES (?, ?)",
                ("session_secret", secrets.token_urlsafe(48)),
            )


init_database()


def session_secret():
    configured = os.getenv("SESSION_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("SESSION_SECRET must contain at least 32 characters.")
        return configured.encode("utf-8")
    with database() as connection:
        row = connection.execute(
            "SELECT value FROM account_settings WHERE key = ?", ("session_secret",)
        ).fetchone()
    if row is None:
        raise RuntimeError("The account session secret is missing from the database.")
    return row["value"].encode("utf-8")


def encode_session(account_id):
    payload = json.dumps(
        {"account_id": account_id, "expires": int(time.time()) + SESSION_SECONDS},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(session_secret(), encoded, hashlib.sha256).digest()
    return encoded.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def current_account_id(request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 1024:
        return None
    try:
        encoded, signature = token.split(".", 1)
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        expected = hmac.new(session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return None
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(payload)
        if int(data["expires"]) < int(time.time()):
            return None
        return int(data["account_id"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def require_account(request):
    account_id = current_account_id(request)
    if account_id is None:
        raise HTTPException(status_code=401, detail="Sign in to access your saved profile.")
    return account_id


def set_session_cookie(response, request, account_id):
    response.set_cookie(
        SESSION_COOKIE,
        encode_session(account_id),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def enforce_auth_rate_limit(request):
    remote_address = request.client.host if request.client else "unknown"
    now = int(time.time())
    with database() as connection:
        connection.execute("DELETE FROM auth_attempts WHERE attempted_at < ?", (now - 86400,))
        attempts = connection.execute(
            "SELECT COUNT(*) AS count FROM auth_attempts "
            "WHERE remote_address = ? AND attempted_at > ?",
            (remote_address, now - 900),
        ).fetchone()["count"]
        if attempts >= 20:
            raise HTTPException(
                status_code=429,
                detail="Too many account requests. Please wait 15 minutes and try again.",
            )
        connection.execute(
            "INSERT INTO auth_attempts (remote_address, attempted_at) VALUES (?, ?)",
            (remote_address, now),
        )


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 600_000
    ).hex()


def valid_email(email):
    return bool(
        len(email) <= 254
        and re.fullmatch(
            r"[^@\s]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}",
            email,
        )
    )


def default_profile():
    return AccountProfile().model_dump()


def clean_profile(profile):
    if len(profile.skills) > 100:
        raise HTTPException(status_code=400, detail="A profile can contain at most 100 skills.")
    if profile.source not in SOURCES:
        raise HTTPException(status_code=400, detail="Choose a supported internship search area.")
    if profile.level not in ("fresher", "graduate"):
        raise HTTPException(status_code=400, detail="Choose a supported career level.")
    if profile.min_match not in (0, 30, 50, 70):
        raise HTTPException(status_code=400, detail="Choose a supported minimum match.")
    clean_skills = []
    for skill in profile.skills:
        if not isinstance(skill, str):
            raise HTTPException(status_code=400, detail="Skills must be text.")
        skill = skill.strip().lower()
        if not skill or len(skill) > 80:
            raise HTTPException(status_code=400, detail="Each skill must be 1 to 80 characters.")
        if skill not in clean_skills:
            clean_skills.append(skill)
    clean_learned = []
    if len(profile.learned) > 100:
        raise HTTPException(status_code=400, detail="A roadmap can contain at most 100 learned skills.")
    for skill in profile.learned:
        if not isinstance(skill, str):
            raise HTTPException(status_code=400, detail="Learned skills must be text.")
        skill = skill.strip().lower()
        if not skill or len(skill) > 80:
            raise HTTPException(status_code=400, detail="Each learned skill must be 1 to 80 characters.")
        if skill not in clean_learned:
            clean_learned.append(skill)
    clean_results = {}
    if len(profile.results) > MAX_PAGES:
        raise HTTPException(status_code=400, detail="Too many saved result pages.")
    fields = ("title", "company", "stipend", "salary", "reward", "deadline", "apply_url", "summary")
    for page, items in profile.results.items():
        if not page.isdigit() or not 1 <= int(page) <= MAX_PAGES or len(items) > BATCH:
            raise HTTPException(status_code=400, detail="Saved search results are invalid.")
        clean_items = []
        for item in items:
            clean_item = {}
            for field in fields:
                value = item.get(field, "")
                if not isinstance(value, str) or len(value) > 5000:
                    raise HTTPException(status_code=400, detail="Saved listing details are invalid.")
                clean_item[field] = value
            item_skills = item.get("skills", [])
            if not isinstance(item_skills, list) or len(item_skills) > 50 or any(
                not isinstance(skill, str) or len(skill) > 100 for skill in item_skills
            ):
                raise HTTPException(status_code=400, detail="Saved listing skills are invalid.")
            clean_item["skills"] = item_skills
            clean_items.append(clean_item)
        clean_results[page] = clean_items
    cleaned = {
        "first_name": profile.first_name.strip()[:100],
        "last_name": profile.last_name.strip()[:100],
        "skills": clean_skills,
        "learned": clean_learned,
        "source": profile.source,
        "level": profile.level,
        "min_match": profile.min_match,
        "results": clean_results,
        "results_demo": profile.results_demo,
        "demo_mode": profile.demo_mode,
    }
    if len(json.dumps(cleaned, ensure_ascii=False)) > 1_000_000:
        raise HTTPException(status_code=413, detail="Saved profile data is too large.")
    return cleaned


def sse(d):
    return f"data: {json.dumps(d)}\n\n"


def stream(q: Query):
    page = max(1, min(q.page, MAX_PAGES))
    is_ch = q.mode == "challenges"
    is_graduate = q.mode == "graduate" or (
        q.mode == "internships" and q.level == "graduate"
    )
    mode = "challenges" if is_ch else "graduate" if is_graduate else "internships"
    cfg = MODES[mode]

    if q.demo or DEMO_ONLY:
        items = []
        if page == 1:
            with open(os.path.join(BASE, cfg["file"]), encoding="utf-8") as f:
                items = json.load(f)[cfg["key"]]
        yield sse({"type": "result", "items": items, "demo": True, "page": page})
        return

    if not KEY:
        yield sse({"type": "error", "text": "Server has no TINYFISH_API_KEY set."})
        return

    base = CHALLENGE_URL if is_ch else GRADUATE_URL if is_graduate else SOURCES.get(q.source, SOURCES["cs"])
    url = base if (is_ch or page == 1) else f"{base}/page-{page}"
    n = CHALLENGE_BATCH if is_ch else BATCH
    goal = cfg["goal"].format(n=n)

    yield sse({"type": "progress", "text": "Starting the web agent..."})
    try:
        with requests.post(
            API,
            headers={"X-API-Key": KEY},
            json={"url": url, "goal": goal},
            stream=True,
            timeout=(10, LIVE_TIMEOUT_SECONDS),
        ) as response:
            if response.status_code != 200:
                yield sse({"type": "error", "text": f"TinyFish returned HTTP {response.status_code}."})
                return

            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    text = line.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if not text.startswith("data:"):
                    continue
                try:
                    event = json.loads(text[5:].strip())
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "PROGRESS":
                    yield sse({"type": "progress", "text": str(event.get("purpose", ""))[:500]})
                elif event_type == "COMPLETE":
                    if event.get("status") != "COMPLETED":
                        yield sse({"type": "error", "text": f"Live search ended with status {event.get('status', 'unknown')}."})
                        return
                    result = event.get("result")
                    if isinstance(result, str):
                        try:
                            result = json.loads(result)
                        except json.JSONDecodeError:
                            yield sse({"type": "error", "text": "Live search returned unreadable listing data. Please try again."})
                            return
                    if not isinstance(result, dict):
                        yield sse({"type": "error", "text": "Live search returned an unexpected result. Please try again."})
                        return
                    items = result.get(cfg["key"], [])
                    if not isinstance(items, list):
                        yield sse({"type": "error", "text": "Live search returned listings in an unexpected format."})
                        return
                    yield sse({
                        "type": "result",
                        "items": [item for item in items if isinstance(item, dict)][:n],
                        "demo": False,
                        "page": page,
                    })
                    return
    except requests.RequestException as error:
        logger.warning("TinyFish live search failed: %s", error)
        yield sse({
            "type": "error",
            "text": "Live search could not reach the listing service. Please try again shortly.",
        })
        return
    yield sse({"type": "error", "text": "The agent stopped without a result."})


@app.post("/api/search")
def search(q: Query):
    return StreamingResponse(stream(q), media_type="text/event-stream")


def account_payload(account):
    return {"email": account["email"]}


def require_fetch_request(request):
    if request.headers.get("x-gapfinder-request") != "1":
        raise HTTPException(status_code=403, detail="This account request was rejected.")


@app.post("/api/account/signup")
def signup(credentials: AccountCredentials, request: Request):
    require_fetch_request(request)
    enforce_auth_rate_limit(request)
    email = credentials.email.strip().lower()
    password = credentials.password
    if not valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(password) < 12 or len(password) > 128:
        raise HTTPException(status_code=400, detail="Password must be 12 to 128 characters.")
    salt = secrets.token_bytes(16)
    password_hash = hash_password(password, salt)
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO accounts (email, password_hash, password_salt, profile, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (email, password_hash, salt.hex(), json.dumps(default_profile()), int(time.time())),
            )
            account_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    response = JSONResponse({"user": {"email": email}}, headers={"Cache-Control": "no-store"})
    set_session_cookie(response, request, account_id)
    return response


@app.post("/api/account/login")
def login(credentials: AccountCredentials, request: Request):
    require_fetch_request(request)
    enforce_auth_rate_limit(request)
    email = credentials.email.strip().lower()
    if not valid_email(email) or len(credentials.password) > 128:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    with database() as connection:
        account = connection.execute(
            "SELECT id, email, password_hash, password_salt FROM accounts WHERE email = ?",
            (email,),
        ).fetchone()
    salt = bytes.fromhex(account["password_salt"]) if account else bytes(16)
    actual_hash = hash_password(credentials.password, salt)
    expected_hash = account["password_hash"] if account else "0" * 64
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    response = JSONResponse(
        {"user": account_payload(account)},
        headers={"Cache-Control": "no-store"},
    )
    set_session_cookie(response, request, account["id"])
    return response


@app.get("/api/account/me")
def account_me(request: Request):
    account_id = current_account_id(request)
    if account_id is None:
        return JSONResponse({"user": None}, headers={"Cache-Control": "no-store"})
    with database() as connection:
        account = connection.execute(
            "SELECT email FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    if account is None:
        return JSONResponse({"user": None}, headers={"Cache-Control": "no-store"})
    return JSONResponse(
        {"user": account_payload(account)},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/account/logout")
def logout(request: Request):
    require_fetch_request(request)
    response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/account/profile")
def get_account_profile(request: Request):
    account_id = require_account(request)
    with database() as connection:
        row = connection.execute(
            "SELECT profile FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Your account is no longer available.")
    return JSONResponse(
        {"profile": json.loads(row["profile"])},
        headers={"Cache-Control": "no-store"},
    )


@app.put("/api/account/profile")
def update_account_profile(profile: AccountProfile, request: Request):
    require_fetch_request(request)
    account_id = require_account(request)
    cleaned = clean_profile(profile)
    with database() as connection:
        result = connection.execute(
            "UPDATE accounts SET profile = ? WHERE id = ?",
            (json.dumps(cleaned, ensure_ascii=False), account_id),
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=401, detail="Your account is no longer available.")
    return JSONResponse(
        {"profile": cleaned},
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/account")
def delete_account(request: Request):
    require_fetch_request(request)
    account_id = require_account(request)
    with database() as connection:
        connection.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return response


def sample_listing_preview():
    with open(os.path.join(BASE, "sample.json"), encoding="utf-8") as f:
        return json.load(f)["internships"][:3]


@app.get("/api/listings")
def listings_preview():
    now = time.monotonic()
    cached = preview_cache["payload"]
    if cached is not None and now < preview_cache["expires_at"]:
        return {**cached, "cached": True}

    payload = {"items": sample_listing_preview(), "source": "sample"}
    if KEY and not DEMO_ONLY:
        deadline = now + PREVIEW_TIMEOUT_SECONDS
        try:
            with requests.post(
                API,
                headers={"X-API-Key": KEY},
                json={
                    "url": SOURCES["cs"],
                    "goal": INTERN_GOAL.format(n=3),
                },
                stream=True,
                timeout=(4, 4),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if time.monotonic() >= deadline:
                        logger.warning("TinyFish listing preview timed out; serving sample listings.")
                        break
                    if not line or not line.startswith(b"data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") != "COMPLETE" or event.get("status") != "COMPLETED":
                        continue
                    result = event.get("result")
                    if isinstance(result, str):
                        try:
                            result = json.loads(result)
                        except json.JSONDecodeError:
                            result = None
                    items = result.get("internships", []) if isinstance(result, dict) else []
                    if items:
                        payload = {
                            "items": [item for item in items if isinstance(item, dict)][:3],
                            "source": "tinyfish",
                        }
                    break
        except requests.RequestException as exc:
            logger.warning("TinyFish listing preview failed; serving sample listings: %s", exc)

    preview_cache["payload"] = payload
    preview_cache["expires_at"] = time.monotonic() + PREVIEW_CACHE_SECONDS
    return {**payload, "cached": False}


@app.post("/api/resume")
async def resume(file: UploadFile | None = File(None), text: str = Form("")):
    raw = text or ""
    if len(raw.encode("utf-8")) > MAX_RESUME_BYTES:
        return JSONResponse({"error": "Pasted resume text is too large (max 5 MB)."}, status_code=400)
    if file is not None and file.filename:
        data = await file.read(MAX_RESUME_BYTES + 1)
        if len(data) > MAX_RESUME_BYTES:
            return JSONResponse({"error": "File is too large (max 5 MB)."}, status_code=400)
        name = file.filename.lower()
        try:
            if name.endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(data))
                if reader.is_encrypted:
                    return JSONResponse(
                        {"error": "This PDF is password-protected. Export an unlocked copy and try again."},
                        status_code=400,
                    )
                raw = "\n".join((p.extract_text() or "") for p in reader.pages)
            elif name.endswith(".docx"):
                import docx
                d = docx.Document(io.BytesIO(data))
                parts = [p.text for p in d.paragraphs]
                for table in d.tables:
                    for row in table.rows:
                        parts.append(" | ".join(c.text for c in row.cells))
                raw = "\n".join(parts)
            elif name.endswith((".txt", ".md")):
                raw = data.decode("utf-8")
            else:
                return JSONResponse(
                    {"error": "Upload a PDF, DOCX, TXT, or Markdown file."},
                    status_code=400,
                )
        except UnicodeDecodeError:
            return JSONResponse(
                {"error": "Text files must use UTF-8 encoding. Try saving the file as UTF-8 or paste the text."},
                status_code=400,
            )
        except Exception as error:
            logger.info("Resume parsing failed for %s (%s).", name, type(error).__name__)
            return JSONResponse(
                {"error": "Could not read that file. Check that it is a valid, unlocked PDF or DOCX, or paste its text."},
                status_code=400,
            )
    raw = raw.strip()
    if not raw:
        return JSONResponse({"error": "No text found. If the PDF is a scan, paste the text instead."}, status_code=400)
    truncated = len(raw) > MAX_RESUME_CHARS
    raw = raw[:MAX_RESUME_CHARS]
    return {"text": raw, "skills": extract_skills(raw), "truncated": truncated}


@app.get("/api/config")
def config():
    return {"demo_only": DEMO_ONLY, "aliases": ALIASES, "implies": IMPLIES}


@app.get("/")
def home():
    return FileResponse(os.path.join(BASE, "static", "index.html"))