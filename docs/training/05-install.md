# 5. Install in your approved assistant

[Learning guide](README.md) · [Previous: review](04-review.md) · [Next: launch](06-launch.md)

**Outcome:** your assistant can find the complete accelerator and identify its active copy. Installation needs no warehouse credentials.

**Official setup documentation checked October 28, 2026; native installations were not exercised.**

## 1. Check what you already have

Use your organization’s approved assistant. Ask your support contact if one is not available.

Have a technical partner confirm the maintained runtime: **Python 3.12 on macOS or Linux (POSIX)**, helper dependencies and file/execution permissions. Windows needs a separately qualified Linux environment, such as WSL or a remote environment.

Cloud skill discovery does not prove helper execution or file access. Keep those checks separate.

## 2. Prepare a separate learning folder

Use a reviewed repository copy with its revision (version identifier) recorded. Open your assistant in a new `dma-learning` folder **outside customer repositories**.

The required folder is `skills/data-model-accelerator` from the reviewed copy. Keep its entire contents, including `SKILL.md`, scripts, references, and supporting files. Copying only the Markdown instructions is incomplete. Add optional stage skill folders only when needed, beside the main folder under the same skills parent.

Paths below are relative to your learning folder, except Databricks workspace paths. Compare existing installations before replacing anything.

## 3. Follow one host path

### Codex

Codex documents `$skill-installer` for repository skills. If available, ask it to install the **complete reviewed folder at the recorded revision** into `.agents/skills/data-model-accelerator/`; have it identify its destination first. If that installer cannot target your learning folder, manually copy the complete folder there instead. Open that workspace, then select the skill through the desktop skill picker or `/skills` in the CLI. Restart if it is missing. [Official Codex skills guide](https://learn.chatgpt.com/docs/build-skills)

### Claude Code

Copy the complete main folder to `.claude/skills/data-model-accelerator/`. Start a local Claude Code session in your learning folder and invoke `/data-model-accelerator`. If the skills directory was created after the session started, use `/reload-skills`. This is the local Claude Code path; cloud sessions have separate loading rules. [Official Claude Code skills guide](https://code.claude.com/docs/en/skills)

### Gemini CLI

Use its native installer from your learning folder. Ask your technical partner to substitute the reviewed folder's actual path:

```text
gemini skills install /reviewed-copy/skills/data-model-accelerator --scope workspace
```

Keep the installation confirmation enabled. Then use `/skills reload` and `/skills list`. Ask Gemini to activate `data-model-accelerator`, and check the folder shown in its activation prompt. The manual fallback is the complete folder at `.gemini/skills/data-model-accelerator/`. [Official Gemini skills guide](https://geminicli.com/docs/cli/skills/)

### Snowflake Cortex Code / CoCo Desktop

For Desktop, copy the complete folder to `.snowflake/cortex/skills/data-model-accelerator/` and open the learning workspace. Alternatively, use **Agent Settings > Skills > Local Skills > +**, selecting a parent folder containing your reviewed skill folders. This user-level registration is shared with the CLI. Confirm the skill appears and look for “Using skill” when invoked. [Official CoCo Desktop skills guide](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-desktop/skills)

For CLI-only project installation, its documentation specifies `.cortex/skills/data-model-accelerator/`; check `/skill list`, then ask it to use the skill. [Official CoCo CLI guide](https://docs.snowflake.com/en/user-guide/cortex-code/extensibility)

Cortex Agents is a separate cloud route with different supporting-file restrictions. Do not flatten this package or assume a stage upload qualifies its nested helpers for execution. [Cortex Agents limitations](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-skills#limitations)

### Databricks Genie Code

Have your technical partner place the complete reviewed folders in a personal workspace learning area, for example `/Users/{username}/dma-learning/skills/`. In Genie Code **Settings**, enter that parent workspace path and choose **Add folder**. Alternatively, copy the complete main folder to `/Users/{username}/.assistant/skills/data-model-accelerator/`. These are Databricks workspace paths, not your laptop's folders. Start a new chat and `@` mention the skill. Helper execution still needs separate qualification. [Official Genie Code skills guide](https://docs.databricks.com/aws/en/genie-code/skills)

## 4. Confirm the selected copy

Send this request after selecting the skill:

> Use data-model-accelerator. Identify the exact SKILL.md path you loaded. Report the reviewed source revision, or say if it is unavailable. Read its installation reference and identify a referenced helper file you can access. Compare this installed copy with the reviewed copy using check_installation.py. Report file identity and runtime availability separately. Do not change global settings or overwrite another installation.

The preflight compares file identity; it **does not prove the host loaded the skill**. Check the host's invocation indication and the assistant's specific path/reference response too. A copied folder may need the source revision recorded separately.

## 5. Resolve gaps and continue

If the skill is absent, check folder nesting, exact `SKILL.md` spelling, the open workspace, and whether the skill is disabled. If two copies appear, identify the selected path before continuing. Missing Python, dependencies, permissions, or inaccessible references means setup needs your technical partner's help; do not bypass controls.

**Checkpoint:** you can name the selected copy, its reviewed source, and any remaining execution gap. Continue to [launch your first task](06-launch.md); synthetic practice is optional.
