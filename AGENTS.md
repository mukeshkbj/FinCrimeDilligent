# Agent notes

Read `PRINCIPLES.md` before any spec, prompt, or code change. Those rules override convenience.

This repository is the Diligent Track 2 sanctions-screening identity resolver.

- A bad decision is worse than no decision. Clear a hit only on an explicit SOP contradiction. Confirm only on explicit agreement with nothing contradicting. Otherwise `REVIEW`.
- Every answer carries one reason code, the resolved `customer_record_id`, minimal cited evidence IDs, and a 2–4 sentence reason that uses this hit's own facts.
- Decisions and reason codes are deterministic across five runs. Jev (`typesafe/jev-router` on OpenRouter) may answer only a narrow typed sub-question the rules cannot settle, and only above the confidence threshold in PRINCIPLES.md (about 95%). If `OPENROUTER_API_KEY` is unset, `XAI_API_KEY` may serve the same typed JSON question and reason wording via Grok. No key, or any error, uses the deterministic rules. Cache model calls by input hash and do not commit `dev/` data or keys. Do not treat unlabeled sibling hits as answers.
- Do not commit `dev/` data, the workbook, or API keys.
- Run `system/run <data_dir> <output_file>`. Score practice labels with `python3 validate.py --data <data_dir> --output <output_file> --score <data_dir>/practice_labels.jsonl`.
