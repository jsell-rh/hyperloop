# Worker Pre-Submission Checklist

Run through every item before reporting results. Do not submit until all boxes are checked.

- [ ] All tests pass (`uv run pytest`)
- [ ] Lint clean (`uv run ruff check .`)
- [ ] Format clean (`uv run ruff format --check .`)
- [ ] `.worker-result.json` written to repo root with `verdict`, `findings`, and `detail` fields
- [ ] `.worker-result.json` is valid JSON (verify with `python -m json.tool .worker-result.json`)
- [ ] All changes committed on the task branch
- [ ] No uncommitted files (`git status` is clean)
- [ ] Run `specs/prompts/checks/check_result_file.sh` and confirm it exits 0
