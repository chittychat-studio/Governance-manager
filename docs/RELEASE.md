# Release checklist (SPEC RL1, P4a)

The maintainer does these steps. The agent must not make the repository public, create the signing key or push tags.

0. `python scripts/release_check.py` runs every check below and lists what is left.
1. `python -m pytest` and `python scripts/eval.py` pass (all gates).
2. Version bumped in `.claude-plugin/plugin.json` and `scripts/governance.py` (`GOVERNOR_VERSION`); CHANGELOG entry
   dated.
3. First release only: create the signing key **outside** the repo and back it up somewhere safe (password manager
   or an offline drive). Losing it means publishing a new public key; leaking it means anyone can sign packs.
   `python scripts/sign_pack.py --new-key ~/governor-signing/packs.key`
   This writes `packs/SIGNING_KEY.pub`. Commit that file only.
4. Sign: `python scripts/sign_pack.py --sign-key ~/governor-signing/packs.key`. Commit `packs/PACKS.lock` and
   `packs/PACKS.lock.sig`. From now on every pack edit needs a re-sign, or installs refuse (by design).
5. `python scripts/status.py <any installed repo>` shows `Signature: signed (verified)`.
6. Merge to `main`, then tag: `git tag v0.2.0 && git push origin v0.2.0`.
7. Make the repository public (GitHub → Settings → General → Danger zone → Change visibility). Check first that no
   private material is in history (`git log --all -p | grep -iE "key|secret|token"` is a start, not a proof).
8. Test the public install on a clean machine: `/plugin marketplace add chittychat-studio/Governance-manager`,
   `/plugin install governor@chittychat-governor`, `/governor:init` in a throwaway repo.
