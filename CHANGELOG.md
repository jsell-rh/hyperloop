# CHANGELOG

<!-- version list -->

## v0.35.0 (2026-04-23)


## v0.34.2 (2026-04-23)


## v0.34.1 (2026-04-23)


## v0.34.0 (2026-04-23)

### Features

- Add args to action/check steps, extract mark-pr-ready from gate
  ([`e92530f`](https://github.com/jsell-rh/hyperloop/commit/e92530f663e46af238a69f9dc5df4cbe720289a5))


## v0.33.0 (2026-04-23)

### Bug Fixes

- Auto-resolve .hyperloop/checks/ and .agent-memory/ conflicts during rebase
  ([`6ae875d`](https://github.com/jsell-rh/hyperloop/commit/6ae875d9016f8583970719b629cc25d5e65e0aa0))

- Dashboard pipeline endpoints handle check: step type
  ([`003358e`](https://github.com/jsell-rh/hyperloop/commit/003358eb6bb5c2a43f95b9e368fcbb1268756a71))

### Features

- Group spec cards by directory on overview page
  ([`fb2006c`](https://github.com/jsell-rh/hyperloop/commit/fb2006cd2c5247ab5040b0b1f70e4b5ccba834b8))

- Show PR title and description on task detail page
  ([`8d7aadb`](https://github.com/jsell-rh/hyperloop/commit/8d7aadb1636e79b2781a95c3f7e1c12524d87058))

- Sidebar navigation with per-domain progress on overview page
  ([`86dc4f0`](https://github.com/jsell-rh/hyperloop/commit/86dc4f0fa8ce78d9709b138970d63bacaa5509ca))


## v0.32.0 (2026-04-23)

### Bug Fixes

- Only re-pin spec SHA on completed tasks when PM creates new work
  ([`117241a`](https://github.com/jsell-rh/hyperloop/commit/117241a2f133f10032488c0d6e41764f0783fdbe))


## v0.31.2 (2026-04-23)

### Bug Fixes

- Add 'check' to known pipeline primitive keys
  ([`baa8b05`](https://github.com/jsell-rh/hyperloop/commit/baa8b051cd4b28582bf298c534ee8ca210f05e9e))


## v0.31.1 (2026-04-23)


## v0.31.0 (2026-04-23)


## v0.30.0 (2026-04-23)


## v0.29.0 (2026-04-22)


## v0.28.2 (2026-04-22)


## v0.28.1 (2026-04-22)


## v0.28.0 (2026-04-22)


## v0.27.1 (2026-04-22)

### Bug Fixes

- Remove instruction to commit review files from base agent prompts
  ([`719d44f`](https://github.com/jsell-rh/hyperloop/commit/719d44f403f9c0ce574a9019ced5cfd93009c576))


## v0.27.0 (2026-04-22)

### Bug Fixes

- Show loop iteration count on pipeline bracket
  ([`9999011`](https://github.com/jsell-rh/hyperloop/commit/99990117830fe432ebaa762e0da89b6d112aa01c))


## v0.26.1 (2026-04-22)


## v0.26.0 (2026-04-22)

### Bug Fixes

- Dep graph — mini pipeline bar, fixed-width tooltip, pipeline steps prop
  ([`c1b5cd0`](https://github.com/jsell-rh/hyperloop/commit/c1b5cd0a9270c2a255bcdd15723974f315da66d8))

- Dep graph — remove icons/bars, phase pill, tooltip clamping, contrast
  ([`1659e71`](https://github.com/jsell-rh/hyperloop/commit/1659e717ff16fec221289a66d2afbdd339484e1f))

- Dep graph — text overflow, round badge, bar hover tooltips, bar animation
  ([`e39da9c`](https://github.com/jsell-rh/hyperloop/commit/e39da9c6e16e019f0d2be77afa01c67fe859231e))


## v0.25.1 (2026-04-21)


## v0.25.0 (2026-04-21)


## v0.24.0 (2026-04-21)

### Features

- Gate rework — pr-require-label, pr-require-approval, GitHub comment notifications
  ([`c7ae615`](https://github.com/jsell-rh/hyperloop/commit/c7ae61565f7ccab8e9365c60f2d359c7a2aec02c))


## v0.23.0 (2026-04-21)

### Features

- Sync trunk with remote after persist, before spawning workers
  ([`30ba3da`](https://github.com/jsell-rh/hyperloop/commit/30ba3da5ae502c0b427ecd83575cde42919514f9))


## v0.22.0 (2026-04-21)


## v0.21.0 (2026-04-21)

### Bug Fixes

- Parse flat config per spec, validate gate/action ports at startup
  ([`2abadeb`](https://github.com/jsell-rh/hyperloop/commit/2abadeb150818fbb1a9e7f7e2aa0a7c4bc2d1d96))


## v0.20.5 (2026-04-21)


## v0.20.4 (2026-04-21)


## v0.20.3 (2026-04-17)

### Bug Fixes

- Check push return code after rebase, fallback to --force
  ([`4deecfe`](https://github.com/jsell-rh/hyperloop/commit/4deecfe2f63eaa69860bb0d8424bde67a4561de1))


## v0.20.2 (2026-04-17)


## v0.20.1 (2026-04-17)


## v0.20.0 (2026-04-17)

### Features

- Spawn backoff + worktree recovery from stale branch checkout
  ([`e65f7de`](https://github.com/jsell-rh/hyperloop/commit/e65f7def15f8e9891500a931b6201cbd39f1c2c0))


## v0.19.4 (2026-04-17)


## v0.19.3 (2026-04-17)


## v0.19.2 (2026-04-17)


## v0.19.1 (2026-04-17)


## v0.19.0 (2026-04-17)

### Bug Fixes

- Commit state before merge, don't consume lgtm on gate check
  ([`31393bd`](https://github.com/jsell-rh/hyperloop/commit/31393bd7dda7d82d706f81004e12bed844690b6c))

- Create missing PR when task reaches gate
  ([`2995695`](https://github.com/jsell-rh/hyperloop/commit/2995695bd86d9a06b57ac2d5b067f8451e4bedd5))

### Features

- Human-friendly PR descriptions with gate instructions
  ([`776bba9`](https://github.com/jsell-rh/hyperloop/commit/776bba9be568566e0a2303d3117237a4744bd9d7))

- OpenTelemetry probe adapter for traces and metrics
  ([`21eae35`](https://github.com/jsell-rh/hyperloop/commit/21eae35fb0709914f7dd8e69b4aa001d61646cab))


## v0.18.0 (2026-04-17)


## v0.17.3 (2026-04-17)


## v0.17.2 (2026-04-16)


## v0.17.1 (2026-04-16)


## v0.17.0 (2026-04-16)


## v0.16.1 (2026-04-16)

### Bug Fixes

- Use --frozen in pre-push hook to avoid uv.lock drift
  ([`7873a39`](https://github.com/jsell-rh/hyperloop/commit/7873a39dd2f7e3eafb3167afbfbbd6ac28a8673d))


## v0.16.0 (2026-04-16)


## v0.15.1 (2026-04-16)


## v0.15.0 (2026-04-16)


## v0.14.1 (2026-04-16)

### Bug Fixes

- Crash
  ([`88ef2fb`](https://github.com/jsell-rh/hyperloop/commit/88ef2fba6635b16cc80707269d86be887f2cd1f7))


## v0.14.0 (2026-04-16)


## v0.13.1 (2026-04-16)


## v0.13.0 (2026-04-16)


## v0.12.0 (2026-04-16)

### Features

- Add push_branch to Runtime protocol, detect deadlocked tasks
  ([`c519a3a`](https://github.com/jsell-rh/hyperloop/commit/c519a3adaff33969a24d6fb0b7c0dbaf61714cc2))


## v0.11.0 (2026-04-16)

### Bug Fixes

- Key tmux session to repo name (hyperloop-{repo})
  ([`8902b2d`](https://github.com/jsell-rh/hyperloop/commit/8902b2da46fd0d5422fe0b63261ba836cc65ef5f))

### Features

- TmuxRuntime adapter + restructure adapters/ into subdirectories
  ([`9ca65ad`](https://github.com/jsell-rh/hyperloop/commit/9ca65adad6b223b9262c706c60cbb56e8bfce259))


## v0.10.1 (2026-04-16)


## v0.10.0 (2026-04-16)


## v0.9.2 (2026-04-16)

### Bug Fixes

- Crash on empty commit, rename max_rounds, worktree gitignore, local merge fixes
  ([`2e368ea`](https://github.com/jsell-rh/hyperloop/commit/2e368ea1ccf99c20758a3d3298d604e4ad860286))


## v0.9.1 (2026-04-15)

### Bug Fixes

- **matrix**: Proper UIA two-step registration flow
  ([`97080f9`](https://github.com/jsell-rh/hyperloop/commit/97080f9d6980e914451a59d4b2453c7b5294ed30))


## v0.9.0 (2026-04-15)


## v0.8.1 (2026-04-15)

### Bug Fixes

- **matrix**: Auto-create room independently of registration
  ([`cb4c0a6`](https://github.com/jsell-rh/hyperloop/commit/cb4c0a665a018a6739ff0fb70e333e7f69202e54))


## v0.8.0 (2026-04-15)

### Features

- **matrix**: Auto-register bot and create room
  ([`fc0d2dd`](https://github.com/jsell-rh/hyperloop/commit/fc0d2dd77cfc11f392af635ec516b3f131bc5a81))


## v0.7.0 (2026-04-15)

### Features

- **observability**: Complete spec alignment
  ([`510d01a`](https://github.com/jsell-rh/hyperloop/commit/510d01a65e61149b7a618464f9fcecb691c318fe))


## v0.6.1 (2026-04-15)


## v0.6.0 (2026-04-15)


## v0.5.0 (2026-04-15)

### Features

- Make base_ref configurable via config file and HYPERLOOP_BASE_REF env var
  ([`8efcc0f`](https://github.com/jsell-rh/hyperloop/commit/8efcc0f4292229525e4aa8831561982ad5384220))

- Replace local base/ loading with kustomize-based prompt composition
  ([`9644afb`](https://github.com/jsell-rh/hyperloop/commit/9644afb89a96eee564f997222d86201312bcb63e))


## v0.4.0 (2026-04-15)


## v0.3.0 (2026-04-15)


## v0.2.0 (2026-04-15)


## v0.1.1 (2026-04-15)


## v0.1.0 (2026-04-15)

- Initial Release
