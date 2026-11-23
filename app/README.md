# Namesake analyst workbench

A local web app for the analysts who work what the engine leaves for a person.
The engine in `system/` still makes every automatic decision; this app runs it,
organises the result into a queue and records what people decide, without ever
changing the scored file.

```bash
app/run <data folder>            # then open http://127.0.0.1:8780/
# or, to open an existing output file without re-running the engine:
python3 app/server.py --data <data folder> --import-output output/dev.jsonl
```

Python 3 standard library only. Set your name in the sidebar ("Signed in as");
every action is signed with it.

## What an analyst can do

| Screen | What it is for |
|---|---|
| **Overview** | Alerts that need you, wait for approval, are escalated or cleared; where the hits went; engine quality on the practice labels; recent activity. |
| **Queue** | Alerts sorted by what needs a person. An alert closes only when every hit is a different person. Search by name, alert or hit id. Export the final decisions as CSV. |
| **Case** | One alert, every hit: the engine's decision and reason with clickable record ids, then four tabs: **Issues**, **Link graph**, **Evidence trail** and **Analyst memo**. |
| **Approvals** | Decisions made by one analyst and waiting for a second (maker-checker). |
| **Runs** | Screen a new data folder with `system/run`, watch progress, and switch between runs. |

### Issues and discrepancies

For every hit the app compares the customer's records, identity checks and the list profile, and lists what does not line up:

| Severity | Examples |
|---|---|
| **Blocker** (stops a safe clearance) | more than one person fits the alert · no customer found · the list profile has no date of birth · countries clash but name and date agree · nothing settles the hit |
| **Warning** | identity not verified (only rejected or expired checks) · date of birth on the record differs from the verified check · name on the record differs from the verified name |
| **Info** | records merged as one person · joint account · screened under a different name · rejected or expired check ignored |

Each issue shows the records involved and a suggested next step. An analyst marks it
**Info requested**, **Resolved** or **Risk accepted** (a note is required to resolve or
accept). **Draft information request** writes a request for everything still open on the
alert, labelled "Draft — not sent": Namesake never contacts anyone.

### Decisions and approval (maker-checker)

On a hit the rules could not settle, the analyst chooses **Clear · different person** or
**Escalate · same person** and writes a reason. On a hit the engine decided, the same panel
lets the analyst **challenge** it. Either way a **second analyst** must approve before it is
final; the person who decided cannot approve their own decision, and sending it back needs a
reason. Clearing with a blocking issue still open shows a warning.

Every action is appended to `app/runs/<run>/actions.jsonl` (git-ignored) and shown in the
case's **Audit trail** and on the Overview.

### Link graph

How the alert reaches the customer and the listed person: alert → account, login, email or
attribute search → customer records (joint holders, records merged on phone + date of birth
or document number) → identity checks and notes (rejected and expired ones shown but marked
not used) → decision ← list hit ← search results (namesakes marked). Records cited in the
decision are highlighted; click any box to open its raw record.

## How it fits the scored system

- `app/server.py` calls `system/engine.py` exactly as `system/run` does; a run on the dev
  folder writes a file byte-identical to `output/dev.jsonl`.
- It reuses the desk's `ui/serve.py` (records, practice metrics, Grok memo draft) and
  `ui/workflow.py` (evidence trail, memo).
- Grok, if a key is set, only rewords the analyst memo; facts it adds are rejected.
