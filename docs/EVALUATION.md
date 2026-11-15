# EASA — Retrieval Evaluation

> **Status:** Phase 3, P3-M5. Measured on 2026-11-14 with the commands in section 7. All data is synthetic.

This document records how well EASA's retrieval finds the right text, how the three search modes and six chunking settings compare, whether PostgreSQL gives the same results as SQLite, and whether an approximate vector index (HNSW) is worth adopting yet.

## 1. Summary

- **Hybrid search is the most robust mode.** With the default chunking it ranks the right chunk first for 82% of queries (SQLite) and within the top 3 for 97%, and it is never weak on any query type. Recommended for grounded answering in Phase 4.
- **Each single mode has a blind spot.** Keyword search ranks the right chunk first for only 38% of paraphrased questions. Semantic search misses some exact codes: `LV-102` is not in its top 10 at all.
- **Smaller chunks help semantic search and hurt keyword search.** Semantic MRR rises from 0.850 (1,200 characters) to 0.946 (400). Hybrid is best at 800–1,200 characters. The differences between 800 and 1,200 are 2–3 queries out of 60, too few to justify changing the default yet.
- **Top 5 is enough.** Hybrid recall reaches 0.983 at 5 results with the default chunking; 3–5 chunks should be enough context for Phase 4.
- **PostgreSQL matches SQLite exactly for semantic search.** Its keyword ranking (`ts_rank_cd`, no inverse document frequency) is weaker than SQLite's BM25 on exact terms (R@1 0.800 vs 1.000); hybrid search recovers most of the gap.
- **Keep exact vector search (ADR-022).** HNSW is roughly 5–12 times faster at 50,000 vectors, but with a tenant filter its recall is 0.41 at default settings and 0.91–0.94 only with iterative scans enabled. EASA's corpus is about 100 chunks today, where exact search takes milliseconds.

## 2. Dataset

| Item | Value |
|---|---|
| Corpus | 12 synthetic policy documents of the fictional company "Larkspur Analytics" (leave, travel, expenses, remote work, IT security, onboarding, code of conduct, benefits, performance reviews, procurement, data retention, facilities), 24 KB of plain text, in [apps/api/eval/corpus/](../apps/api/eval/corpus/) |
| Queries | 60 in [apps/api/eval/queries.json](../apps/api/eval/queries.json): 24 **paraphrase** (few words shared with the answer, e.g. "How many vacation days do I get each year?"), 15 **exact** (codes, names, specific terms, e.g. `EXP-4471`, "Vaultline"), 21 **keyword** (keyword-style, e.g. "parking permits") |
| Labels | Each query names its document and an evidence phrase: an exact substring of that document that answers the query |
| Relevance | A retrieved chunk is relevant if its text contains the evidence phrase. This works for every chunk size. A unit test checks that every phrase appears exactly once in its document and in no other document |

Codes sit inside longer documents, so a document is never a single chunk for one code (a weakness of the P3-M3 live test).

## 3. Method

For each chunking setting, the runner (`app/evaluation/runner.py`) creates a fresh database, applies all migrations, and uploads the corpus through the normal pipeline (validation, extraction, normalization, chunking, embedding with the real `bge-small-en-v1.5@aa8f8b060edb` model). It then runs every query in every mode through `SearchService` with `top_k = 10`, exactly as the API does. It refuses to report if any chunk lacks a vector.

| Metric | Meaning |
|---|---|
| R@k (recall at k) | Share of queries whose evidence appears within the top k results (one phrase per query) |
| MRR@10 | Mean of 1 / rank of the first relevant result (0 if not in the top 10) |

**Primary metrics are R@1, R@3 and MRR.** With only 24–97 chunks, the top 10 covers a large share of the corpus (40% at 1,200 characters), so R@10 is inflated. One query is 0.017 of a score; differences below about 0.05 (3 queries) should be treated as noise.

Chunk settings: `structured` (whole paragraphs, grouped up to the limit) and `fixed` (overlapping windows, 150-character overlap) at 1,200 (the application default), 800 and 400 characters.

## 4. Results (SQLite)

### 4.1 Chunking settings

| Setting | Chunks | Mean chunk length |
|---|---|---|
| structured-1200 (default) | 24 | 1,003 |
| structured-800 | 37 | 650 |
| structured-400 | 86 | 278 |
| fixed-1200 | 27 | 973 |
| fixed-800 | 43 | 665 |
| fixed-400 | 97 | 376 |

### 4.2 All queries

| Setting | Mode | R@1 | R@3 | R@5 | R@10 | MRR@10 |
|---|---|---|---|---|---|---|
| structured-1200 | semantic | 0.783 | 0.900 | 0.933 | 0.983 | 0.850 |
| structured-1200 | keyword | 0.750 | 0.883 | 0.967 | 0.983 | 0.829 |
| structured-1200 | **hybrid** | **0.817** | **0.967** | **0.983** | 1.000 | **0.887** |
| structured-800 | semantic | 0.833 | 0.950 | 0.967 | 0.983 | 0.887 |
| structured-800 | keyword | 0.767 | 0.850 | 0.900 | 0.950 | 0.820 |
| structured-800 | hybrid | 0.867 | 0.933 | 0.983 | 1.000 | 0.911 |
| structured-400 | semantic | 0.900 | 0.983 | 1.000 | 1.000 | 0.946 |
| structured-400 | keyword | 0.667 | 0.750 | 0.817 | 0.883 | 0.725 |
| structured-400 | hybrid | 0.800 | 0.900 | 0.933 | 0.967 | 0.860 |
| fixed-1200 | semantic | 0.767 | 0.900 | 0.917 | 0.983 | 0.836 |
| fixed-1200 | keyword | 0.767 | 0.900 | 0.933 | 0.983 | 0.837 |
| fixed-1200 | hybrid | 0.867 | 0.950 | 0.967 | 1.000 | 0.911 |
| fixed-800 | semantic | 0.783 | 0.933 | 0.950 | 0.983 | 0.856 |
| fixed-800 | keyword | 0.700 | 0.850 | 0.883 | 0.933 | 0.786 |
| fixed-800 | hybrid | 0.817 | 0.900 | 0.983 | 1.000 | 0.874 |
| fixed-400 | semantic | 0.850 | 0.950 | 0.967 | 0.983 | 0.904 |
| fixed-400 | keyword | 0.683 | 0.833 | 0.883 | 0.900 | 0.767 |
| fixed-400 | hybrid | 0.767 | 0.900 | 0.967 | 1.000 | 0.853 |

### 4.3 By query type (default setting, structured-1200)

| Type (n) | Mode | R@1 | R@3 | MRR@10 |
|---|---|---|---|---|
| paraphrase (24) | semantic | 0.667 | 0.875 | 0.787 |
| paraphrase (24) | keyword | 0.375 | 0.708 | 0.571 |
| paraphrase (24) | hybrid | 0.625 | 0.958 | 0.771 |
| exact (15) | semantic | 0.800 | 0.867 | 0.831 |
| exact (15) | keyword | 1.000 | 1.000 | 1.000 |
| exact (15) | hybrid | 0.933 | 0.933 | 0.947 |
| keyword (21) | semantic | 0.905 | 0.952 | 0.937 |
| keyword (21) | keyword | 1.000 | 1.000 | 1.000 |
| keyword (21) | hybrid | 0.952 | 1.000 | 0.976 |

At 400 characters semantic search reaches 0.833 R@1 on paraphrases, but keyword search drops to 0.250, which drags hybrid down to 0.500.

### 4.4 Observations

- Semantic search missed `LV-102` completely and ranked `ONB-15` third: codes carry little meaning for an embedding model. Keyword search found every code first.
- Keyword search fails when the question shares few words with the answer ("Can I keep a present a supplier sent me?" vs "accept gifts").
- Reciprocal rank fusion keeps most of each mode's strengths: hybrid is within 0.07 of the better single mode in every query type at the default setting (largest gap: exact terms, R@1 0.933 vs 1.000 for keyword), and it is the best mode overall.
- Smaller chunks make each chunk more topical, which helps semantic matching, but they give BM25 less text per chunk and more competing chunks, which hurts keyword ranking.

## 5. PostgreSQL versus SQLite

The same runs on PostgreSQL 18.7 + pgvector 0.8.7 (`evaluate --backend postgres --configs all`):

- **Semantic search: identical** metrics for all six settings (for example structured-1200: R@1 0.783, MRR 0.850 on both). pgvector's exact search and the NumPy brute force agree, as the parity tests require.
- **Keyword search: different ranking function.** For structured-1200, PostgreSQL R@1 is 0.717 (SQLite 0.750); on exact terms 0.800 (SQLite 1.000). The misses are queries where a common word outweighs a rare one: "anchor day" (`day`), "cycle-to-work scheme" (`work`), "phish@larkspur.example" (`larkspur` appears in every document), "contract legal review". `ts_rank_cd` counts term occurrences without inverse document frequency, so it cannot tell rare words from common ones. That is also why it has no cross-tenant statistics leak (SECURITY.md).
- **Hybrid narrows the gap**: PostgreSQL structured-1200 hybrid R@1 0.833, MRR 0.898 (SQLite 0.817, 0.887).

| structured-1200 | SQLite R@1 | PostgreSQL R@1 | SQLite MRR | PostgreSQL MRR |
|---|---|---|---|---|
| semantic | 0.783 | 0.783 | 0.850 | 0.850 |
| keyword | 0.750 | 0.717 | 0.829 | 0.811 |
| hybrid | 0.817 | 0.833 | 0.887 | 0.898 |

Mean query latency in these runs (laptop, Docker, includes query embedding): SQLite semantic 18 ms, keyword 5 ms, hybrid 21 ms; PostgreSQL semantic 24 ms, keyword 18 ms, hybrid 35 ms.

## 6. Exact search versus HNSW (PostgreSQL)

`evaluate-hnsw` (`app/evaluation/hnsw.py`) loads 50,000 synthetic 384-dimensional vectors into a throwaway database, runs 100 queries with the application's exact search (`PgvectorIndex`), then builds an HNSW index (`m = 16`, `ef_construction = 64`, a partial expression index on `vector::vector(384)` for one model) and repeats the queries with the same tenant, model and status filters. Recall@10 is the overlap with the exact top 10.

**Synthetic data.** Real sentence embeddings have a low intrinsic dimension, so vectors are points of a 32-dimensional Gaussian projected to 384 dimensions plus small noise (0.1); queries are fresh points from the same distribution. A first design (tight clusters, queries copied from stored vectors) was rejected: its exact top 10 consisted of near-ties, so "recall" measured tie-breaking (0.16–0.67 regardless of settings).

| Tenants (rows per tenant) | ef_search | iterative_scan | Index used | Recall@10 | Median ms | p95 ms |
|---|---|---|---|---|---|---|
| 1 (50,000) | 40 | off | yes | 0.890 | 7.6 | 13.0 |
| 1 (50,000) | 100 | off | yes | 0.974 | 6.6 | 7.8 |
| 10 (5,000) | 40 | off | yes | **0.406** | 29.3 | 118.6 |
| 10 (5,000) | 40 | relaxed_order | yes | 0.914 | 11.2 | 110.4 |
| 10 (5,000) | 100 | off | yes | 0.833 | 9.9 | 16.5 |
| 10 (5,000) | 100 | relaxed_order | yes | 0.939 | 10.7 | 15.1 |

Exact search: median 76.9 ms (p95 129.1) for one tenant of 50,000 vectors and 62.1 ms (p95 121.6) with 10 tenants. Index build: 84–94 s.

Findings:
- **Filters are the main risk.** HNSW finds the nearest vectors first and applies the tenant filter afterwards. With 10% of rows per tenant and `ef_search = 40`, only about 4 of the 40 candidates belong to the tenant, so recall falls to 0.41. pgvector 0.8's iterative scan (`relaxed_order`) keeps searching until enough rows pass the filter and restores recall to 0.91–0.94.
- **Speed.** HNSW answered in 7–11 ms median in most settings (29 ms in one noisy setting) versus 62–77 ms for exact search: roughly 5–12 times faster at this size, and exact search grows linearly with the corpus.
- **Latency numbers are indicative only.** They come from a laptop running Docker and varied by 2–3 times between runs (an earlier run measured exact search at 23 ms median for 10 tenants).
- **At EASA's real size** (about 100 chunks) exact search is a few milliseconds and always correct, so an index would add build time, memory and recall risk for no benefit.

Decision: keep exact search ([ADR-022](ARCHITECTURE_DECISIONS.md#adr-022)).

## 7. Reproducing

From `apps/api` (the real model must be downloaded; PostgreSQL from `compose.yaml` for the PostgreSQL runs):

```powershell
uv run python -m app.cli evaluate --configs all                     # SQLite, 6 settings, about 1 minute
$env:EASA_EVAL_POSTGRES_URL = "postgresql+psycopg://easa:<password>@127.0.0.1:5433/easa"
uv run python -m app.cli evaluate --backend postgres --configs all  # about 1 minute
uv run python -m app.cli evaluate-hnsw --tenants 10                 # about 2 minutes
uv run python -m app.cli evaluate-hnsw --tenants 1
$env:EASA_EVAL_POSTGRES_URL = $null
```

Reports (JSON with every query outcome, and Markdown tables) are written to `apps/api/var/eval/` (git-ignored). PostgreSQL runs create and drop throwaway databases named `easa_eval_<random>`. With `EASA_EMBEDDING_PROVIDER=hashing` the runner works without the model (for checking the pipeline only; the numbers are not meaningful).

## 8. Limitations

- **Optimistic.** The same author wrote the documents, the queries and the labels, the corpus is small and clean, and every query has exactly one answer. Real questions are vaguer, real documents longer and messier. Treat the absolute numbers as an upper bound and the comparisons as the useful part.
- **Small samples.** 60 queries; per-type groups have 15–24 queries, so a single query moves a group score by 0.04–0.07.
- **Retrieval only.** These metrics say whether the right text is retrieved, not whether a final answer is correct; answer quality is measured in Phase 4.
- **Chunk size trade-off is not fully captured.** Larger chunks make recall easier (fewer, bigger targets) but put more irrelevant text into a prompt; Phase 4 should weigh retrieval scores against answer quality and context length.
- **HNSW data is synthetic.** Recall depends on the data distribution; real embeddings should be re-measured before adopting an index.

## 9. Recommendations

1. Use **hybrid** retrieval for Phase 4 grounding, with 3–5 chunks of context. *(Done in P4-M2: answers use hybrid retrieval with 5 chunks by default, and the search API's default mode is now `hybrid`.)*
2. Keep the **structured-1200** default for now; re-evaluate 800 characters together with answer quality in Phase 4.
3. On PostgreSQL, prefer hybrid over keyword-only search. Improving PostgreSQL keyword ranking (for example a BM25 extension or per-tenant term statistics) is possible future work.
4. Keep **exact vector search** until a tenant has roughly 100,000 chunks or exact search exceeds the latency budget. Then add a partial HNSW index per model with `hnsw.iterative_scan = relaxed_order` and `ef_search` of at least 100, and re-measure recall on real embeddings with this runner.
5. Extend the dataset in later phases with real-world-style questions written by someone other than the corpus author, and with questions that have no answer in the corpus.
