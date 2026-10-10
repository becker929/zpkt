"""The hard rules on the studio session's shell commands."""

import pytest

from harness.studio.guard import bash_hook, check


@pytest.mark.parametrize("command", [
    "sudo rm -rf /var/x",
    "cd /tmp && sudo make install",
    "echo $(sudo whoami)",
    "git push --force origin p2-studio",
    "git push -f origin x",
    "git push origin +p2-studio",
    "git push --force-with-lease",
    "git push origin main",
    "git push -u origin HEAD:main",
    "git push origin master && echo done",
    "security find-generic-password -s zpkt-rig-token -a me -w",
    "security dump-keychain",
    "diskutil eraseDisk APFS X disk4",
    "dd if=/dev/zero of=/dev/disk4 bs=1m",
    "rm -rf /",
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf ~/Desktop",
    "rm -fr $HOME/Music",
    "rm -r -f /Users",
    "rm -rf ..",
    'rm -rf "$HOME"',
])
def test_refused(command):
    assert check(command), command


@pytest.mark.parametrize("command", [
    "echo sudo is a word",
    "git push -u origin p2-studio",
    "git push origin feature/main-menu",
    "git status && git log --oneline -5",
    "security find-generic-password -s zpkt-rig-token",          # attributes only, not the secret
    "rm -rf ./build",
    "rm -rf /tmp/studio-x",
    "rm -rf ~/_agent_scratch/studio/tmp/abc",
    "rm -rf ~/Desktop/zpkt/lib/harness/.pytest_cache",
    "rm notes.txt",
    "uv run hands live ping",
    "ls -la ~/Desktop",
])
def test_allowed(command):
    assert check(command) is None, command


async def test_the_hook_denies_with_a_reason_and_ignores_other_tools():
    out = await bash_hook({"tool_name": "Bash", "tool_input": {"command": "sudo ls"}}, "t1", None)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and "sudo" in decision["permissionDecisionReason"]
    assert await bash_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "t2", None) == {}
