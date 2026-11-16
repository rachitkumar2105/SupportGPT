# SupportGPT — Independent Audit Report

**Date:** 2026-08-31
**Scope:** Re-verify all previously claimed fixes against the actual code and a live run; find new gaps not previously covered; fix what's broken; verify the fixes.

Every claim below was checked by running something — a live process, a reproduction script, a simulated attack, or a fresh dependency install — not by re-reading the code and trusting a comment. Exact commands are included so results can be reproduced.

---

## Phase 1 — Re-verification of previously claimed fixes

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | No hardcoded/auto-seeded credentials unless `SEED_DEMO_USERS=true` | **Confirmed correct** | Single seed path (`seed_users()` in `app.py`), gated by `if not SEED_DEMO_USERS: return`, defaults to `false`. Grepped the whole repo for `admin@123`/`developer@123` — only that one function and the demo-user constants inside it reference them. |
| 2 | `SECRET_KEY` has no fallback; app fails to start without it | **Confirmed correct** (after fixing my own test) | First attempt gave a false negative: I unset `SECRET_KEY` from the process env but `load_dotenv()` silently refilled it from the local `.env` file (`python-dotenv` doesn't override existing vars, but it *does* fill in ones that are absent). Re-tested by moving `.env` aside entirely — app raises `RuntimeError` and refuses to import. |
| 3 | CORS is locked to an explicit origin list, not `*` | **Confirmed correct, but a real gap found and fixed** | Default `ALLOWED_ORIGINS` has no wildcard. But nothing stopped an operator from setting `ALLOWED_ORIGINS=*` via env — with `allow_credentials=True` that's the exact invalid/vulnerable combination the original audit flagged. Added a startup guard that raises `RuntimeError` if `*` appears in `ALLOWED_ORIGINS`. |
| 4 | Every endpoint uses Pydantic request/response models | **Partially correct — response models were never added** | Grepped every `@app.*` route: all 21 endpoints take a typed Pydantic `payload` (or no body). No endpoint declares a `response_model`; all return plain dicts. The original phase-1 spec asked for "request/response models" — only the request half was ever done. Documented as a known limitation (see below); not fixed in this pass — would touch every endpoint's return shape and is out of scope for a bug-fix pass. |
| 5 | RAG pipeline is real (chunking → embeddings → top-k retrieval) | **Confirmed correct**, traced end-to-end in code + live | `/upload` → `rag.chunk_document()` → `rag.embed_texts()` → persisted as `DocumentChunk` rows. `/chat` → `retrieve_relevant_chunks()` → per-request FAISS `IndexFlatIP` over that user's persisted chunk vectors → threshold-filtered top-k → cited in the system prompt and returned as `sources`. Live-tested (real fastembed, real Groq): uploaded a shipping-policy doc, asked a grounded question, got a correct answer with `sources: [{"page": null, "relevance": 0.875}]`. |
| 6 | Knowledge base only stores Q&A after positive feedback, not unconditionally | **Confirmed correct, but a real gap found and fixed** | Traced `/chat` and `/chat/stream` — neither writes to `KnowledgeEntry` anymore; only `/feedback` does, gated on `is_positive`. **New gap**: `/feedback` trusted the client-submitted `query`/`response` pair with no check that `response` was ever actually produced by the AI for this user — a client could submit `is_positive: true` with a fabricated answer and get it promoted into the shared knowledge base. Fixed: promotion now requires `response` to match an existing `ChatHistory` row (`role="assistant"`) for the current user. |
| 7 | Groq model ID currently in use is not deprecated | **Confirmed correct** | `client.models.list()` called live: `openai/gpt-oss-120b` is in the returned list, `llama-3.3-70b-versatile` is not. |
| 8 | Dual-key failover actually triggers on 429/quota errors | **Confirmed via simulation — cannot force a genuine live 429 from Groq on demand** | Directly exercised `DualKeyGroqClient.create_completion()` with a stubbed primary client raising an exception shaped like Groq's real rate-limit error (`status_code = 429`): confirmed it calls primary, catches, retries on secondary, returns `key_used="secondary"`. Also confirmed a non-quota error (`status_code = 401`) does **not** fail over — propagates immediately, only the primary is called. This is simulation of the exact code path, not proof against Groq's live infrastructure. |

---

## Phase 2 — New gaps found

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| A | `Base.metadata.create_all()` doesn't alter existing tables — a pre-existing `app.db` (e.g. the actual deployed instance, which predates the `document_chunks`/`KnowledgeEntry.embedding` schema changes) would crash `/chat` with a 500 on every request (`no such column: knowledge_base.embedding`) | **Critical** (deploy-breaking, data-availability) | **Fixed.** Added `run_lightweight_migrations()` in `database.py`: diffs each model's columns against the live table via SQLAlchemy `inspect()` and adds any missing ones with `ALTER TABLE ... ADD COLUMN`. Reproduced the exact crash against a hand-built old-schema SQLite file, confirmed the fix patches it and `/chat` no longer 500s. |
| B | Path traversal via upload filename — `file.filename` was used unsanitized in the save path (`docs/{username}_{filename}`) | **High** (arbitrary file write, bounded by process file permissions) | **Fixed.** Added `safe_filename()`: strips both `/` and `\` path separators explicitly (plain `os.path.basename()` would miss a Windows-style `..\..\x` traversal string on a POSIX host), strips leading dots, replaces disallowed characters. Verified live against a running server with `requests` (curl's multipart filename override didn't actually reach the server) — the file landed at `docs/{user}_evil_traversal.txt`, never escaped the project directory. |
| C | Ticket owner could self-modify `status`/`priority`/`ai_response` on their own ticket via `PUT /tickets/{id}`, bypassing the developer-only resolution flow (this predates my earlier changes — it was present in the original `app.py` too) | **Medium** (authorization/workflow bypass) | **Fixed.** `update_ticket` now rejects (`403`) any attempt by a non-staff owner to set `status`, `priority`, or `ai_response` — those fields are staff-only regardless of ticket ownership. Added regression tests. |
| D | `/chat/stream`'s exception handler leaked the raw exception string (`str(e)`) to the client over SSE | **Medium** (information disclosure) | **Fixed.** Now logs the real exception server-side and streams a generic error message. |
| E | `/upload`'s PDF-processing exception handler leaked the raw exception string in the `500` response body | **Low-Medium** (information disclosure) | **Fixed.** Same pattern — logged server-side, generic message to the client. |
| F | No upload size limit — an attacker could upload an arbitrarily large file | **Medium** (resource exhaustion / DoS) | **Fixed.** Added `MAX_UPLOAD_BYTES` (10 MB) enforced via a streaming, size-capped copy (`save_upload_capped`) that aborts and deletes the partial file with `413` once the cap is exceeded, rather than buffering the whole file first. |
| G | No `max_length` on `ChatRequest.message`, `VoiceRequest.transcript`, `TicketCreateRequest.issue`, `FeedbackRequest` fields, or passwords/usernames — a client could send megabyte-scale text fields, forcing large/expensive Groq calls or embedding computations | **Medium** (cost/DoS) | **Fixed.** Added `max_length` to every free-text field in `schemas.py` (chat/voice: 4000 chars, tickets/feedback: 2000–8000, passwords: 128, etc). |
| H | Dependency CVEs: `fastapi==0.104.1` (PYSEC-2024-38), `starlette==0.27.0` (7 separate CVEs, pinned transitively via the old fastapi), `PyPDF2==3.0.1` (PYSEC-2026-1835), `ecdsa==0.19.2` (PYSEC-2026-1325) — **and** the pins in `requirements.txt` didn't actually match what any prior session had tested against (the environment already had newer fastapi/pydantic pre-installed, so `requirements.txt` was silently untested) | **High** (known CVEs + untested pins) | **Fixed for fastapi/starlette/PyPDF2. `ecdsa` documented as a known limitation — no fix available upstream.** Bumped `fastapi` to `0.136.3` and `pydantic` to `2.13.4` (verified in a **fresh venv**, not the pre-polluted global site-packages). Replaced the abandoned `PyPDF2` with its actively-maintained successor `pypdf` (`from pypdf import PdfReader`) — `PyPDF2`'s last release is 3.0.1 and no newer version will ever ship. `ecdsa`: this is a transitive dependency of `python-jose` (unconditionally required even with the `[cryptography]` extra); the vulnerability is a Minerva timing side-channel on ECDSA signing/keygen, and the upstream project has explicitly stated **there is no planned fix** (side-channel attacks are out of scope for that project). This app only ever uses JWT `HS256` (HMAC), never generates or uses EC keys — the vulnerable code path is present in the dependency tree but never invoked by this codebase. No further action taken; flagged as accepted risk. |
| I | Feedback endpoint trusted arbitrary client-submitted `query`/`response` pairs for knowledge-base promotion | **Medium** (data integrity / poisoning) | **Fixed** — see Phase 1 item 6 above. |
| J | `rag._get_embedder()`'s lazy singleton had a benign race: concurrent first requests (FastAPI sync endpoints run in a threadpool) could each see `_embedder is None` and construct/load the ONNX model redundantly | **Low** (wasted CPU/memory on cold start only, not a correctness bug) | **Fixed.** Added double-checked locking with a `threading.Lock`. |
| K | FAISS index persistence across restart | **Confirmed not an issue by design — no fix needed** | There is no separate FAISS index file to lose. Every retrieval call rebuilds a small `IndexFlatIP` on the fly from `DocumentChunk.embedding` rows read fresh from the DB (see `retrieve_relevant_chunks`), which *is* the durable, restart-safe store. Verified live: uploaded a doc, killed the server process entirely, started a brand-new process, queried again — retrieval still worked. |
| L | Concurrent request safety / shared mutable state | **One item confirmed and already documented; nothing new found beyond J above** | Grepped `app.py` for module-level mutable globals: only `_rate_limit = {}` remains (the in-memory IP rate limiter), which already carries an explicit code comment noting it's per-process/not multi-worker-safe and would need Redis to scale out. No other shared state remains — the old `user_documents_context`/`user_chat_memory` in-memory caches were already removed in the prior session. |
| M | No Alembic / real migration tool | **Confirmed — documented, partially mitigated** | Confirmed no `alembic` anywhere in the repo. Not adding full Alembic in this pass (would be a substantial scope increase for a bug-fix audit); instead added the lightweight `run_lightweight_migrations()` (item A) that covers this project's actual migration pattern so far (adding nullable columns). This does **not** handle renames, type changes, backfills, or dropped columns — a real migration tool is still recommended before the schema changes in more complex ways. |
| N | Malicious/empty filename handling | **Confirmed and fixed as part of item B** | Added an explicit `if not file.filename: raise HTTPException(400, ...)` guard — previously an empty filename would have thrown an unguarded `AttributeError` on `.lower()`. |

---

## Phase 3 — What was actually fixed (severity order)

1. **[Critical]** Lightweight startup migration for columns added to existing tables (`database.py`)
2. **[High]** Path traversal via unsanitized upload filenames (`app.py`)
3. **[High]** Dependency CVEs: fastapi/starlette bump, PyPDF2 → pypdf migration (`requirements.txt`, `app.py`)
4. **[Medium]** Ticket owner could bypass the developer-only resolution flow (`app.py`)
5. **[Medium]** Feedback endpoint could poison the knowledge base with fabricated responses (`app.py`)
6. **[Medium]** Raw exception messages leaked to clients in `/chat/stream` and `/upload` (`app.py`)
7. **[Medium]** No upload size limit (`app.py`)
8. **[Medium]** No `max_length` on free-text request fields (`schemas.py`)
9. **[Low]** CORS wildcard guard as defense-in-depth (`app.py`)
10. **[Low]** Benign race in the lazy embedder singleton (`rag.py`)
11. **[Test infra, not app code]** Fixed a flaky test caused by the test suite's own fake-embedding generator (see below)

Nothing was "fixed" that was already correct — items 1, 2, 5, 6, 7, 8, K, and L in the Phase 1/2 tables above required no code change, only verification.

### A bug found in my own test suite, not the app

While adding a regression test for item I (feedback promoting fabricated responses), the new test failed intermittently (~50% of full-suite runs, deterministic per `PYTHONHASHSEED`). Root cause: the test suite's fake-embedding generator (`tests/conftest.py`) used `numpy`'s `rand()` (uniform, **all-positive** components) instead of `randn()` (zero-mean, signed) to build deterministic stand-in vectors. `rand()`-based vectors all live in the same positive orthant, giving *any two unrelated strings* a spuriously high baseline cosine similarity (empirically ~0.7+) — enough to spill over the app's real 0.75 knowledge-base match threshold purely by chance, depending on hash-seed-driven randomness, and cause `find_knowledge` to falsely "match" two semantically unrelated questions. This is a test-fixture defect, not an application bug — real `fastembed` vectors don't have this clustering property. Fixed by switching to `randn()`; verified against 8 different `PYTHONHASHSEED` values (0–7), all pass now, where 2 of those 8 previously failed.

---

## Phase 4 — Verification

**Full pytest suite** (32 tests, up from 19 — added `tests/test_security.py`, `tests/test_migrations.py`, `tests/test_groq_failover.py`):
```
cd SupportGPT && rm -f app.db tests/test_app.db && python -m pytest tests/ -q
# 32 passed
```
Re-ran across `PYTHONHASHSEED` 0–7 to confirm the flaky test above is actually fixed, not just lucky:
```
for seed in 0 1 2 3 4 5 6 7; do PYTHONHASHSEED=$seed python -m pytest tests/ -q; done
# 32 passed, every seed
```

**Live end-to-end test** (real server, real Groq API, real fastembed embeddings — no mocks):
```bash
uvicorn app:app --host 127.0.0.1 --port 8140 &
curl -X POST :8140/signup ... / :8140/login ...
curl -X POST :8140/upload -F "file=@shipping.txt"   # real doc: shipping policy
curl -X POST :8140/chat -d '{"message":"How long does standard delivery take?"}'
```
Result: correct, grounded answer — `"Standard delivery takes 3 to 5 business days within the continental US【Document】."` — with `"sources":[{"page":null,"relevance":0.875}]`.

**Live path-traversal check against the running server** (not mocked):
```python
requests.post(".../upload", files={"file": ("../../evil_traversal.txt", b"malicious content", "text/plain")})
```
Result: `200 OK`, file landed at `docs/auditE2E1_evil_traversal.txt` — confirmed it never escaped the project directory.

**Dependency scan, before and after**:
```bash
pip install pip-audit
python -m pip_audit -r requirements.txt
```
- Before this pass: **12 known vulnerabilities in 4 packages** (fastapi, starlette, PyPDF2, ecdsa)
- After this pass, verified in a **fresh venv** installed straight from the updated `requirements.txt` (not the pre-polluted global environment used earlier): **1 known vulnerability in 1 package** (`ecdsa 0.19.2`, `PYSEC-2026-1325` — no fix version exists upstream; see Phase 2 item H for why this is an accepted, practically-unreachable risk for this app).

**Startup guard checks** (each actually run, not just read):
```bash
mv .env .env.bak && python -c "import os; os.environ['GROQ_API_KEY_PRIMARY']='x'; os.environ['GROQ_API_KEY_SECONDARY']='y'; import app"
# RuntimeError: SECRET_KEY environment variable must be set...
mv .env.bak .env

python -c "import os; os.environ.update(SECRET_KEY='t', GROQ_API_KEY_PRIMARY='x', GROQ_API_KEY_SECONDARY='y', ALLOWED_ORIGINS='*'); import app"
# RuntimeError: ALLOWED_ORIGINS cannot include '*'...
```

**Migration fix, reproduced and verified**:
```python
# built a standalone SQLite file with the OLD knowledge_base schema (no `embedding` column)
# imported the real app against it -> /chat crashed with:
#   sqlalchemy.exc.OperationalError: no such column: knowledge_base.embedding
# added run_lightweight_migrations() -> re-ran -> "Migrated schema: added column knowledge_base.embedding"
# -> /chat now returns 200
```

**Dual-key failover, simulated** (see Phase 1 item 8 — full script in `tests/test_groq_failover.py`).

---

## Known limitations (explicitly not fixed, or not fully verifiable)

- **`ecdsa` CVE (PYSEC-2026-1325)**: no upstream fix exists; accepted as low-practical-risk since this app never performs ECDSA signing/keygen (HS256 only). If `python-jose` ever drops its hard `ecdsa` dependency, or a fork appears, revisit.
- **No response_model on any endpoint**: every endpoint validates its request body but returns a plain dict, not a typed response model. The original Phase-1 spec asked for both; only requests were ever done. Not fixed here — would touch every endpoint's return shape, out of scope for a targeted fix pass.
- **No real migration tool (Alembic)**: `run_lightweight_migrations()` only handles adding nullable columns to existing tables — the one kind of schema change this project has made so far. It cannot handle renames, type changes, dropped columns, or data backfills. Recommend adopting Alembic before the schema changes in a way this lightweight approach can't cover.
- **In-memory rate limiter** (`_rate_limit` in `app.py`): still per-process, resets on restart, not shared across multiple workers. Already documented in-code; would need Redis to fix for real. Not addressed in this pass (pre-existing, known, low severity for the current single-worker deployment).
- **Dual-key failover was verified by simulation, not a genuine live 429 from Groq.** I don't control Groq's rate limits on demand, so I could not force a real 429 to prove the failover fires against Groq's actual infrastructure — only that the code correctly handles an exception shaped exactly like the one Groq's SDK raises for that case (confirmed via Groq's SDK exception shape: a `status_code` attribute internally).
- **OCR failure messages**: `[Image uploaded - OCR failed: {str(e)}]` still embeds a raw exception string into `extracted_text` for image uploads (not into an HTTP error response — it's the same user's own uploaded content, shown back only to them). Left as-is; lower severity than the two leaks that were fixed, and it's the uploading user's own data, not cross-user disclosure.
- **`Feedback.query`/`Feedback.response` storage**: the `/feedback` fix stops *fabricated* responses from being promoted to the knowledge base, but the `Feedback` table itself still stores whatever the client submits, unverified — that's an analytics/audit record, not something the app trusts for RAG or knowledge-base content, so it wasn't treated as a security issue.

---

## Files changed in this pass

`app.py`, `database.py`, `rag.py`, `requirements.txt`, `schemas.py`, `tests/conftest.py`, plus new `tests/test_security.py`, `tests/test_migrations.py`, `tests/test_groq_failover.py`.
