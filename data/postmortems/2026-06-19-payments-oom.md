# Postmortem 2026-06-19: payments OOM loop

payments leaked memory in the receipt cache. Heap ramped for an hour before OOMKills.
A restart restored service for 9 hours, buying time for a proper fix. Lesson: a
memory ramp with no deploy means restart first, then heap dump.
