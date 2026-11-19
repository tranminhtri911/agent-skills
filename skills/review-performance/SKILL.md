---
name: review-performance
description: "Use when code involves threads, thread pools, async/await, background workers, queues, large files or streams, caching, memory growth, CPU-heavy loops, N+1 queries or connection usage, or when something is slow, leaks memory, hangs, or exhausts connections or workers. Triggers (vi): chậm, tối ưu hiệu năng, tốn bộ nhớ, rò rỉ bộ nhớ, CPU cao, treo, lag, quá tải, cache, N+1. Repo questions: làm sao sửa/kiểm tra?"
metadata:
  version: "1.0.3"
  suite: devskills
---

# Review Performance

Measure first, pick the concurrency model by workload, bound every resource, and prove improvements with before/after numbers from the same workload in an isolated environment.

`DS` = `python3 "${CLAUDE_SKILL_DIR}/scripts/ds.py"`.

## Hand-offs — load these too when the condition holds

Load each with the Skill tool before working on that part; dev-orchestrate routes the whole task.

- N+1, missing indexes, slow queries on large tables (query plans, IDX-008/009), long transactions, pool exhaustion → **REQUIRED:** change-database.
- Timeouts, queues, retries or back-pressure → **REQUIRED:** design-reliability.
- Load or performance tests → **REQUIRED:** test-safely.

## Pick the model by workload (plan §17.1)

| Workload | Use | Watch for |
| --- | --- | --- |
| Many I/O calls, async-native clients | async I/O with a limit on in-flight work | blocking calls on the event loop, orphaned tasks, missing timeouts |
| Blocking I/O / sync SDK | bounded thread pool | unbounded queue, stuck threads, shared sessions |
| CPU-bound Python | process pool or native/vectorized code | pickling cost, memory × processes |
| Long or must-survive work | durable queue + worker | duplicates, leases, shutdown, replay |
| Large files/streams | streaming/chunking with backpressure | buffers growing without limit |

Language specifics (Java executors, Node worker_threads, .NET, Go goroutines, PHP workers): [concurrency-by-language.md](references/concurrency-by-language.md).

## Resource rules

- PERF-001 limit workers **and** the queue of pending work; `max_workers` alone does not bound submissions.
- PERF-002 every task, thread, connection, file, response body and browser context has an owner and a lifetime.
- PERF-003 cleanup with context managers/`finally`/`using`/`defer` on success, error, timeout and cancellation.
- PERF-004 respect cancellation; clean up then propagate — no catch-all that keeps running.
- PERF-005 never wait inside a pool for tasks submitted to the same pool (starvation/deadlock).
- PERF-007 bounded caches (size + TTL), chunked batches, streaming and pagination for large data.
- PERF-008 no load tests, benchmarks or fault injection against production or paid APIs; only isolated targets.
- PERF-009 report dataset, concurrency, warmup, samples, p50/p95/p99, errors and resource cost.
- PERF-010 never claim "no leak" from one request: watch the trend over repeated workload after warmup.

## Method

1. Reproduce with a fixed workload in an isolated environment. 2. Measure: latency percentiles, throughput, CPU, RSS/heap, event-loop lag, threads/tasks, open files, pool wait, query count/time. 3. Find the bottleneck (profiler, `EXPLAIN`, query log, `tracemalloc` snapshots compared over time). 4. Make one small change. 5. Re-run the same workload; compare correctness and resource cost. 6. Keep or revert. If tail latency or DB connections exceed budget, it is not done.

Typical fixes in order: remove N+1 queries and over-fetching → add the index the query needs → paginate/stream → batch remote calls → bound concurrency → cache with explicit invalidation → only then scale out.

## Tools in this skill set

- `DS check-code` flags blocking calls in `async def`, threads created in loops, executors without limits, files opened without `with`, engines created per request, goroutines per loop iteration, unbounded thread pools.
- `DS pool-budget --group web:3:2:5:1 --surge-percent 100 --db-max 80` checks connection budgets at deployment peak.
- `DS run-tests --profile performance_isolated -- <bench command>` runs local benchmarks with timeouts and process cleanup (leftover processes are reported as possible leaks).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `async def` handler calling `requests`/`time.sleep` | async client or `asyncio.to_thread` |
| `ThreadPoolExecutor` fed a million items at once | bounded queue or `asyncio.Semaphore`/chunked submission |
| Cache without TTL or size | `lru_cache(maxsize=…)`/TTL cache, invalidate on write |
| "It is faster" from one run | warmup + repeated samples + percentiles |
| Whole API times out while one batch/request holds a transaction | Find the root blocker; timeout ladder (lock < statement < pool acquire < request), separate batch pool, no remote calls inside transactions — change-database → long-transactions.md |
