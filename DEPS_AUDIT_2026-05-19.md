# Dependency Audit - 2026-05-19

Scope: dependencies declared in `pyproject.toml` under `[project].dependencies`, `[project.optional-dependencies].mac`, and `[dependency-groups].dev`.

Method: attempted `python3 -m pip index versions`, but the local sandbox could not resolve PyPI DNS (`nodename nor servname provided`). Latest versions below were verified from the corresponding PyPI project pages on 2026-05-19. No packages were installed and no dependency files were modified.

## Major Or Minor Updates Available

| Package | Current | Latest | Update type | Risk | Recommendation |
| --- | ---: | ---: | --- | --- | --- |
| fastapi | 0.115.0 | 0.136.1 | minor | medium | Upgrade with API/server smoke tests because pre-1.0 minor releases can still change behavior. |
| google-api-python-client | 2.194.0 | 2.196.0 | minor | low | Safe routine bump; keep current Google API flows covered by integration tests. |
| google-auth-oauthlib | 1.3.1 | 1.4.0 | minor | medium | Upgrade deliberately and re-test OAuth browser/token refresh flows. |
| mcp[cli] | 1.10.0 | 1.27.1 | minor | medium | Upgrade in a focused PR and re-test any MCP client/server command paths. |
| mlx-lm | 0.21.0 | 0.31.3 | minor | medium | Upgrade only on macOS with a local model load/generation smoke test. |
| numpy | 1.26.0 | 2.4.6 | major | high | Do not broad-bump casually; first confirm all numerical/ML transitive dependencies support NumPy 2.x. |
| outlines | 0.1.0 | 1.3.0 | major | high | Treat as a migration; inspect API usage and run structured-generation tests before adopting. |
| pydantic | 2.12.5 | 2.13.4 | minor | medium | Upgrade with model validation and FastAPI request/response tests. |
| pyobjc-framework-Quartz | 10.0 | 12.1 | major | high | Align with the rest of PyObjC 12.1 on macOS, then test screen/Quartz automation paths. |
| rich | 14.3.3 | 15.0.0 | major | medium | Upgrade with TUI rendering checks, especially where Textual/Rich output is asserted. |
| uvicorn | 0.34.0 | 0.47.0 | minor | medium | Upgrade with ASGI startup/shutdown and local server smoke tests. |
| hypothesis | 6.151.12 | 6.152.9 | minor | low | Safe routine dev-tool bump; expect possible new generated examples to expose latent test bugs. |
| pre-commit | 4.5.1 | 4.6.0 | minor | low | Safe routine dev-tool bump; run hooks once after updating. |

## Full Assessment

| Package | Current | Latest | Risk | Recommendation |
| --- | ---: | ---: | --- | --- |
| fastapi | 0.115.0 | 0.136.1 | medium | Upgrade with API/server smoke tests because pre-1.0 minor releases can still change behavior. |
| google-api-python-client | 2.194.0 | 2.196.0 | low | Safe routine bump; keep current Google API flows covered by integration tests. |
| google-auth-oauthlib | 1.3.1 | 1.4.0 | medium | Upgrade deliberately and re-test OAuth browser/token refresh flows. |
| google-generativeai | 0.8.6 | 0.8.6 | high | No version bump exists, but the package is marked legacy/deprecated; plan migration to the newer Google Gen AI SDK. |
| httpx | 0.28.0 | 0.28.1 | low | Patch bump is safe; run HTTP client tests if changing. |
| loguru | 0.7.3 | 0.7.3 | low | Already current; no action needed. |
| mcp[cli] | 1.10.0 | 1.27.1 | medium | Upgrade in a focused PR and re-test any MCP client/server command paths. |
| mlx-lm | 0.21.0 | 0.31.3 | medium | Upgrade only on macOS with a local model load/generation smoke test. |
| mlx-whisper | 0.4.0 | 0.4.3 | low | Patch bump is reasonable; verify a short transcription on macOS. |
| numpy | 1.26.0 | 2.4.6 | high | Do not broad-bump casually; first confirm all numerical/ML transitive dependencies support NumPy 2.x. |
| outlines | 0.1.0 | 1.3.0 | high | Treat as a migration; inspect API usage and run structured-generation tests before adopting. |
| pydantic | 2.12.5 | 2.13.4 | medium | Upgrade with model validation and FastAPI request/response tests. |
| pyobjc-framework-ApplicationServices | 12.1 | 12.1 | low | Already current; keep paired with other PyObjC framework packages. |
| pyobjc-framework-Quartz | 10.0 | 12.1 | high | Align with the rest of PyObjC 12.1 on macOS, then test screen/Quartz automation paths. |
| python-multipart | 0.0.24 | 0.0.29 | low | Patch bump is reasonable; test file/form upload endpoints. |
| rich | 14.3.3 | 15.0.0 | medium | Upgrade with TUI rendering checks, especially where Textual/Rich output is asserted. |
| sounddevice | 0.5.0 | 0.5.5 | low | Patch bump is reasonable; verify audio device enumeration/recording on macOS. |
| textual | 8.2.3 | 8.2.7 | low | Patch bump is reasonable; run TUI smoke tests. |
| uvicorn | 0.34.0 | 0.47.0 | medium | Upgrade with ASGI startup/shutdown and local server smoke tests. |
| bandit | 1.9.4 | 1.9.4 | low | Already current; no action needed. |
| hypothesis | 6.151.12 | 6.152.9 | low | Safe routine dev-tool bump; expect possible new generated examples to expose latent test bugs. |
| pre-commit | 4.5.1 | 4.6.0 | low | Safe routine dev-tool bump; run hooks once after updating. |
| pyright | 1.1.408 | 1.1.409 | low | Patch bump is safe; run type checking after updating. |
| pytest | 9.0.3 | 9.0.3 | low | Already current; no action needed. |
| pytest-cov | 7.1.0 | 7.1.0 | low | Already current; no action needed. |
| python-dotenv | 1.2.2 | 1.2.2 | low | Already current; no action needed. |
| ruff | 0.15.10 | 0.15.13 | low | Patch bump is safe; run lint after updating. |

## Sources

- PyPI project pages checked: `fastapi`, `google-api-python-client`, `google-auth-oauthlib`, `google-generativeai`, `httpx`, `loguru`, `mcp`, `mlx-lm`, `mlx-whisper`, `numpy`, `outlines`, `pydantic`, `pyobjc-framework-ApplicationServices`, `pyobjc-framework-Quartz`, `python-multipart`, `rich`, `sounddevice`, `textual`, `uvicorn`, `bandit`, `hypothesis`, `pre-commit`, `pyright`, `pytest`, `pytest-cov`, `python-dotenv`, and `ruff`.
