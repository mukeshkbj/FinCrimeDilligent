# Data notes — Diligent Track 2 (dev set)

Mined from `/workspace/fincrime/screening` on 21 Nov 2026 (Europe/London). All counts computed from the JSONL files. Read with `PRINCIPLES.md` and `POLICY.md`. Do not memorise wording; the unseen set will phrase free text differently, but the dated-report form and listing phrases are the same.

## 1. Inventory

| File | Rows | Key | Notes |
|---|---:|---|---|
| `dev/alerts.jsonl` | 440 | `alert_id` unique | 395 Individual, 45 Company |
| `dev/hits.jsonl` | 819 | `hit_id` unique | Exactly the union of `alerts.hit_ids`. 702 Individual, 117 Company |
| `dev/customers.jsonl` | 72,265 | `record_id` unique | 64,746 Individual, 7,519 Company |
| `dev/accounts.jsonl` | 86,659 | `account_id` **not** unique | 86,607 distinct IDs; **52 joint accounts** have 2 rows / 2 holders |
| `dev/onboarding.jsonl` | 72,265 | `account_id`, `customer_id`, `kyc_applicant_id` each unique | One row per customer |
| `dev/kyc_checks.jsonl` | 54,488 | `check_id` unique | 49,574 applicants (4,914 have 2 checks) |
| `dev/notes.jsonl` | 31,895 | `note_id` unique | Filed by `requester_email` |
| `dev/search_results.jsonl` | 16,882 | `result_id` unique | 1,758 queries; 4 synthetic sources |
| `dev/practice_labels.jsonl` | 50 | `hit_id` | Answers + `path` + acceptable `reason_codes` / `customer_record_ids` |
| `dev/name_variants.json` | 55 groups, 30 legal forms | — | Spelling/nickname groups and company legal forms to drop |

`output.schema.json` and `validate.py` sit beside `dev/`. Alert `screened_at` runs **2026-11-01 to 2026-11-19**.

Hits per alert: 344 alerts have 1 hit; the rest have 2–15 (8 alerts have 15). Practice labels cover 50 hits in 46 alerts; those 46 alerts contain **170** hits, so **120 sibling hits are unlabeled**. Do not treat them as answers.

## 2. How the tables join

There is **no single customer key** on the alert. An alert carries at most one link, never two:

| Link on the alert | n | Resolves via | Coverage |
|---|---:|---|---|
| `account_ref` | 170 | `accounts.account_id` (all 170 found) | May be a **joint** account (2 holders) |
| `login_handle` | 70 | `accounts.login_handle` (all 70 found) | Login is unique to one account row; that account may still be joint |
| `email` | 54 | `customers.email` (all 54 found) and/or `notes.requester_email` (31 of 54 also have notes) | Emails are unique on customers (0 shared) |
| **no link** | **146** | Search `customers` by screened **name + DOB + country + city** (principle 2) | Every no-link alert has a screened DOB **and** country; 76 also have a city |

All 294 linked alerts resolve to at least one customer on the first hop. All 294 have either an approved KYC check or a note on a holder (204 have approved KYC, 188 have notes).

**Multi-hop path (same as the practice `path` field):**

1. Follow the alert link → one or more `CUS-*` (if joint, pick the holder whose name and DOB fit the screened customer).
2. Merge other records of the **same person**: same **phone + full date of birth**, or the same **document number on approved** KYC checks (and anything already linked to those). Phone or address alone is not enough (family).
3. From those customer records → their accounts → `onboarding.kyc_applicant_id` → latest **approved** `kyc_checks` row. Rejected and expired checks are not evidence.
4. Customer `email` → `notes`.
5. Hit names/aliases → `search_results.query` (see §4), only if the hit still has no DOB.

`customers.login_name` is **always empty**. Logins live only on `accounts.login_handle`.

**Joint accounts.** 52 accounts have two customer rows (always exactly 2). All 52 share a phone **and** an address; **none** share a DOB — they are family, not the same person. Example: `ACC-C4CA34` is `CUS-377745` Elvira Velasco MORILLO (1968-03-05) and `CUS-508976` Luca MORILLO (1940-12-19), same phone `+880 1766843099` and address in Oslo. **58 alerts** point at a joint account. Onboarding exists for exactly one of the two holders. The practice path says: *joint holders X and Y → the screened name and date of birth fit X*.

**Same-person merges (computed with proper date parsing):**

- 116 groups share a phone and a **full** DOB (232 records). Year-only DOB + phone must not merge.
- 7 approved document numbers are shared across two applicants (e.g. `N47010619` → `APP-F851F6` and `APP-B42775`).
- Union-find of both rules: **123 components of size 2 (246 records)**. No document-merge pair was already in a phone+DOB group.
- 164 phones are shared by more than one customer record; many are family (different DOB), e.g. Yusuf Ibrahim 1979-07-26 and Ahmad Ibrahim 2004-06-09 on `+44758092869`.

**Onboarding vs accounts.** Every onboarding `customer_id` is a holder of that `account_id`. Apparent mismatches only happen if you index accounts by `account_id` and keep one row: the other joint holder is in the second row.

**KYC reach.** 49,574 customers have at least one approved check; 22,691 customers have an onboarding row but **no** `kyc_checks` at all (look in notes). Every applicant who has any KYC check has exactly one approved check (4,914 also have a second, rejected or expired, check).

## 3. Hits — fields, DOBs, notes, listing types

**Entity / listing.** Individual 702, Company 117. Categories (a hit can have more than one; 61 have 2, 19 have 3): Adverse Media 324, PEP 301, Enforcement 180, Sanctions 68, Registration 23, Other Segment 15, SOE 7. `primary_category` is present on 474 hits and always equals the first category; on the other 345 use the first of `categories`. For search-result matching, the listing phrase follows primary (else first) category, per POLICY: Sanctions → "a sanctioned individual"; PEP → "a politically exposed person"; Enforcement → "the subject of enforcement action"; Adverse Media → "named in adverse media"; SOE → "a state-owned enterprise official"; anything else (Registration, Other Segment, …) → "named on a watchlist".

**Missing rates (selected).** `dobs` only 152/819 (**18.6%**). `profile_notes` 431 (52.6%). `aliases` 297. `countries` 474. `addresses` 681 (83%). `nationality` 108, `citizenship` 114, `place_of_birth` 62. `deceased_date` **4**. `life_status` Deceased **6** (two of them have no date). `best_matching_name` 474. `first_name`/`last_name` 357. `identifiers` 212 (strings like `TaxID: …`, `Passport: …`, `OFAC: …`, `National: …` — not used in the SOP for identity). `match_score` is 90–100 for every hit (already a screening candidate; it does not decide identity). Names: 365 use "Last, First" order, 454 do not.

**DOB formats in `dobs`.** 667 hits have an empty `dobs` list. Of the 152 with values: 105 are two years (`YYYY`+`YYYY`); **103 of those are consecutive year pairs** (age-at-date residue, e.g. `["1994","1995"]` on `H-91AC66`). Also: 25 single `YYYY-MM-DD`, 6 single year, 3 `YYYY-MM`, plus a few mixed lists (up to 6 values). For companies, only the `dobs` field is an incorporation date — do not mine notes for it.

**An empty `dobs` field does not mean the hit has no date of birth.** 8 of 12 practice `SAME_ENTITY` hits, and 24 of 28 `DIFFERENT_ENTITY` hits, have empty `dobs`. The SOP says: use `dobs`, else a sentence in the **first paragraph** of `profile_notes` (an age at a date gives **two** birth years: aged 45 in March 2019 → 1973 or 1974), else (only if still none) a **usable** search result.

Age-in-notes is rare but decisive. Hyphen-aware patterns (`a 30-year-old`, `aged 30`, `was 42 years old`, `when he reached the age of 38`) fire on **7** hits, all in the first paragraph, e.g.:

- `H-582410`: "November 1998 saw Elvira Velasco Morillo, a 30-year-old, face charges." → 1967 or 1968 (practice confirm).
- `H-D861DA`: "questioning of Michael Earl Tilley in January 2023, he was 46" → 1976 or 1977 (practice `DOB_MISMATCH` vs customer 1979-11-08).
- `H-4AA437`: "questioned Tomasz Paweł Drozd in January 2025, when he reached the age of 38" → 1986 or 1987 (practice mismatch vs 1995-12-17).

**Dated report lines** (for `TEMPORAL_IMPOSSIBILITY`) are exactly: `According to …; September 10, 2025: …` (English month name, day, comma, year, colon). **215** hits have at least one exact line (124 have 1, some have many, up to 28). **60** other hits say "According to" in a different form (e.g. `H-58A39C` "According to the Federal Bureau of Prisons, information as of December 13, 2017:") — **these do not count** as dated reports. Other wordings in the unseen set will also not count.

**Death.** 4 hits have `deceased_date` (`H-BD709E` 2022-03, `H-C85D81` 2021-08-02, `H-167095` 2023-02-14, `H-F51C73` 2022-03). All four dates fall before the alert’s `screened_at`, so they can support `DECEASED`. Two further hits are `life_status=Deceased` with **no date** (`H-A0E7C9`, `H-DCDB32`) — do not clear on `DECEASED` without a date. None of these 6 are in the practice 50.

**Countries tied to a hit.** Usable sources: `countries`, `nationality`, `citizenship`, last comma-segment of each `addresses` entry (strip a trailing `[Business]` / `[PEP]` / `[Associated]` / `[Headquarters]` / `[Residency]` tag), and last segment of `place_of_birth`. Drop "International" and "Europe" (14 hits mention them). After this parse, **732** hits have at least one usable country and **87** have none (all 87 have no geo fields at all). Traps: `nationality` is sometimes a place string (`Ribeirao Pires, Sao Paulo, Brazil` on `H-0181BD` — take the last part, Brazil); addresses can be just `"Nigeria"` or `"Denmark [PEP]"`; territories are their own country (`Northern Mariana Islands` on `H-58A39C`).

## 4. Search results

Structure: `result_id`, `query`, `title`, `snippet`, `source`. Sources are evenly split across `localpaper.example` (4,352), `newswire.example` (4,215), `people-directory.example` (4,165), `registry-news.example` (4,150). Every field is always present. Queries have 2–54 results each (typical 3–8).

**Most results are namesakes.** Link a result to a hit only when:

1. The query matches a hit name or alias after normalisation (lower-case, strip punctuation and `(…)` , treat comma-reversed "COSTA, MARCOS ROBERTO" as the same key as "marcos roberto costa"). With that, **614 / 819** hits have at least one result; 205 have none. 308 of 1,758 queries match a hit name; 1,537 queries match some customer name — the file also contains bank-side name searches, which the SOP does not tell you to use for the hit.
2. The title/snippet contains the **exact listing phrase** for the hit’s category (see §3) **and** a country tied to the hit. **6,679** results contain one of the six policy phrases (roughly 1,050–1,150 each). Only **59 hits** have at least one result that has **both** the right phrase and a hit country — that is the usable set.

Example of a correctly used result: `SR-590704` for `H-0181BD` — "May 2019 news reports profiled 33 year old MARCOS ROBERTO COSTA, who is a politically exposed person in Brazil." Phrase + country, and the age gives 1985 or 1986. Similarly `SR-01BFC3` (`H-80B4B5`, Jérôme Kerviel, 33 in February 2010 → 1976 or 1977), `SR-AE2CE1` (`H-F9DBF9`, Giampiero Fiorani, 52 in June 2012 → 1959 or 1960), `SR-A88751` / `SR-65C752` (practice `DOB_MISMATCH` from search ages).

Do not pull a DOB from search if `dobs` or profile notes already give one.

## 5. KYC checks

`result`: **approved 49,574**, expired 2,433, rejected 2,481. Use only the latest **approved** check of the person. Providers: Sumsub 11,710, Veriff 11,589, Persona 11,530, Onfido 11,430, plus **Companies registry lookup 8,229** (all `document_type=registry extract`, all companies). Individual document types: national ID 15,557, driving licence 15,377, passport 15,325. `document_country` is always a country name, never an ISO code. `document_number` is missing on all 8,229 registry extracts.

**Verified vs declared (latest approved check, 49,574 pairs, dates parsed as day-month-year):**

- **DOB:** 29,708 differ only in format (`September 26, 1979` vs `26/09/1979`); **0 real date disagreements**. Parsing `DD/MM/YYYY` (and swapping only if the month is >12) is the right convention — if you parse `05/03/1968` as March vs May you will break `H-582410`.
- **Name:** 9,987 token-set differences, of which **9,930** are just an extra/missing middle name (`Rachel Harris` vs `Rachel David Harris`). **17** look like typos in the verified name (`Dejan Jovanović` vs `DEJAN JOVANOIVĆ` on `KYC-47B39A`; `ISABEL FERNÁDNEZ`; `ABUBKAAR`; `MOHAMAMD NADEEM` on `KYC-8DE62A`; `SULEIAMN UMAR` on `KYC-E7150E`; `TIJJANI ABDLULAHI` on `KYC-16E55D`; `JUAN GOZNÁLEZ` on `KYC-3B906A`; `MILAN SETFANOVIĆ` in `NOTE-2A1C15`). **40** have a completely different first name and the same surname (`Mason Davis` vs `Amanda Davis` on `KYC-9D259B`; `CHINEDU AZEEZ` vs screened RIDWAN; `SARAH JOHNSON` vs screened JACOB). The last group is exactly what `NAME_MISMATCH_VERIFIED` is for: the verified legal name outranks the screened / CRM name.

Verified names therefore must be compared with principle-8 matching (variants + edit distance), not exact string equality — they are often ALL CAPS and sometimes typo'd, but they are still the legal name.

## 6. Notes

31,895 notes; 29,645 distinct emails, **all** of which exist on a customer. Channel: `kyc` 22,575, `phone` 5,091, `app` 2,146, `email` 2,083. Most emails have 1 note; 2,228 have 2; 11 have 3.

**What they contain:**

- **Onboarding / identity write-ups** (the bulk of `kyc` notes): provider, verified legal name, DOB, document type and issuing country. These **count as verified evidence** when there is no `kyc_checks` row, or as a cross-check. Practice uses notes as the verified source on e.g. `H-582410` (`NOTE-14E25A`), `H-80B4B5` (`NOTE-23FC8E` — and the CRM DOB is wrong, see §9), `H-5E39F0`, `H-EDBB79`, `H-D9BBCC`.
- **Places lived** — **881** notes with resided / lived / relocated wording, often on `email`/`phone` channels. These add countries to the customer for `LOCATION_MISMATCH`. Examples: `NOTE-7F183D` "living and working in India between 2013 and 2014" (`H-427D39`); `NOTE-F302A4` "home and a job in Nigeria throughout 2018 to 2019" (`H-A22C42`); `NOTE-F1D4BE` residency in Denmark 2016–2018 (`H-7F2A6C`).
- **No genuine name-change notes** were found (hits on "aka" / "nee" were false positives on names like AMAKA and RENEE). **No deceased notes.**

Note DOBs use the same mixed formats, including `05/03/1968` meaning 5 March 1968.

## 7. Practice labels (50) — decisions, paths, reason-code signals

Distribution: **`DIFFERENT_ENTITY` 28, `SAME_ENTITY` 12, `REVIEW` 10**. This slice is richer than "most hits are routine" would suggest; still, 56% are clears and no `SAME_ENTITY` is a close call once verified facts are gathered. Reason-code *mentions* (a hit may allow more than one code):

| Code | n | Decision |
|---|---:|---|
| `LOCATION_MISMATCH` | 18 | DIFFERENT_ENTITY (15 sole, 2 with name mismatch, 1 with temporal) |
| `INSUFFICIENT_DATA` | 10 | REVIEW (all 10) |
| `NAME_DOB_LOCATION_MATCH` + `NAME_DOB_MATCH` | 8 | SAME_ENTITY (both codes accepted) |
| `DOB_MISMATCH` | 7 | DIFFERENT_ENTITY (5 sole, 2 with name mismatch) |
| `NAME_MISMATCH_VERIFIED` | 7 | DIFFERENT_ENTITY (3 sole, plus the 4 combos above) |
| `NAME_LOCATION_MATCH` | 4 | SAME_ENTITY, **companies only** |
| `TEMPORAL_IMPOSSIBILITY` | 1 | DIFFERENT_ENTITY (with location) |

**Never seen in the 50, but required by the SOP and present in dev:** `ENTITY_TYPE_MISMATCH` (1 hit in the 819: `H-5EEC5A` / `A-41F2A9`, screened company `Stadtwerke München GmbH` vs hit individual `Mun Chen`, Singapore), `DECEASED` (4 dated deaths), `AMBIGUOUS_CUSTOMER_RECORD` (the two ambiguous practice cases still got `INSUFFICIENT_DATA` because every person led to the same decision).

`customer_record_ids`: 13 hits accept **more than one** `CUS-*` (same person, merged); 2 are `AMBIGUOUS` (`H-6C7985`, `H-CDEC83`); none are missing. Evidence prefixes: CUS 49, KYC 32, NOTE 21, SR 5. Paths used: KYC 32, notes 21, no-link customer search 12, same-person merge 13, joint account 8, search results 5, multi-person 2, login 11, account_ref (non-joint) 14, email link 5.

**Concrete trigger for each reason code** (from the 50, plus the rare SOP cases in dev):

- **`NAME_DOB_LOCATION_MATCH` / `NAME_DOB_MATCH`** — Person: verified (or CRM if no verified) name agrees with a hit name/alias, and the customer DOB agrees with a hit birth year/date (including a two-year age window), and nothing contradicts. If a customer country also overlaps a hit country, both codes are accepted. The hit DOB often comes from notes or search, not `dobs`. Examples: `H-582410` (age in notes → 1967 or 1968; joint account; `NOTE-14E25A`); `H-0181BD` (merge two records; `SR-590704` age); `H-91AC66` (structured `dobs` `1994,1995`); `H-80B4B5` (verified DOB 1977-01-11 in a note **overrides** CRM DOB 1969-05-05; search age 1976 or 1977); `H-4D76E3` (verified note DOB 1968-02-17 **overrides** CRM `02/12/1963`; agrees with hit `1968-02`); `H-F9DBF9` (Giampiero / Giampiero Fiorani, search age).
- **`NAME_LOCATION_MATCH`** — Companies only: name agrees (legal forms dropped) and a country agrees, nothing contradicts. `H-02115F` Pescanova S.A. / "Pescanova, Sociedad Anónima", Spain, via login `pescanov2115` + `KYC-997803`. Also `H-84548F`, `H-24D490`, `H-D8119F`.
- **`DOB_MISMATCH`** — Every birth date the hit gives (field, notes age, or usable search age) is contradicted: customer year more than 1 year outside, or same year but month/day differs. One agreeing date blocks this. Examples: `H-D861DA` notes age 1976/77 vs 1979-11-08; `H-622EDD` search age 1972/73 vs 1979-04-17; `H-4AA437` notes age 1986/87 vs 1995-12-17; `H-58A39C` listed `1962-09-10` vs 1965-03-28 (gap >1 year); `H-CF5228` listed `1980-11-11` vs 1951-09-17.
- **`LOCATION_MISMATCH`** — Every customer country (residence, nationality, approved document country, places lived in notes) differs from every hit country. **Do not use this if name and DOB agree — that is REVIEW.** In all 18 practice location-clears the hit had **empty `dobs` and no extracted DOB**, so the name+DOB-agree trap did not arise. Countries must be normalised (see §8). Example: `H-CF173B` customer Peru/United States vs hit United Kingdom.
- **`NAME_MISMATCH_VERIFIED`** — The **verified** legal name (KYC or onboarding note) agrees with none of the hit's names/aliases under principle 8. The screened/CRM name often *does* look like the hit — ignore it. Examples: `H-2808BE` screened RIDWAN AZEEZ vs verified `CHINEDU AZEEZ`; `H-380854` screened JACOB JOHNSON vs `SARAH JOHNSON`; `H-EDBB79` screened MD. SAEDUL ISLAM vs `TASLIMA RAHIM ISLAM`; `H-FC22E2` screened diego gallardo vs `Joseph gallardo` (also DOB mismatch); `H-5E39F0` screened Amable Diaz vs `SAMUEL DIAZ`. Close-but-not-enough: `H-D9BBCC` verified `MARKUS GERHARD MUELLER` vs hit `Mark Mueller` — `mark` and `markus` are **different** variant groups, and "Mark" (4 letters) allows only 1 edit.
- **`TEMPORAL_IMPOSSIBILITY`** — Customer was under 16 at the earliest **exact** dated-report line, or a company was incorporated after it. Only example: `H-13E1CF`, customer born 2007-08-21 (`KYC-358C76`), report "According to the thenews.com.pk; January 08, 2020:" → at most 13. Also a location mismatch (Singapore/US vs Pakistan).
- **`ENTITY_TYPE_MISMATCH`** — One is a person, the other a company. Only dev example: `H-5EEC5A`. Not in the 50. First-hop customer type always matched the screened type in this set (0 disagreements).
- **`DECEASED`** — Hit profile gives a date of death before `screened_at`. Four dated cases in dev, none in the 50.
- **`INSUFFICIENT_DATA`** — Name agrees, no contradiction, and you cannot confirm (usually: no comparable hit DOB for a person; or company missing country). All 10 practice reviews match this, including both ambiguous-customer alerts, because every candidate person led to the same review. Typical reason text: "Nothing in the customer's records contradicts the hit, and the date of birth cannot be compared with it." Examples: `H-404FB7` Suleiman Umar, Nigeria, no hit DOB; `H-427D39` Rajesh Kumar / `राजेश कुमार`, India, no hit DOB; `H-A22C42` AbdulBasit Abdullahi YAHAYA, Nigeria, no hit DOB.
- **`AMBIGUOUS_CUSTOMER_RECORD`** — More than one *person* fits the alert **and they would get different decisions**. Use `customer_record_id=AMBIGUOUS`. The two practice multi-person cases (`H-CDEC83` three Juan González born 1989 in/around Panama; `H-6C7985` two Mohammad Nadeem born 1990 in Pakistan with different full DOBs 5 April vs 18 May) agreed on REVIEW, so the code is `INSUFFICIENT_DATA` but the record id is still `AMBIGUOUS`. Cite all candidate `CUS-*`.

## 8. Traps and edge cases

- **Placeholders are not name parts:** `NA`, `N/A`, `TEST`, `UNKNOWN`, `XXX`, `NONE`, digits. **179** individual customers have fewer than two real parts after dropping these (`Paweł N/a N/a` `CUS-537602`, `Martin Xxx Xxx` `CUS-757068`, `Sani 0000 0000` `CUS-895644`, `0000 Barajas` `CUS-010344`). Those individuals can be neither confirmed nor cleared on name. **33** hits have digit/placeholder parts (including CCC numeric aliases). `"na"` is also a **company legal form** (National Association): `TD Bank, N.A.` is a company name, not a placeholder-only name.
- **Company legal forms** (drop as name parts): `ab, ag, as, asa, bv, co, company, corp, corporation, gmbh, inc, kg, limited, llc, llp, lp, ltd, na, nv, oy, oyj, plc, sa, sarl, sas, se, sf, sl, spa, srl`. Also expand obvious equivalents not always in the list (`Sociedad Anónima` ≈ `S.A.` on `H-02115F`). 78 hits and 7,359 customers have a listed form in the name.
- **Initials:** a single letter is an initial, not a part (`Carl E. Andersen` `H-7F2A6C`). 32 hits and 17 customers have initials.
- **Transliterations and scripts:** use `name_variants.json` (55 groups: Mohammed/Muhammad/Mohd, Thomas/Tomasz, Aleksandr/Alexander, etc.). `Md` is not in the Mohammed group (`mohd` is). `john` does not include `jonathan`. `mark`/`marc`/`marco` is a **separate** group from `markus`/`marcus`/`marcos`. Aliases may be non-Latin, e.g. `राजेश कुमार (None, Devanagari)` on `H-427D39`.
- **Edit distance:** 1 edit for parts of 4–6 letters, 2 for longer, 0 for shorter than 4; swap is two edits. Apply this to typo'd verified names too.
- **±1 year DOBs agree.** Consecutive year-pairs are the common form (103 hits). A full customer date can agree with a year-only or a two-year window (`1994-11-01` agrees with `1994, 1995`). A gap of more than one year is a mismatch (`1965-03-28` vs `1962-09-10`).
- **Age gives two birth years.** Always keep both. Confirm if the customer year is either; mismatch only if it is more than 1 year outside both.
- **Country clash + name and DOB agree → REVIEW, not `LOCATION_MISMATCH`.** Not illustrated in the 50 (all location clears had no hit DOB). Must still implement it. Normalise adjectives (`Nigerian`, `Bangladeshi`, `American`, `British`, `Spanish`, `Italian`) and ISO-2 residence codes (`NG`, `US`, `GB`, `ES`, `BR`, `PE`, `IN`, `RO`, …) to countries. Customer nationality is stored as a name or adjective, never ISO-2; residence is mixed (21,596 ISO-2, 50,669 names).
- **Ambiguous customers** on no-link search: a year-only screened DOB plus a common name and country can match more than one person. `H-CDEC83` (Juan González, screened DOB 1989, Panama) hits three records that are **two people**: `CUS-565167` and `CUS-892985` share phone `+880 1773016546` and full DOB 1989-11-04 (merge them; residences Panama vs Sweden still both belong to that person), and `CUS-037213` is a different person (1989-12-06, different phone). The path says "2 different people fit". `H-6C7985` is two Mohammad Nadeem records in Pakistan with different full DOBs (5 April 1990 vs 18 May 1990) and different phones — not a merge. Sharing a name and a birth *year* is not a merge; merge needs phone+full DOB or an approved document number.
- **Joint accounts vs merges.** Joint holders are different people (different DOB). Merged records are the same person (same full DOB+phone or same approved document). Do not mix the rules.
- **Verified DOB/name can disagree with the CRM record.** Always prefer the latest approved check or KYC note. See `H-80B4B5` and `H-4D76E3`. Using the CRM DOB would have falsely mismatched a true match.
- **`DD/MM/YYYY` not `MM/DD/YYYY`**, except when the first number is >12.
- **Dated-report parser must be strict** (exact punctuation). Loose "According to … as of …" lines are not temporal evidence.
- **Comma names and "Md Al" short parts.** Short parts (<4) must match exactly. Reorder "Last, First".
- **One type-mismatch in 819**, zero in the 50 — still handle it; the unseen set may have more.
- **Practice is not the score set.** 120 unlabeled hits sit in the same alerts as the 50. The 50 over-represent interesting cases.

## 9. Useful (legitimate) signals for accuracy

1. **Build the customer picture in the SOP order, then compare.** Almost every practice error-mode is "used the screened/CRM name or DOB instead of the verified one" or "forgot a hop" (joint holder, merge, note, search).
2. **Extract hit DOBs; do not trust the `dobs` field alone.** Empty on 81% of hits. Notes ages and the 59 usable search results are high-value. This is how most practice confirms and several DOB mismatches were decided.
3. **Default `REVIEW` unless a contradiction or a full confirm rule fires.** All 10 practice reviews are "name agrees, countries overlap or don't contradict, no hit DOB". That pattern will be common in the 667 hits with no structured DOB (only a minority will have an extractable age).
4. **Country normalisation and address-tail parsing** unlock `LOCATION_MISMATCH` and company `NAME_LOCATION_MATCH`. 732 hits have a usable country once addresses are parsed; only 474 have `countries` filled.
5. **Lived-in notes (881)** add customer countries that CRM residence may miss, and are cited in practice (`NOTE-7F183D`, `NOTE-F302A4`, `NOTE-F1D4BE`).
6. **Determinism:** no randomness in the data. Decisions are deterministic rules only; no model decides. Grok writes the reason wording, checked against the record. Reproducibility is part of the official score.
7. **Cite minimally:** only the records that decided it (a CUS and the KYC or NOTE that supplied the verified fact; an SR only when it supplied the hit DOB). Practice evidence is small.

## 10. Signals that should force REVIEW

- No contradiction, and (for a person) no comparable hit DOB, even if name and country agree.
- Name and DOB agree but every country disagrees.
- More than one *person* fits the alert and their decisions diverge (`AMBIGUOUS_CUSTOMER_RECORD`); if they coincide, give that decision but still set `customer_record_id=AMBIGUOUS`.
- Individual customer has fewer than two real name parts — cannot confirm or clear on name; only confirm/clear if some other SOP rule independently settles it (and if not, REVIEW).
- Hit `life_status=Deceased` but no `deceased_date`.
- "According to" text that is not the exact dated-report form — do not use it for `TEMPORAL_IMPOSSIBILITY`.
- Search results that lack the exact listing phrase or a hit country — ignore (namesakes).
- Rejected/expired KYC — ignore.
- Year-only or month-only dates: missing parts are not a mismatch; do not invent a day.
- If two plausible parsed dates or two plausible customer resolutions would change the decision, REVIEW.


## Engine alignment

`system/engine.py` follows the patterns in this note. It does not read `practice_labels.jsonl`, and it does not treat the 120 unlabeled sibling hits as answers.

- The latest approved KYC check or identity note supplies the legal name, date of birth, and document country. The CRM value is used only when no approved check has that field. That is what keeps `H-80B4B5` and `H-4D76E3` from being cleared on the declared date.
- Hit dates come from `dobs`, then an age in the first paragraph (both birth years), then a search result. The query is the hit name or an alias, sorted and lower-cased. A result counts only when it contains the exact listing phrase and a country tied to the hit.
- Location clears only when the name and date of birth do not already agree. If they agree and the countries do not, the hit is `REVIEW`.
- Temporal impossibility uses only `According to …; Month D, YYYY:` lines. A `life_status` of Deceased with no `deceased_date` does not clear, and it blocks a confirmation.
- An individual with fewer than two real name parts is not confirmed or cleared on name. Verified names, including typo'd ALL-CAPS names, are compared with principle 8.
- Two people who would get different decisions are `AMBIGUOUS_CUSTOMER_RECORD`. Two people who agree keep that decision, and `customer_record_id` is still `AMBIGUOUS`.
- Section 10 is the review gate: no comparable date, a country clash that name and date already answer, an undated death, a rejected check, a namesake search result, and a partial date are not turned into a clearance.

The 50 practice labels are a check that these rules fire. They are not a lookup table.
