# Landing work

Work on a branch. Do not open PRs here.
Once the tests covering your change pass and the review is clean, merge the branch into `main` with a merge commit whose subject is `Merge branch <branch>: <summary>`, then push `main` to `origin` (never force).
Run tests directly: `python3 -m unittest discover -s scripts -p 'test_*.py'`, `python3 -m unittest discover -s skills/<name>/tests` for a skill with its own tests, `node --test workflows/*.test.js`, and `node --experimental-strip-types extensions/<name>.test.mts`. `hoffice/AGENTS.md` names hoffice's.
This is the operator's standing grant for this repo under the global Autonomy rule: merging and pushing are expected completion steps, not skipped irreversible actions.
