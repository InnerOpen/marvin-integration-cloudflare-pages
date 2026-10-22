# Common causes of a failed Pages build

Match on the log line first. The wording differs by framework; these are the patterns that come up most.

| What the log says | Likely cause | What to do |
|---|---|---|
| `Command not found`, `npm: not found`, `command exited with code 127` | The build command or a tool it calls isn't installed in the build image | Check the project's build command in Cloudflare (Settings, Builds). Add the missing tool as a dependency so the install step provides it. |
| `Cannot find module 'x'`, `Module not found`, `ERR_MODULE_NOT_FOUND` | A dependency is missing from `package.json`, or the lockfile and `package.json` disagree | Add it to dependencies (not only devDependencies if the build needs it), commit the lockfile, build again. Check the name's capitalisation: builds run on a case-sensitive filesystem. |
| `npm ERR! code ERESOLVE`, `peer dependency` | Conflicting dependency versions | Fix the versions in `package.json`, or keep a lockfile that resolves. |
| `Node.js version`, `requires Node >=`, `engine "node" is incompatible` | The build is using a different Node version than the project needs | Set the Node version in the project (an `.nvmrc` file, or the `NODE_VERSION` build variable in Cloudflare). |
| `Error: Cannot read properties of undefined`, a stack trace pointing into the site's own files | A bug in the site's code or in the content it reads (a missing field, an unexpected null) | Read the file and line in the trace. Look at recently published content that page or template uses. |
| `Failed to fetch`, `ECONNREFUSED`, `ETIMEDOUT`, `fetch failed` during the build | The build asks an API for content and couldn't reach it, or it answered with an error | Check the content API is up and its address and token are right in the build variables. A retry often works if it was a blip. |
| `401`, `403`, `Unauthorized`, `Forbidden` while fetching | A token or key in the build variables is missing, wrong or expired | Check the variable named in the log in Cloudflare (Settings, Variables), then retry. |
| `Build timed out`, `exceeded the maximum build time` | The build ran longer than the limit | Look for the slow step in the log. Reduce what is built, cache dependencies, or retry if it was a one-off slow fetch. |
| `ENOSPC`, `JavaScript heap out of memory`, `Killed` | The build ran out of disk or memory | Reduce what the build holds in memory at once (large images, large content sets), or split the work. |
| `Failed: error occurred while running build command` with nothing above it | The real error is earlier in the log | Read upward from the last line to the first `error` or `failed`. |
| `Missing script: "build"`, `no build command` | The build command is wrong or missing | Check it in Cloudflare (Settings, Builds) against the scripts in `package.json`. |
| `Output directory "x" not found`, `build output directory` | The build succeeded but wrote its files somewhere else | Check the output directory setting matches what the build produces (often `dist` or `public`). |
| `Failed to publish your Function`, `Error: Failed to upload` | The deploy step failed, after a good build | Retry once. If it keeps failing, check Cloudflare's status page and the project's limits (file count, file size). |
| `Deployment failed` with no build error | The build was fine and the deploy step failed | Same as above: retry, then check Cloudflare's status page. |

## Reading a log

- The failure is rarely the last line. The last line is usually the build tool saying it gave up.
- Read upward to the first line that says `error`, `failed`, `cannot` or `exited with`, and quote that.
- A long run of warnings is not the cause. Don't quote them.

## When the cause was temporary

A timeout, a network error or a 5xx from an API the build calls is usually temporary. Say a retry is reasonable, and that if
it fails the same way twice it is not temporary.
