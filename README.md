# SyncTask assistant (backend)

Read-only assistant for SyncTask. It answers questions about the user's own projects and
tasks with a local Ollama model. The database is read in code, and the model writes the
answer from that data. This repo is separate from the
SyncTask Expo app and shares no code with it.

## Safety defaults

- The backend reads the Firebase project named by `FIREBASE_PROJECT_ID`. Admin access bypasses
  security rules, so the membership check in the code is what keeps users to their own projects.
- `FIREBASE_PROJECT_ID` must be set explicitly; startup refuses to run without it.
  `python -m synctask_assistant.startup` shows what the guard decides.
- Never commit keys. `.env` and service-account JSON files are git-ignored; `.env.example`
  holds names only.

## Install and run

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Ollama with the model named in
`ASSISTANT_MODEL` already pulled.

```powershell
uv sync --locked
Copy-Item .env.example .env   # fill in the values; on a server, set them in the platform instead
uv run python -m synctask_assistant.api
```

The server listens on `127.0.0.1:8000` by default. See "Phone on the same Wi-Fi (demo)" to change
that.

## Schema

`schema.json` is the allowlist the backend loads at startup: collections, fields, types, enums,
patterns, operators, and excluded data, built from the SyncTask app's data model. It is read from
the repo root, so keep it there when you deploy.

## How an answer is made

1. The ID token is verified. The user id comes only from the token; a `userId` in the body is ignored.
2. The backend reads the projects whose `memberIds` contain that id, then every task in those
   projects (`projects/{id}/tasks`).
3. `context.py` builds one text block. It starts with a summary per project (status counts,
   overdue count, open tasks per person), then lists tasks, open ones first and earliest
   deadline first. Summary counts cover every task. The list is capped by
   `ASSISTANT_CONTEXT_TASKS` (default 150) and `ASSISTANT_CONTEXT_CHARS` (default 24000), and
   the block states how many tasks it lists.
4. `answer.py` sends the question and the block in one model call, with no tools and no output
   schema. The block sits inside tags with a random value, so its content cannot close it early.
   The system message says the block is data written by other people.
5. The response is `{"status": "ok", "answer": ..., "scope": {...}}`. `scope` reports how many
   projects and tasks were used, how many tasks were listed, and whether the list was truncated.
   No raw rows are returned.

Stored titles, names and descriptions are collapsed to one line and cut to a fixed length
before they reach the model, so they cannot add layout or lines of their own.

## Model and HTTP settings

| Variable | Default | Meaning |
|---|---|---|
| `ASSISTANT_MODEL` | `gemma4:e2b` | Ollama model name |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama server; must start with http:// or https:// |
| `ASSISTANT_TEMPERATURE` | `0.2` | 0 to 2 |
| `ASSISTANT_TOP_P` | unset | 0 to 1 |
| `ASSISTANT_MODEL_TIMEOUT` | `60` | Seconds, 1 to 600 |
| `ASSISTANT_NUM_CTX` | `16384` | Context window sent to Ollama, 2048 to 262144 |
| `ASSISTANT_THINK` | `on` | `on` leaves the model's own reasoning default; `off` turns reasoning off |
| `ASSISTANT_ANSWER_TOKENS` | `2048` | Most tokens one answer may use, reasoning included, 128 to 8192 |
| `CORS_ORIGINS` | empty | Browser origins allowed to call the API, comma-separated, for example `http://localhost:8081`. Empty allows none. Wildcards are refused |
| `ASSISTANT_CONTEXT_TASKS` | `150` | Most task lines in the data block, 1 to 2000 |
| `ASSISTANT_CONTEXT_CHARS` | `24000` | Size budget for the data block, 2000 to 200000 |
| `ASSISTANT_TIMEZONE` | `UTC` | IANA zone used for "today" |
| `ASSISTANT_WEEK_START` | `monday` | `monday` or `sunday` |

`POST /ask` takes `{"question": "..."}` with a Firebase ID token in the `Authorization: Bearer`
header. The question is 1 to 500 characters. A missing, malformed, expired, revoked or invalid
token gets 401 before the body is read, and no model or database call is made. Model or database
outages return 503 with a safe message.

## Real Firebase project (demo)

To use your real Firebase project:

1. In the Firebase console, open your project's **Project settings → Service accounts** and click
   **Generate new private key**. Save the JSON file outside this repository, for example
   `C:\Users\<you>\secrets\synctask-admin.json`.
2. In `.env`, set the project and the key. Make sure no emulator variables are set:

   ```
   FIREBASE_PROJECT_ID=your-real-project-id
   GOOGLE_APPLICATION_CREDENTIALS=C:\Users\<you>\secrets\synctask-admin.json
   ```
3. Check the guard: `uv run python -m synctask_assistant.startup` should print
   `OK: NON-EMULATOR (explicit project id)`.

The key bypasses Firestore security rules, and the backend's membership check is what keeps users to
their own projects. Never commit it, share it, or put it in the Expo app.
## Phone on the same Wi-Fi (demo)

The server listens on localhost by default, so a phone cannot reach it. For the demo:

1. Add `HOST=0.0.0.0` to `.env` and restart the API.
2. Set the Wi-Fi network to **Private** in Windows settings.
3. Find the computer's address with `ipconfig`: the IPv4 address of the Wi-Fi adapter, for example `192.168.1.23`.
4. On the phone's browser, open `http://192.168.1.23:8000/health`. You should see
   `{"status":"ok", ...}`. If this fails, the problem is the network or firewall, not the app.
5. Set `EXPO_PUBLIC_ASSISTANT_URL=http://192.168.1.23:8000` in the client's `.env` and restart Expo.

Cautions:

- Use a hotspot from your own phone or computer rather than school Wi-Fi. Traffic is plain HTTP, and
  other devices on a shared network could reach the API.
