# Concurrency and resource patterns by language

## Python

```python
import asyncio

async def fetch_all(urls: list[str], client: httpx.AsyncClient, max_in_flight: int = 10) -> list[bytes]:
    """Fetch with at most max_in_flight concurrent requests; any failure cancels the rest."""
    semaphore = asyncio.Semaphore(max_in_flight)

    async def fetch(url: str) -> bytes:
        async with semaphore:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return response.content

    async with asyncio.TaskGroup() as group:  # structured concurrency: no orphaned tasks
        tasks = [group.create_task(fetch(url)) for url in urls]
    return [task.result() for task in tasks]
```

- Blocking SDK: `concurrent.futures.ThreadPoolExecutor(max_workers=N)` and submit in bounded batches.
- CPU-bound: `ProcessPoolExecutor`; pass small inputs; dispose DB engines after fork.
- Free-threaded builds (3.13t+) only after measuring and checking library thread safety.

## Java / Kotlin

- `new ThreadPoolExecutor(core, max, keepAlive, unit, new ArrayBlockingQueue<>(capacity), rejectionPolicy)` — never `Executors.newCachedThreadPool()` for unbounded input.
- Virtual threads (Java 21+) still need limits on downstream resources (DB pool, rate limits).
- `try-with-resources` for connections/streams; `CompletableFuture` with timeouts (`orTimeout`).

## Node.js / TypeScript

- The event loop is single-threaded: CPU work goes to `worker_threads` or a queue.
- Limit concurrency with `p-limit`/a semaphore; `AbortController` + timeouts on `fetch`.
- Streams with `pipeline()` for backpressure; avoid reading whole files into memory.

## .NET

- `async`/`await` end to end; no `.Result`/`.Wait()`; pass `CancellationToken`.
- `SemaphoreSlim` or `Parallel.ForEachAsync(…, new ParallelOptions { MaxDegreeOfParallelism = N })`.
- `IHttpClientFactory` for HttpClient lifetime; `await using` for disposables.

## Go

```go
sem := make(chan struct{}, 10) // at most 10 concurrent workers
var wg sync.WaitGroup
for _, item := range items {
    wg.Add(1)
    sem <- struct{}{}
    go func(item Item) {
        defer wg.Done()
        defer func() { <-sem }()
        process(ctx, item)
    }(item)
}
wg.Wait()
```

- `context.WithTimeout` on every remote call; `errgroup.WithContext` + `SetLimit`.

## PHP (Laravel)

- Concurrency comes from processes: size PHP-FPM workers and queue workers to the DB budget.
- Long jobs in queues with `timeout`, `tries`, `backoff`; chunk large queries with `chunkById`/`lazyById`.

## Signals to collect

latency p50/p95/p99 · throughput · error rate · CPU · RSS/heap · event-loop lag · thread/task count · open file descriptors · DB pool in-use/wait · query count per request · queue depth and oldest job age.
