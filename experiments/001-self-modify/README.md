# Self-Modification Experiment

## Research Question
Can Sick add a new tool to itself, verify it works, and retain it across sessions?

## Experiment Design
1. Start with the baseline SickAgent (6 P0 tools)
2. Instruct: `modify_self("Add a web_fetch(url) method")`
3. Measure:
   - Success rate (import verifies, tests pass)
   - Time to completion
   - Lines of code added
   - Did the agent also add a test?

## How to Run
```bash
uv run python demos/self_evolve.py
```

## Results
(TBD after first run)
