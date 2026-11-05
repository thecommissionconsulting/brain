# vault

The company's knowledge vault. Clients, internal practice, and how the company runs.

Start at [`index.md`](index.md) — it maps every folder and is the default way to
find a note. The rules are in [`_ai/rules.md`](_ai/rules.md).

This vault also has a **vector search**, described below. It is a second way in,
not a replacement for the index.

---

## Searching the vault by meaning

Use this when you don't know *where* something lives, or when the words in your
head won't match the words in the note. Semantic search finds
"lakehouse migration" in a note that only ever says "data platform rebuild".

### How to use it

**1. Ask, naming the search.** Either form works:

```
/vault-rag what did we do for Kiwibank
```

```
search the vector database for our Snowflake and dbt standards
```

**2. Wait a few seconds.** It loads the index and the embedding model on every
call, so there is a short pause before anything happens.

**3. Read the answer.** Every claim cites the note it came from, so you can
check it:

> The company responded to Kiwibank's Data Management and Integration RFI, covering
> Collibra for data governance…
>
> — `wiki/clients/kiwibank/kiwibank-data-management-and-integration-rfi-response-final-for-submission.md`

**4. Believe it when it says no.** "Not in the vault" means one of three things,
in order of likelihood: the note is new and hasn't been indexed yet, it is one of
the ~238 notes that are frontmatter with no body, or the vault genuinely doesn't
have it. Re-phrasing the question rarely helps — run an update first.

### When to use the normal route instead

For everyday questions, `index.md` → folder hub → grep is still the default and
is usually faster. Vector search earns its keep on questions where you can
describe the thing but not name it, or where you'd otherwise be guessing which
folder to open.

It only runs when you ask for it by name. It never runs automatically, and it is
never attached to a hook.

---

## Updating the search index

The index does not update itself. Run this after you've added or changed notes.

### How to update

**1. Open a terminal in the installer folder.** Its path is machine-specific, so it
isn't written down in this repo. If you set up with `scripts/setup_vault.py` it's
recorded in `_local/rag.path`; otherwise look for `rag/` beside the vault.

```bash
cd <the installer folder>
```

**2. Run the ingest:**

```bash
.venv/Scripts/python.exe ingest.py
```

Only what changed gets re-embedded. A normal day is well under a minute; a bulk
import of a few hundred notes takes about fifteen.

**3. Check it landed:**

```bash
.venv/Scripts/python.exe kb.py stats
```

`embedded` must equal `n`. If it doesn't, run `ingest.py` again — it embeds only
the gap.

### Example: you added three client notes this morning

```bash
cd "$(cat _local/rag.path)"     # or wherever your rag clone lives
.venv/Scripts/python.exe ingest.py
```

```
[obsidian] reading...
  obsidian[wiki]: 3240 note(s)
[obsidian] 40195 passages, 13 new or changed (7s)
[embed] vectorising new passages...
  embedded 13/13
[embed] 13 vectors written
```

Thirteen chunks, a few seconds. Now ask about them.

### Reading the output

| Line | Meaning |
|---|---|
| `pruned N row(s)` | Deleted or renamed notes cleaned up. Normal. |
| `REFUSED to prune N row(s)` | **Stop.** The run would delete more than a fifth of the index. Check every path in `config.json` is reachable before re-running with `--force-prune`. |
| `skipping prune — the connector returned nothing` | A source read nothing. Its notes were left alone. Fix the cause and re-run. |

### Never run `setup.py`

It asks *"Install automatic recall hooks for Claude Code and Codex?"* and
**defaults to yes**. Accepting writes a hook into your user-global Claude
settings that injects vault content into every prompt in every project on this
machine. The installer's own `INSTALL.md` tells you to run it. Don't.

To change settings, edit `config.json` in the installer folder directly.

### When a full rebuild is needed

Only if the embedding model or the chunking changes. Delete `kb.sqlite` and run
`ingest.py`. It takes about **100 minutes** for the current 40,182 chunks.

---

Full detail — every situation, every failure mode, how the retrieval thresholds
were set and why — is in
[`wiki/internal/rag/vault-rag-runbook.md`](wiki/internal/rag/vault-rag-runbook.md).
The design and the build record are in
[`wiki/internal/rag/vault-rag.md`](wiki/internal/rag/vault-rag.md).
