import sys
import pexpect

import uuid
from typing import Optional
from enum import StrEnum


PXPIPE_REGISTRY = {}

class PExpectTimeoutError(Exception):
    pass

class PExpectEOFError(Exception):
    pass

class ShellTypes(StrEnum):
    BASH = "BASH"
    POWERSHELL = "POWERSHELL"
    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    REDIS = "REDIS"
    MONGO = "MONGO"
    
    @classmethod
    def map_shell_llm_marker(cls, shell_type):
        return {
            cls.BASH: "echo {marker}",
            cls.POWERSHELL: "Write-Host {marker}",
            cls.POSTGRESQL: "select \'{marker}\';",
            cls.MYSQL: "select \'{marker}\';",
            cls.REDIS: "ECHO {marker};",
            cls.MONGO: "print(\"{marker}\");",
        }[shell_type]

    @classmethod
    def map_shell_end_of_command(cls, shell_type):
        return {
            cls.BASH: ";",
            cls.POWERSHELL: ";",
            cls.POSTGRESQL: ";",
            cls.MYSQL: ";",
            cls.REDIS: ";",
            cls.MONGO: ";",
        }[shell_type]


class PExpectPipe:
    """
    A wrapper around pexpect.spawn that:
    - Simulates stdin/stdout like subprocess.PIPE
    - Detects command completion using a unique marker
    - Works for both shell and DB shells
    """

    def __init__(self, cmd: str, timeout: float = 3, marker: str = "\"LLM_DONE\""):
        if sys.platform == "win32":
            from pexpect.popen_spawn import PopenSpawn as Spawn
        else:
            from pexpect import spawn as Spawn

        # Default shell depending on platform
        if cmd is None:
            cmd = "powershell" if sys.platform == "win32" else "bash"
        self.child = Spawn(cmd, encoding="utf-8", timeout=timeout)
        self.timeout = timeout
        self.marker = marker
        self.current_shell_type = ShellTypes.BASH
        self.id = str(uuid.uuid4())
        PXPIPE_REGISTRY[self.id] = self
        self._wait_for_prompt()
        self.last_command = ""

    # ----------------------
    # Helper to wait for generic prompts
    # ----------------------
    def _wait_for_prompt(self, shell_type: Optional[ShellTypes] = None):
        if shell_type in (ShellTypes.POSTGRESQL,):
            patterns = [r"postgres=[#>]", pexpect.TIMEOUT, pexpect.EOF]
        elif shell_type in (ShellTypes.MYSQL,):
            patterns = [r"mysql>", pexpect.TIMEOUT, pexpect.EOF]
        elif shell_type == ShellTypes.POWERSHELL:
            patterns = [r"> ", pexpect.TIMEOUT, pexpect.EOF]
        else:
            # bash / generic
            patterns = [r"\$ ", r"# ", r"> ", pexpect.TIMEOUT, pexpect.EOF]

        idx = self.child.expect(patterns, timeout=self.timeout)
        return self.child.before, idx


    # ----------------------
    # Send a command
    # ----------------------
    def write(
        self,
        command: str,
        append_marker: bool = True,
        shell_type: ShellTypes = ShellTypes.BASH):
        """
        command: string to run
        append_marker: whether to append marker to detect completion
        shell_type: shell type that the command would execute in
        """
        if append_marker:
            marker_cmd = ShellTypes.map_shell_llm_marker(shell_type).format(marker=self.marker)
            end_of_command_sign = ShellTypes.map_shell_end_of_command(shell_type)

            if shell_type == ShellTypes.POWERSHELL:
                # PowerShell: always use semicolon to separate commands
                if command.strip():
                    command = f"{command}{end_of_command_sign} {marker_cmd}"
                else:
                    command = marker_cmd
            else:
                # Bash and DB shells: append ; if missing, then marker
                if command.strip() and not command.strip().endswith(end_of_command_sign):
                    command += end_of_command_sign
                command += " " + marker_cmd
        print(f"{command=}")
        self.last_command = command
        self.child.sendline(command)

    # ----------------------
    # Read output until marker appears
    # ----------------------
    def read_until_marker(self, timeout: Optional[float] = None):
        timeout = timeout or self.timeout
        striped_marker = self.marker.strip("\"")
        patterns = [striped_marker, pexpect.TIMEOUT, pexpect.EOF]

        while True:
            idx = self.child.expect(patterns, timeout=timeout)
            output = str(self.child.before).strip()
            print(f"{output=}\n{self.last_command=}")
            if self.last_command.replace(self.marker, "") in output:
                continue
            if idx == 0:  # Marker detected
                yield output.replace(self.marker.strip("\""), "").strip()
                break
            elif idx == 1:  # Timeout
                raise PExpectTimeoutError(output)
            elif idx == 2:  # EOF
                raise PExpectEOFError(output)



    # ----------------------
    # Close session
    # ----------------------
    def close(self):
        self.child.sendline("exit")
        self.child.close()

def detect_os(pxpipe_id:str) -> str:
    """
    Detects the OS inside the current shell session.
    Returns a string like 'ubuntu', 'debian', 'alpine', 'centos', 'windows', 'darwin', etc.
    """
    try:
        pipe = PXPIPE_REGISTRY.get(pxpipe_id)
        if not pipe:
            raise ValueError("pxpipe with this id has not registered or deleted")
        # Linux check
        pipe.write("cat /etc/os-release", shell_type=ShellTypes.BASH)
        output = pipe.read_until_marker()
        if "ID=" in output:
            for line in output.splitlines():
                if line.startswith("ID="):
                    return line.split("=")[1].strip().strip('"')
        
        # Windows check
        pipe.write("ver", shell_type=ShellTypes.POWERSHELL)
        output = pipe.read_until_marker()
        if "Windows" in output:
            return "windows"

        # macOS check
        pipe.write("uname -s", shell_type=ShellTypes.BASH)
        output = pipe.read_until_marker()
        if "Darwin" in output:
            return "darwin"

        # Generic fallback
        pipe.write("uname -a", shell_type=ShellTypes.BASH)
        return pipe.read_until_marker().strip()

    except Exception as e:
        return f"unknown: {e}"
