# Data notes

Findings from the development room that the resolver is built on. These are patterns in the SOP and the file layout, not memorised answers.

## What each file is for

Alerts carry the screened customer (`name`, `entity_type`, `dob`, `country`, `city`) plus at most one link: `account_ref`, `login_handle`, or `email`. Hits are the watchlist profiles. Customers are declared CRM facts. Accounts and onboarding are the bridges to KYC applicants. Approved KYC checks are the strongest legal name, date of birth, and document country. Notes are filed by email: some are identity checks, some say where the customer lived, most are ordinary support. Search results are keyed by the hit name's lowercase words in alphabetical order, and most of them are namesakes.

## How a customer is actually found

- One account can list several customer ids. The screened name and date of birth pick the holder. A shared phone alone does not.
- Records are the same person only when they share a phone and the same full date of birth, or the same document number on approved checks, transitively.
- With no link, a customer fits only when the screened name agrees and every supplied part of the date, country, and city agrees. A missing screened field is not a constraint.
- If more than one person still fits and they disagree, the decision is `REVIEW` / `AMBIGUOUS_CUSTOMER_RECORD` and `customer_record_id` is `AMBIGUOUS`. If they agree, that decision is used and the id is still `AMBIGUOUS`.

## Verified beats declared

The latest approved KYC check or identity note supplies the legal name, date of birth, and document country. A rejected or expired check is ignored. Declared CRM dates are often a different year from the passport. Using the CRM date would clear true matches. Identity notes are free text (provider, document, name in capitals, a date of birth, a country) and are not all worded the same way.

Residence notes add countries the person lived in ("lived", "resident", "home", "based in"). Those countries count. They are why some hits stay `REVIEW` instead of a location clearance.

## Dates and names

Numeric dates in this bank are day/month/year. A year alone can agree with a full date. A one-year gap is not a contradiction. The same year with a different month or day is. An age at a date in the first paragraph of a profile ("aged 45 in March 2019", "a 30-year-old" in November 1998) is two birth years, `year - age` and `year - age - 1`. Dated reports that can make someone too young are only lines of the form `According to …; September 10, 2025:`. Other wordings do not count. Companies use `dobs` only, as an incorporation date.

Names ignore case, accents, punctuation, and bracketed tags. Single letters are initials. Placeholders (`NA`, `TEST`, digits, and the like) are not parts. Parts match when they are identical, in the same `name_variants.json` group, joined or split, or within 1 edit for 4–6 letters and 2 edits for longer ones. Swapping two letters is two edits. Names agree when two parts match, or every part of the shorter name matches. Company legal forms are not parts. An individual whose name has fewer than two real parts is neither confirmed nor cleared on name.

## Hits, countries, and the cost of clearing

Hit countries are `countries`, `nationality`, `citizenship`, the last part of each address, and `place_of_birth`. `International` and `Europe` are not countries. Codes (`GB`, `US`) and demonyms (`Dutch`, `Bangladeshi`) are. Territories such as the Northern Mariana Islands stay their own country.

A search result is about the hit only when it uses the category phrase (`a politically exposed person`, `named in adverse media`, and the others in the SOP) and a country tied to the hit. It is used for a birth date only when `dobs` and the profile note do not already give one.

Clearing a true `SAME_ENTITY` or `REVIEW` costs 60. Other mistakes cost 2 or 3. Location does not clear a hit whose name and date of birth already agree; that hit is `REVIEW`. The practice set is small relative to the room and is mostly namesakes, so the engine clears only on an explicit contradiction.

## Evidence

The records that decided the practice hits, and not the accounts or applicants walked through to reach them, are the cited ids. On those 50 hits the engine's evidence set matches the label set. Customer record ids on a merged person are accepted as any record of that person.
