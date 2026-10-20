"""
Harbor agents for the Khoros A/B benchmark: Harbor's Claude Code agent with Khoros installed.

Only Khoros's runtime surfaces are mounted read-only into the task container (never the whole repo, which holds
benchmark solutions): /opt/khoros/{bin,.harness,plugin,CLAUDE.md}. run_harbor.py passes the mounts.

- KhorosClaudeCode: `khoros` on PATH, CLAUDE.md in the task's working directory (with `bin/khoros` rewritten to
  `khoros`, since the task repo has no bin/), `khoros init`, and `--plugin-dir /opt/khoros/plugin`.
- KhorosFactoryClaudeCode: the same, plus a preamble asking for the full Khoros workflow (the `khoros-factory` arm).

Vanilla runs use Harbor's stock `claude-code` agent, so both arms share its install, flags and auth handling.
"""

from harbor.agents.installed.claude_code import ClaudeCode

KHOROS_ROOT = "/opt/khoros"

INSTALL_KHOROS = (
    "set -e; "
    "if ! command -v python3 >/dev/null 2>&1; then "
    "  (apt-get update -qq && apt-get install -y -qq python3) >/dev/null 2>&1 "
    "  || apk add --no-cache python3 >/dev/null 2>&1 "
    "  || (yum install -y python3 || dnf install -y python3) >/dev/null 2>&1; "
    "fi; "
    "mkdir -p $HOME/.local/bin; "
    f"ln -sf {KHOROS_ROOT}/bin/khoros $HOME/.local/bin/khoros; "
    f"ln -sf {KHOROS_ROOT}/bin/khoros $HOME/.local/bin/harness; "
    'export PATH="$HOME/.local/bin:$PATH"; '
    "khoros --help >/dev/null"
)

# Runs in the task's working directory, right before the agent starts.
PREPARE_WORKSPACE = (
    'export PATH="$HOME/.local/bin:$PATH"; '
    f"sed 's#bin/khoros#khoros#g; s#bin/harness#harness#g' {KHOROS_ROOT}/CLAUDE.md > CLAUDE.md && "
    "khoros init --profile generic >/dev/null"
)

FACTORY_PREAMBLE = (
    "Work through this repository's Khoros workflow as described in CLAUDE.md: start by triaging the request "
    "with `khoros triage`, and if it is T2 or T3, write the recommended spec, register the work as tasks on the "
    "blackboard, and claim, submit and approve them. Run `khoros verify --with-tests` before finishing.\n\n"
)


class KhorosClaudeCode(ClaudeCode):
    async def install(self, environment) -> None:
        await super().install(environment)
        await self.exec_as_agent(environment, command=INSTALL_KHOROS)

    def build_cli_flags(self) -> str:
        flags = super().build_cli_flags()
        return f"{flags} --plugin-dir {KHOROS_ROOT}/plugin".strip()

    def _instruction(self, instruction: str) -> str:
        return instruction

    async def run(self, instruction, environment, context) -> None:
        await self.exec_as_agent(environment, command=PREPARE_WORKSPACE)
        await super().run(self._instruction(instruction), environment, context)


class KhorosFactoryClaudeCode(KhorosClaudeCode):
    def _instruction(self, instruction: str) -> str:
        return FACTORY_PREAMBLE + instruction


# --- npm-installed variants -------------------------------------------------------------------------------------
# On Apple Silicon, x86-only task images (SWE-rebench ships no Dockerfiles for its prebuilt images) run under
# Rosetta, where Claude Code's native installer crashes but the npm package runs. Node comes from the official
# tarball because distro packages are often too old. Every arm of such a run uses these classes, vanilla included,
# so the install stays identical across arms.

NODE_VERSION = "22.11.0"
CLAUDE_CODE_VERSION = "2.1.303"

INSTALL_NODE_AND_CLAUDE = (
    "set -e; "
    'case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch"; exit 1 ;; esac; '
    "mkdir -p /opt/node && "
    f"curl -fsSL https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-$arch.tar.gz "
    "| tar -xz -C /opt/node --strip-components=1 && "
    "mkdir -p $HOME/.local/bin && "
    'export PATH="/opt/node/bin:$HOME/.local/bin:$PATH" && '
    f"npm install -g --prefix $HOME/.local @anthropic-ai/claude-code@{CLAUDE_CODE_VERSION} >/dev/null && "
    "echo 'export PATH=\"/opt/node/bin:$HOME/.local/bin:$PATH\"' >> ~/.bashrc && "
    "claude --version"
)


class NpmClaudeCode(ClaudeCode):
    async def install(self, environment) -> None:
        await self.ensure_system_dependencies(environment, ("curl", "bash"))
        await self.exec_as_agent(environment, command=INSTALL_NODE_AND_CLAUDE)

    async def run(self, instruction, environment, context) -> None:
        # Make node visible to the agent's shell commands as well as to the claude launcher
        await self.exec_as_agent(environment, command="ln -sf /opt/node/bin/node /usr/local/bin/node 2>/dev/null || true")
        await super().run(instruction, environment, context)


class NpmKhorosClaudeCode(KhorosClaudeCode, NpmClaudeCode):
    """MRO: KhorosClaudeCode.install -> NpmClaudeCode.install, so Khoros is installed on top of the npm install."""


class NpmKhorosFactoryClaudeCode(KhorosFactoryClaudeCode, NpmKhorosClaudeCode):
    pass
