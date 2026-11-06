# Fuel Subsidy Claims Platform — RURA · RRA · MINECOFIN · MININFRA (trial)

Checks an OMC subsidy claim against an EBM extract and produces the
taskforce summary plus accepted, rejected (with reasons) and review lists.

## Run it (Mac, Anaconda or any Python 3.10+)

```bash
cd fuel_subsidy
pip install -r requirements.txt
streamlit run app.py          # opens http://localhost:8501
```

## Accounts and roles

| Role | Sees | Trial account |
|---|---|---|
| **Administrator (super user)** | everything + **Admin** (users, access, signatories, official subsidy, prices, round numbering, form policy, audit log) | `admin` / `admin2026` |
| RRA officer (analyst) | Submission, Processing, Approval (create rounds), Reports, Insights, Appeal (analyse, verify) | `officer` / `rra2026` |
| Taskforce member | Approval (approve each round = electronic signature), Reports, Insights | `beatha.mukangabo`, `eric.mutabazi`, … / `Change@2026` |
| Final approver | Approval (final approval), Appeal (approve verified appeals), Reports, Insights | `evariste.rugigana` / `Change@2026` |
| Finance officer | Payment, Reports, Insights | created by the admin |
| Fuel supplier (OMC) | Submission, Appeal | TIN, e.g. `100007664` / `omc2026` |
| **Data Scientist** (function) | Home, Appeal (cases assigned to him/her: re-match with EBM, check the VAT declaration annex, verify), Analysis, Reporting (incl. data extraction), Insights | created by the admin with the function *Data Scientist* |
| Manager | sees every stage (submission → processing → taskforce approval → payment → appeal, reports, insights); approves and deletes nothing | created by the admin |
| Senior manager | same as Manager **+ can add users** (Admin › Users) | created by the admin |

* Everyone has **My account › Change password**.
* Signatory accounts are created from their names in one uniform form — `given.family`
  (`MUKANGABO Beatha` → `beatha.mukangabo`) — with a default password (`Change@2026`, set in Admin) that
  **must be changed at the first sign-in**. The admin can add more from a list of names (Admin › Signatories).
* An account created or reset by the admin also has to change its password at the next sign-in.
* **Functions** (Admin › Functions): roles the administrator defines — a name, the heads it opens and the built-in
  role whose permissions it uses there ("acts as"). *Data Scientist* is ready: it acts as an RRA officer but only in
  Home, Appeal, Analysis, Reporting and Insights. Give a function to an account like a role.
* **Deleting an account** (admin): the account's details are archived first (Admin › Deleted records) and its claims,
  signatures, appeals and audit entries are kept. To stop access only, untick *Active*.
* **Deleting a submitted file**: the RRA officer can delete a claim before analysis (Submitted / Returned); the
  administrator at any stage (also removes it from its round, payments and appeals). A reason is required and a full
  copy (claim file, letter, lines, payments, appeals) is archived in Admin › Deleted records.

## Standard forms

* **Claim form** (*Submission of request › Download the claim form*): 16 fixed columns —
  `# · Site-name · OMC TIN · Client-name · Closed at · Vehicle ID · Card Number · Product · Quantity · P.U ·
  Amount · subsidy rate · subsidy Amount · Net To be Payed · Served-by · EBM Slip No`; supplier name and TIN
  in the header, period in cell A4.
  * **OMC TIN** = the fuel supplier's own TIN (9 digits) on every line. Before submission a missing TIN, or a TIN
    different from the supplier's account, is a warning; the EBM seller TIN of each invoice must be the claimant (R7).
    Client-name identifies the transport operator.
  * `Closed at` as real date cells, product dropdown (AGO/PMS), number checks, EBM Slip No check, Amount /
    subsidy / net calculated automatically, instructions sheet.
* **Appeal form** (*Appeal › Download appeal form*): prefilled with the selected rejected lines; the supplier
  fills the corrected EBM Slip No / quantity and an explanation.

## Flow

1. **Submission** (supplier): official claim form, **signed request letter** (PDF/image) and the **amount of subsidies
   requested** (RWF) are all required; other files are rejected; checks before confirming —
   dates outside the interval, subsidy rate different from the official rate, price different from the RURA
   price, duplicate slips; the supplier ticks *I confirm* and submits.
2. **Processing** (RRA officer): only the EBM file is uploaded; supplier, TIN, interval and account are filled
   automatically in direct mode; the official subsidy and prices come from the system. *Save as verified*.
   **Amount to reimburse = the lower of the subsidies requested and the subsidies calculated** (potential = accepted
   lines × official rate). Both are shown, and the round report has *Subsidies claimed* (requested), *Subsidies
   calculated* and *Amount to reimburse*. Appeal awards never take the total above the amount requested.
3. **Approval**: the officer consolidates verified claims into a round numbered by the system
   (*15th submission (November 2026)*); every taskforce member chooses **I approve and sign** or **I reject and sign** (reason required),
   with their name shown as the signature; then the final approver signs the same way. The round report carries
   "Approved and signed electronically by <name> on …" for each signatory.
   **Pending lines** (Processing › *Pending lines*): the analyst re-routes each pending line to **Accept** or
   **Reject** (reason required), one by one or all at once, in any analysed claim. Totals are recalculated; on an
   approved claim the extra amount goes to Finance as a separate *Pending review* payment. Not possible while the
   claim's round is being signed (signed figures do not change).
4. **Payment** (finance): each amount is a **first submission** or an **appeal award**; tick paid with reference;
   rejected amounts after approval are listed with their reasons.
   **Appeal review by a Data Scientist**: an officer assigns each appeal case (*Assign*); the person sees it on Home
   and under *Assigned to me*. Step 1 re-matches the appealed lines with EBM; step 2 checks the **VAT declaration
   annex** from e-Tax (same format as the EBM file — what was declared vs what the machines recorded): by receipt
   (SdcId + SdcReceiptTypeCounter), else buyer TIN + date + amount — automatically by uploading the annex, or by
   hand in the verification table. *As the analysis suggests* upholds only lines found in EBM **and** declared.
5. **Tracking** (supplier): Home › *Where are my files?* shows every claim with its stage and a progress bar;
   Submission › *My requests and status* › *Track a file* shows the stage (Submission → System verification → RRA Staff verification →
   Taskforce signatures k of 8 → Final approval → Paid), what happens next, the amounts (requested, calculated,
   to reimburse, paid), accepted / pending / rejected lines, appeals and a plain-language history.
6. **Appeal**: submitted → analysed with EBM → verified by RRA (proposed litres) → approved → paid.
7. **Insights**: overall; one fuel supplier against its peers; comparison of suppliers with a similar number of
   vehicles and litres; transport agencies against each other; KPI scorecard (compliance, consumption,
   abnormality, efficiency) with 🔴/🟠/🟢 flags against the peer median.

## Analysis and Reporting

* **Analysis** (formerly *Reports*): reimbursement report for signature per round, accepted / rejected details,
  claim analysis reports, appeals, audit log — RRA staff, taskforce, approver, finance, managers.
* **Reporting** — every account, each seeing only the reports of its role (a fuel supplier only its own TIN):

| Group | Report | Who |
|---|---|---|
| Claims and payments | Claims statement · Payment statement · Rejected lines and reasons · Appeals status | everyone |
| Finance | Payment schedule (to pay) | staff, finance, final approver |
| Approval | Submission rounds and signatures | staff, finance, taskforce, final approver |
| Management | Monthly summary · Supplier compliance · Rejections by rule · Processing time | staff (+ taskforce / approver / finance as relevant) |
| Risk | Vehicles above 400 L a day · Pending lines awaiting decision | staff (+ taskforce / approver) |

  Filters: period and fuel supplier; downloads in Excel (with a cover sheet: who, when, period) and CSV.
  "Staff" = RRA officer, administrator, manager, senior manager.
* **Reporting › Taskforce batch report** — the analyses of the *Fuel Subsidy Reimbursement Claims* deck, produced
  from the data (batches 1–15 loaded as history + every submission round of the platform, numbered from B16):
  scheme overview · claimed vs reimbursable by batch (chart, payout %) · results by OMC (low acceptance flagged) ·
  batches per OMC with coverage dates (overlaps *) · points to check (overlapping periods, gaps, rate per litre,
  low acceptance, no vehicles, round figures, catch-up claims) · OMC profile · **download the whole report as
  PowerPoint**. Filter by batch range. A fuel supplier sees only its own OMC profile.
  Batch history: Admin › Batch history (view, download, add or replace).
* **Reporting › Data extraction** — RRA officers / analysts and the administrator only (see below).
* **Admin › Backup** — full database backup, administrator only.

## Data extraction (Reporting › Data extraction)

* **Ready-made extracts**: all claims with amounts, all claim lines, rejected lines with reasons, totals per supplier,
  totals per round, payments, litres per vehicle per day, rejections by rule, taskforce signatures, appeals, audit
  log, accounts — each shown, with its SQL, and downloadable as Excel or CSV.
* **Your own SQL** (SELECT / WITH only): runs on an in-memory copy, so it cannot change anything. Tables: `claims`,
  `claim_lines` (the lines of every analysed claim), `payables`, `rounds`, `signatures`, `appeals`, `events`,
  `users` (no passwords), `deleted_claims`, `deleted_users`, `claim_keys`.
* **Everything**: all tables in one Excel workbook. The full database backup (`.db`) is in Admin › Backup — on
  Streamlit Community Cloud the database can be reset when the app restarts, so download a backup regularly.

## Home page pictures

The Home page opens with a sliding banner — *Fuel Subsidies Command Post* for staff, with the four institutions
RURA · RRA · MINECOFIN · MININFRA — of eight slides: RURA, RRA, MINECOFIN, MININFRA, Nyabugogo bus park, a Kigali
boulevard, a road through the tea hills with a bus, and reimbursement (clouds, sunlit sky, green hills). They are original illustrations made for the platform. **Admin › Home pictures** replaces any slide with a real photo (for
example the RRA and RURA buildings — use photos RRA owns or may use) and edits its title and caption; photos are
resized automatically. *Back to the illustration* restores the drawing.

## Heads and who sees them

| Head | Supplier (requester) | Officer |
|---|---|---|
| Home | ✓ own figures | ✓ all figures, accounts |
| Submission of request | ✓ upload, declare interval, follow status | ✓ all requests |
| Processing · Claim analysis | | ✓ EBM matching, rules, review decisions, approve / return |
| Payment | | ✓ tick paid with amount, date, reference; undo with reason |
| Reports | | ✓ report for signature per submission round, accepted / rejected details, appeals, audit log |
| Insights | | ✓ trends, status, by supplier and agency, litres per vehicle per day |
| Appeal | ✓ contest rejected lines with evidence, follow decision | ✓ decide line by line |

Stage switching is enforced in one place (`engine/register.py`, `TRANSITIONS`):
SUBMITTED → PROCESSED → APPROVED → PARTLY PAID / PAID; RETURNED from the
first stages. An upheld appeal adds its amount to the claim (a paid claim goes
back to PARTLY PAID until the extra is paid). Every action is in the audit log.
Data is kept in `claims.db` (SQLite) for the trial.

Command-line processing still works: see `run_claim.py --help`.

## Files you give it

| File | Needed | Columns |
|---|---|---|
| Claim from OMC | yes | the supplier format (#, Site-name … EBM Slip No). Title rows, totals and signature rows are skipped automatically. Column names are matched loosely (case, spaces, "Net To be Payed"/"Net to be paid"…). |
| EBM extract | yes | TIN, ClientsTIN, SdcId, **SdcReceiptTypeCounter** (or invoice_number), SdcDateTime, InvoiceType, ItemName, ItemUnitPrice, ItemQuantity, ItemTotalPrice, TaxType, MatchInvoiceAmount … Extra columns (WasReported, HasSignature, …) are ignored. Key = SdcId + SdcReceiptTypeCounter with spaces removed, compared with the cleaned EBM Slip No. See `sample_data/ebm_extract_real_layout.csv`. |
| RURA prices | built in | `reference/rwanda_fuel_pump_prices_nov_2026.xlsx` (ASSIMPER: Diesel 2,927, Petrol 2,938, Mogas 3,200 RWF/L, LPG 1,260 RWF/kg) is used automatically. Officers can view or replace it in Processing › Rules and RURA prices. Accepts `product, effective_from, price` or `Fuel product, Retail pump price, Unit, Price date/source update, Source, Source URL`. Undated rows apply to any date; if only a later-dated price exists it is used and the report says so. |
| Earlier paid lines | optional | any file with an "EBM Slip No" or "EBM invoice matched" column; catches invoices claimed in a previous submission. |

## Consumption interval (required)

The supplier must declare the period of consumption (from–to). It is taken
from the dates entered at submission, or read from a title row of the claim
file: `Period: 21/09/2026 - 30/09/2026`, `21 - 30 Sept 2026`,
`28 Sept - 04 Oct 2026`, `29 June - 30 Sept`, `du 01 octobre au 15 octobre 2026`.
Without an interval the claim is not processed. If the file and the entered
dates disagree, the entered dates are used and the difference is reported.
The Summary sheet shows an **Interval check**: declared interval, range of
Closed at dates, range of matched EBM invoice dates, and how many lines fall
outside.

## Cleaning (so lines are not rejected for how they were typed)

* **EBM Slip No → `SdcId|invoice`**. Accepts `SDC010057290/10540`,
  `sdc010057290 - 010540`, `SDC 010 057 290 / 10540`, `SDCO10057290/10541`
  (letter O), `SDC01005729010540` (glued), `010057290/10540` (no prefix),
  `10540/SDC010057290` (reversed), `…_10540 NS` (suffix). Leading zeros of the
  invoice are dropped on both sides. EBM's `SdcId` + `invoice_number` are
  harmonised the same way.
* **Numbers**: `2,927.00`, `2.927` (price → 2927), `230,443`, `1.234.567`,
  `78,73` (decimal comma), `RWF 1 200`, `(500)`, Excel floats.
* **Dates — dd/mm/yyyy or mm/dd/yyyy**: the format is decided for the whole
  file from dates that can only be read one way (`13/06/2026` is day-first,
  `06/13/2026` is month-first). If every date is ambiguous, the reading that
  puts the dates inside the declared interval wins. A single date outside the
  interval whose other reading is inside is switched; Excel date cells stored
  with day and month swapped are repaired the same way. US times (`6/7/2026
  12:14 AM`), ISO and Excel serial dates are read too. Everything is shown as
  **dd/mm/yyyy**, and the decision is stated on screen and in the report.
  Try `sample_data/claim_sample_mmddyyyy.xlsx`.
* **Plates** upper-cased without spaces/dashes; **products** mapped
  (AGO/Diesel/Mazout → DIESEL; PMS/Gasoline/Essence → PETROL); TINs read as
  text so leading zeros survive.
* Every repair is listed in the **Cleaning log** sheet.

## Matching, in order

1. Exact key `SdcId|invoice`.
2. SDC ID with one wrong/missing digit, same invoice, same product and quantity.
3. Slip unusable or not found → same seller TIN, product, quantity and time
   (±30 min). A match here goes to **review**, never auto-accepted.
4. Transaction date outside the EBM file's dates → **review** ("load EBM for
   this date"), not rejection.

## Rules

| Code | Rule | Result |
|---|---|---|
| R0 | Usable EBM reference / quantity | reject if no slip and no EBM match |
| R1 | Invoice exists in EBM | reject |
| R2 | Duplicate invoice (same claim, other rows, earlier claims) | reject; EBM litres shared in date order |
| R3 | Claimed L ≤ EBM L (±0.05 L) | excess rejected, rest paid (PARTIAL) |
| R4 | EBM unit price ≥ RURA price −1 RWF | reject |
| R5 | Tax type not exempt (A) | reject |
| R6 | Product matches | reject |
| R7 | Seller TIN = claimant | reject |
| R7 | EBM invoice date outside the declared consumption interval | reject |
| R7 | Closed at outside the interval but EBM invoice inside (typing error?) | review |
| R7 | Closed at outside the interval and no EBM invoice | reject |
| R7 | Closed at vs EBM time differs > 24 h | review |
| R8 | > 400 L per vehicle per day (or statistical outlier), refuel within 60 min | review |
| R9 | Invoice refunded (NR/CR) or training/proforma | reject |
| R10 | EBM invoice has no buyer TIN (999999999), or a buyer TIN different from the one that client normally uses | review |

### Indicators produced in one run (from the IKWIM verification notebook, extended)

* **All claimed / Accepted / Pending review / Rejected**: transactions, plates, invoices, operators (buyer TINs), litres, subsidy RWF, % of claimed litres.
* **EBM matching**: matched by slip number, matched after an SDC-ID typo fix, matched by date+quantity (to confirm), not found, match rate, slips claimed twice in the file.
* **By vehicle**: claimed / accepted / pending / rejected litres and RWF per plate and client, active days, litres per active day.
* **Price check**: claim P.U vs EBM P.U vs RURA price, per product.
* Duplicate rows in the EBM extract are counted once (they can no longer inflate the EBM quantity).

Try it on `sample_data/synthetic_875_lines_claim.csv` + `synthetic_875_lines_ebm.xlsx`
(synthetic data shaped like a real weekly OMC claim: mm/dd/yyyy dates, EBM 2.1 layout).

Lines in review are **pending**: not paid until a reviewer decides (Review
sheet has Decision and Note columns). Subsidy paid = accepted litres × rate.

All thresholds are in `engine/config.py` and in the app's sidebar.
**Confirm with RRA:** which EBM tax type codes are exempt (default `A`).
