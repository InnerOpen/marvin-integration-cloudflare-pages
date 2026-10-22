---
name: cloudflare-pages-failed-build
description: Use when someone asks why the site failed to build or deploy on Cloudflare Pages, or when a site_deployment_failed event needs explaining. Finds the failure, reads the build-log reason, names the likely cause and the next step, and never guesses past what the log says.
allowed-tools: list_events describe_event get_workflow find_entries get_entry
---

# Explaining a failed Cloudflare Pages build

Someone is asking why the site didn't go live. Answer from evidence: the failure event, the line from the build log, and
what the workspace shows. If the evidence isn't there, say so. A confident wrong cause sends a person to fix the wrong
thing.

You can only read. You can't retry the build, change a setting or touch Cloudflare, so end with what a person should do.

## 1. Find the failure

1. `list_events` with `event_type` `site_deployment_failed` (a small `limit`, say 5). Each row has a time and a title like
   "my-site failed to build or deploy". Note when the latest one happened.
2. Compare it with the most recent `site_deployment_completed` event. If a build succeeded after the failure, the site is
   live again: say so, and treat the failure as history.
3. Ask which build they mean if more than one failed and it isn't clear.

## 2. Find the reason

The reason is the end of Cloudflare's build log. The `cloudflare-pages-deploy-failed` workflow reads it when Cloudflare
reports the failure and puts it on the failure event and on the build's row under Settings, Automation, Results, with a
link to the full log.

- If the person pasted the error line or the log, work from that.
- Use `get_workflow` on `cloudflare-pages-deploy-failed` to check it is switched on and see how its last run went. A
  workflow that is off, or whose last run failed, explains why there is no reason on the event.
- If you can't see the log, say that plainly and point them to the Results row or the log link in the notification.
  Don't infer a cause from the project's name or from what usually breaks.

`describe_event` on `site_deployment_failed` shows what reacts to a failure here (the workflow, any notification) and when
it last happened. Use it when the question is "why didn't I hear about it" rather than "why did it fail".

## 3. Say what it likely is

Match the line against `references/causes.md` for the common causes and the usual fix. Quote the log line you matched, so
the person can check you. If two causes fit, give both and say what would tell them apart. If none fits, say the line
doesn't match anything you know and say what you'd look at next in the log, above the final error.

If the build failed after a content change, `find_entries` and `get_entry` can show what was published or changed just
before (recently published entries, a changed field). Treat that as a lead, not proof: a build can fail for reasons
unrelated to the last edit.

## 4. The shape of the answer

Keep it short and in this order:

1. **What happened:** which build, when, failed in the build or in the deploy step.
2. **The reason:** the log line, quoted, or "I can't see the log".
3. **Most likely cause:** one sentence, with how sure you are.
4. **What to do:** the first step a person can take, in Cloudflare or in the site's code. Mention a retry only when the
   cause was temporary (a timeout, a network error).
5. **What you couldn't check.**

## Never

- Never guess past the log. "Probably a dependency issue" without a line that says so is a guess.
- Never say the site is down because a build failed. The previous successful deployment keeps serving until a new one
  succeeds.
- Never invent a command, a setting name or a version number. Use the ones in the log.
