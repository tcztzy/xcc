# Performance

## Goals

- Fast compile times for large C codebases (CPython-sized).
- Predictable memory usage with bounded peaks.
- No hidden quadratic behavior in the front end.

## Benchmarking

- Use the standard library for timing (for example `time.perf_counter`).
- Track end to end compile time and memory per translation unit.
- Maintain a stable baseline for CPython builds and compare regressions.

## Optimization policy

- Optimize only after correctness is proven.
- Every optimization must have a benchmark and a regression test.
- Keep optimizations modular and easy to disable.
