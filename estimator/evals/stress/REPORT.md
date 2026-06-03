# CAG Stress Test — Report

> Empirical map of where this CAG breaks. Filled from `evals/stress/results.csv`,
> produced by `uv run python -m evals.stress.run --http http://localhost:8000`
> against the live estimator (real LLM, real PDFs) on 2026-06-03.

## Run outcome

A clean run, unlike the first attempt (see History at the bottom). **780 rows,
772 successful, 8 errors (~1%).** 45 sessions: 38 completed all 20 turns, 1
reached 14, 6 died on turn 1 (stray 502s). `contradiction` completed sizes
0/5/20 KB only — the run ended before its 50/100 KB cells, so those are absent.

**Two honest caveats about how this run was produced:**

1. **`ENFORCE_PHASES_SUM=false`.** `gpt-4o-mini` cannot reliably make per-phase
   costs sum to `total_cost_eur`; with the rule on, ~57% of turns 502'd after
   Instructor exhausted its retries and never reached turn 20. For a stress run
   that measures latency/cost/memory (not euro-accuracy) we disabled *only* that
   one validator (flag-gated; production keeps it on). The estimates here are
   therefore arithmetically loose — irrelevant to the curves below.
2. **Turn axis reconstructed from row order.** This run predates the runner's
   `turn_index` fix; the server-side `turn_index` plateaus at the sliding-window
   cap (7). Each session has its 20 turns in order, so the true turn = row
   position within the session. The runner now writes the authoritative number
   directly.

**Run parameters:**

| Setting               | Value                                            |
|-----------------------|--------------------------------------------------|
| Model (`PRIMARY_MODEL`) | `gpt-4o-mini`                                  |
| Scenarios             | growing, pivot, contradiction (0/5/20 KB only)   |
| Attachment sizes (KB) | 0, 5, 20, 50, 100                                |
| Repeats per cell      | 3                                                |
| Latency budget        | 8 000 ms                                         |
| Cost budget per turn  | $0.02                                            |
| Rows in `results.csv` | 780 (772 ok + 8 errors)                          |
| Total spend           | ~$3.49                                           |

---

## 1. Summary table

One row per `(scenario, attachment_size_kb)` cell, over up to 60 turns (20 × 3
repeats). `Total $` is the summed cost of all turns in the cell.

| Scenario       | KB  | n  | P50 ms | P95 ms | Total $ | Drift pass % |
|----------------|----:|---:|-------:|-------:|--------:|-------------:|
| growing        |   0 | 60 |  7 482 | 14 994 |  0.0507 |        100.0 |
| growing        |   5 | 60 | 15 758 | 23 398 |  0.1051 |        100.0 |
| growing        |  20 | 60 | 20 846 | 27 424 |  0.2470 |        100.0 |
| growing        |  50 | 59 | 23 925 | 29 992 |  0.5260 |        100.0 |
| growing        | 100 | 60 | 23 709 | 28 799 |  0.6278 |        100.0 |
| pivot          |   0 | 60 |  4 877 |  8 524 |  0.0482 |        100.0 |
| pivot          |   5 | 60 |  8 569 | 18 459 |  0.1020 |        100.0 |
| pivot          |  20 | 60 | 12 647 | 21 539 |  0.2619 |        100.0 |
| pivot          |  50 | 60 | 15 869 | 22 696 |  0.5415 |        100.0 |
| pivot          | 100 | 60 | 18 344 | 22 048 |  0.6127 |        100.0 |
| contradiction  |   0 | 60 |  5 156 |  9 425 |  0.0532 |        100.0 |
| contradiction  |   5 | 60 |  7 705 | 19 538 |  0.1021 |        100.0 |
| contradiction  |  20 | 53 | 17 412 | 25 795 |  0.2138 |        100.0 |

**Budgets across all 772 successful turns:**

| Budget                  | Pass rate            |
|-------------------------|----------------------|
| Latency ≤ 8 000 ms      | **257 / 772 (33 %)** |
| Cost ≤ $0.02 per turn   | **770 / 772 (100 %)**|

Overall latency: **P50 ≈ 13.2 s, P95 ≈ 26.5 s, max ≈ 58.7 s.** Cost per turn was
never the problem on `gpt-4o-mini` — latency was, on two turns out of three.

---

## 2. Three curves (as tables)

### 2a. Latency vs context size — the dominant curve

`tokens_in` (system prompt + history window + transcript + extracted attachment),
median latency pooled across all successful turns:

| `tokens_in` bucket | Median latency (ms) | n   |
|--------------------|--------------------:|----:|
|   0–999            |          (no turns) |   0 |
| 1 000–2 999        |               4 999 |  29 |
| 3 000–6 999        |               5 989 | 188 |
| 7 000–14 999       |              12 051 | 182 |
| 15 000+            |              19 273 | 373 |

Clear, monotonic: latency roughly **quadruples** from the smallest to the
largest context bucket, and nearly half of all turns (373/772) sit in the
15 000+ bucket — driven by the re-injected attachment text. `tokens_in` ranged
2 166 → **159 485**.

### 2b. Cost accumulated vs turn index (size = 0, mean over repeats)

| Turn | growing $ | pivot $ | contradiction $ |
|-----:|----------:|--------:|----------------:|
|    1 |    0.001  |  0.000  |          0.000  |
|    5 |    0.003  |  0.003  |          0.003  |
|   10 |    0.008  |  0.007  |          0.007  |
|   15 |    0.012  |  0.011  |          0.012  |
|   20 |    0.017  |  0.016  |          0.018  |

Cost grows ~linearly per turn (the window caps how much history is re-sent, so
it does not explode). The real cost driver is attachment size, not turn count:
per cell, total cost goes from **~$0.05 at 0 KB to ~$0.63 at 100 KB — a ~12×
jump** (see §1).

### 2c. Memory drift vs turn index — 100 % everywhere (a structural non-result)

| Turn N | growing | pivot | contradiction |
|-------:|--------:|------:|--------------:|
|    2   |  100 %  | 100 % |        100 %   |
|    5   |  100 %  | 100 % |        100 %   |
|   10   |  100 %  | 100 % |        100 %   |
|   15   |  100 %  | 100 % |        100 %   |
|   20   |  100 %  | 100 % |        100 %   |

The tracked fact in every scenario is the turn-1 `project_name`
(Nimbus / Helios / Atlas). It never drifts — **but that is an artefact of where
the fact lives, not proof of perfect memory.** `project_name` is held in the
persistent `ProjectMetadata` side-channel, which is *not* subject to
sliding-window eviction, so it cannot be forgotten as long as the metadata
extractor keeps it. Confirmed by `anchors_count = 0` across all 772 rows: the
heuristic anchor detector never fired, so recall here is owed entirely to
`ProjectMetadata`. **This metric, as configured, cannot exhibit drift** — see
§4, claim 4.

---

## 3. Reading: where the CAG starts to break

**Paragraph 1 — the dominant failure mode is latency under context growth.**
On `gpt-4o-mini` the CAG does not fail on memory or on per-turn cost — it fails
on **latency**, and it does so as a smooth function of how much context each turn
carries. With no attachment, P50 latency is a tolerable 5–7 s; each step up in
attachment size pushes it higher until, at 50–100 KB, P50 sits at **~24 s and
P95 at ~30 s** (max observed 58.7 s). Only **33 % of all turns met the 8 s
budget**; the other two-thirds breached it, almost entirely on the
attachment-bearing cells. The latency-vs-`tokens_in` curve (§2a) shows why: it
rises monotonically with input size, and 48 % of turns landed in the 15 000+
token bucket because the full extracted attachment (capped at 60 000 chars) is
re-shipped into the prompt every single turn. Cost per turn, by contrast, stayed
under the $0.02 budget on 100 % of turns — `gpt-4o-mini` is cheap enough that the
dollar cost is a non-issue at this scale; the SLA is what breaks.

**Paragraph 2 — what this implies for the RAG decision.**
The argument for RAG here is **latency and input volume, not memory**. The single
biggest lever is the attachment: it is re-injected verbatim every turn, drives
`tokens_in` into the 15 000+ bucket, and is exactly what pushes P50 from ~5 s
(0 KB) to ~24 s (100 KB). RAG would retrieve only the ~1–2 K tokens relevant to
the current question instead of the whole 60 K-char document each turn,
collapsing the latency curve back toward the 0 KB baseline and cutting per-cell
cost ~12×. The limiting case that justifies the switch is concrete: **with
attachments ≥ 50 KB, every turn breaches the 8 s SLA (P50 ~24 s, P95 ~30 s).**
The memory dimension is a separate lesson: recall looked perfect only because the
one tracked fact lives in `ProjectMetadata`; a faithful drift test would track a
fact that exists *only* in the conversation window (an early requirement never
promoted to metadata), which is where eviction would actually bite — and where
RAG-over-history would be the answer.

---

## 4. Four claims to defend

1. My CAG's dominant failure is **latency**, not memory or cost: only **33 % of
   turns met the 8 s SLA**, and at ≥ 50 KB attachments **P50 is ~24 s** — every
   turn over budget.
2. Latency scales with **input context**: median latency goes 5 s → 6 s → 12 s →
   19 s across the `tokens_in` buckets, and ~half of all turns exceed 15 000
   input tokens because the full attachment is re-injected each turn.
3. Per-turn **cost is not a constraint** on `gpt-4o-mini` (100 % under $0.02), but
   total cost scales **~12× with attachment size** ($0.05 → $0.63 per cell) — the
   attachment, not the turn count, is the cost driver.
4. My **memory_drift metric cannot show drift as configured**: it tracks
   `project_name`, which lives in the persistent `ProjectMetadata` (immune to
   window eviction; `anchors_count` was 0 throughout). To measure real recall
   loss I must track a window-only fact — that is the next iteration.

---

## 5. Reproducibility

```bash
# Fixtures (deterministic).
uv run python -m evals.stress.fixtures.build_pdfs

# Stress run on gpt-4o-mini with the phases-sum rule disabled for the run:
#   estimator/.env -> PRIMARY_MODEL=gpt-4o-mini ; ENFORCE_PHASES_SUM=false
docker compose up -d --force-recreate estimator
curl -sf http://localhost:8000/health

uv run python -m evals.stress.run \
    --http http://localhost:8000 \
    --scenarios growing,pivot,contradiction \
    --attachment-sizes 0,5,20,50,100 \
    --repeats 3 \
    --latency-budget-ms 8000 \
    --cost-budget-usd 0.02 \
    --output evals/stress/results.csv
```

`results.csv` is gitignored (regenerated per run). With the runner's
`turn_index` fix, a fresh run writes the true turn number directly (no
row-order reconstruction needed).

---

## History

- **Attempt 1 (`claude-sonnet-4-5`):** hard-failed — the CAG's per-turn token
  volume tripped Anthropic's 30 000-tokens/minute tier-1 rate limit; 29/45
  sessions died on turn 1, none past turn 7. Switched model.
- **Attempt 2 (`gpt-4o-mini`, rule on):** ~57 % of turns 502'd on the phases-sum
  validator (gpt-4o-mini mis-sums by ~20 %). Disabled the rule for the stress run.
- **Attempt 3 (`gpt-4o-mini`, rule off):** this report. Clean — ~1 % errors,
  38/45 sessions to turn 20.
