# Digests

Create `<digest>/DIGEST.md` using the hoffice engine's `templates/digest-config.md` to define projects, source kinds, and cadence. Dated outputs live beside it. Run `/hoffice-digest <digest> [daily|weekly]`.

Source instructions belong in instance `extensions/sources/<kind>.md`. Missing sources are reported as coverage gaps. Scheduling belongs in `extensions/scheduler.md`; without it, run the launcher by hand. Digests record activity, not proof of what shipped.
