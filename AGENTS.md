# Agent notes

Read `PRINCIPLES.md` before any spec, prompt, or code change. Those rules override convenience.

This repository is the Diligent Track 2 sanctions-screening identity resolver.

- A bad decision is worse than no decision. Clear a hit only on an explicit SOP contradiction. Confirm only on explicit agreement with nothing contradicting. Otherwise `REVIEW`.
- Every answer carries one reason code, the resolved `customer_record_id`, minimal cited evidence IDs, and a 2–4 sentence reason that uses this hit's own facts. **evidence = the records that decided the hit, never the hit itself.**
- Decisions are deterministic rules only; no model decides. Grok writes the reason wording, checked against the record. The same inputs must produce the same file across runs, including when API keys are set and when `PYTHONHASHSEED` changes. Do not commit `dev/` data or keys. Do not treat unlabeled sibling hits as answers.
- Do not commit `dev/` data, the workbook, or API keys.
- Run `system/run <data_dir> <output_file>`. Score practice labels with `python3 validate.py --data <data_dir> --output <output_file> --score <data_dir>/practice_labels.jsonl`. For holdout: `python3 dev/make_unseen.py dev holdout`, then `system/run holdout output/holdout_cases.jsonl`, then `python3 validate.py --data holdout --output output/holdout_cases.jsonl --score holdout/holdout_cases.jsonl`. Do not score `dev/holdout_cases.jsonl` against `--data dev` (those hits are not in the base room). Do not commit `holdout/`.
