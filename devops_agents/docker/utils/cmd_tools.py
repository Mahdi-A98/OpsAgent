import re
import sys
import time
import pexpect
import queue
import signal
import uuid
import threading
from typing import Optional, Generator, AsyncGenerator, Dict
from enum import StrEnum


PXPIPE_REGISTRY: Dict[str, 'PExpectPipe']  = {}
# PXPIPE_REGISTRY_LOCK = threading.Lock()
# ToDo: decide to apply lock or not as its time consuming
class ShellTypes(StrEnum):
    BASH = "BASH"
    POWERSHELL = "POWERSHELL"
    POSTGRESQL = "POSTGRESQL"
    MYSQL = "MYSQL"
    REDIS = "REDIS"
    MONGO = "MONGO"
    PYTHON = "PYTHON"
    
    @classmethod    
    def get_shell_echo_marker_mapping(cls):
        return {
            cls.BASH: "echo {marker} ",
            cls.POWERSHELL: "Write-Host {marker} ",
            cls.POSTGRESQL: "select \'{marker}\'; ",
            cls.MYSQL: "select \'{marker}\'; ",
            cls.REDIS: "ECHO \"{marker}\" ",
            cls.MONGO: "print(\"{marker}\"); ",
            cls.PYTHON: "print(\"{marker}\"); ",
        }
    
    @classmethod
    def map_shell_llm_marker(cls, shell_type):
        return cls.get_shell_echo_marker_mapping()[shell_type]

    @classmethod
    def map_shell_end_of_command(cls, shell_type):
        return {
            cls.BASH: ";",
            cls.POWERSHELL: ";",
            cls.POSTGRESQL: ";",
            cls.MYSQL: ";",
            cls.REDIS: " ",
            cls.MONGO: ";",
            cls.PYTHON: ";",
        }[shell_type]


class PExpectPipe:
    """
    A wrapper around pexpect.spawn that:
    - Simulates stdin/stdout like subprocess.PIPE
    - Detects command completion using a unique marker
    - Works for both shell and DB shells
    """
    class PipeStatus(StrEnum):
        COMPLETED = "COMPLETED"
        PROCESSING = "PROCESSING"
        FAILED = "FAILED"
        READY = "READY"
        TIMED_OUT = "TIMED OUT"
        

    def __init__(self,
                cmd: str,
                timeout: float = 3,
                marker: Optional[str] = None,
                marker_pattern = ""):
        if sys.platform == "win32":
            from pexpect.popen_spawn import PopenSpawn as Spawn
        else:
            from pexpect import spawn as Spawn

        # Default shell depending on platform
        if cmd is None:
            cmd = "powershell" if sys.platform == "win32" else "bash"
        
        if marker is None:
            marker = f"MARKER_{uuid.uuid4().hex[:8]}"
            marker_pattern = r"MARKER_[a-f0-9]{8}"
        echo_marker_pattern = "|".join([
            f"({ecm.format(marker=marker_pattern).strip()})"for ecm in 
            ShellTypes.get_shell_echo_marker_mapping().values()
        ])
        self.child = Spawn(cmd, encoding="utf-8", timeout=timeout)
        self.timeout = timeout
        self.marker = marker
        self.marker_pattern = marker_pattern
        self.echo_marker_patterns = echo_marker_pattern
        self.current_shell_type = (
            ShellTypes.POWERSHELL 
            if cmd == "powershell"
            else ShellTypes.BASH
        )
        self.id = str(uuid.uuid4())
        self.last_command = ""
        
        # Shared buffer + lock
        self._output_buffer = ""
        self._read_cursor = 0
        # self._buffer_lock = threading.RLock()

        # Optional queue for pub/sub style
        self._output_queue = queue.Queue()
        
        # Background thread to continuously read
        self._stop_reader = threading.Event()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        
        # with PXPIPE_REGISTRY_LOCK:
        PXPIPE_REGISTRY[self.id] = self
        self._wait_for_prompt()
        self.status = self.PipeStatus.READY
        
    # ----------------------
    # Internal reader thread
    # ----------------------
    def _reader_loop(self):
        """Continuously read from child process and append to buffer/queue."""
        while not self._stop_reader.is_set():
            try:
                chunk = self.child.read_nonblocking(1024, timeout=0.1)
                if chunk:
                    # with self._buffer_lock:
                    self._output_buffer += chunk
                    self._output_queue.put(chunk)
            except pexpect.TIMEOUT:
                continue
            except pexpect.EOF:
                break
            except Exception:
                break

    # ----------------------
    # Helper to wait for generic prompts
    # ----------------------
    def _wait_for_prompt(self, shell_type: Optional[str] = None):
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
        self.marker = f"MARKER_{uuid.uuid4().hex[:8]}"
        if append_marker:
            marker_cmd = ShellTypes.map_shell_llm_marker(shell_type).format(marker=self.marker)
            end_of_command_sign = ShellTypes.map_shell_end_of_command(shell_type)
            if not shell_type in (ShellTypes.REDIS,):
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
            elif shell_type == ShellTypes.REDIS:
                print(f"{command=}")
                self.last_command = command
                self.child.sendline(command)
                self.child.sendline(marker_cmd)
        else:
            self.child.send(command)
        
        self.status = self.PipeStatus.PROCESSING

    # ----------------------
    # Non-blocking streaming (consume queue)
    # ----------------------
    async def astream_output(self, timeout:Optional[float] = None) -> AsyncGenerator[dict, None]:
        """Generator yielding chunks as they arrive (for Redis/pub-sub)."""
        timeout = timeout or 0.2
        while True:
            try:
                chunk = self._output_queue.get(timeout=timeout)
                if self.marker and self.marker in chunk:
                    cleaned_chunk = re.sub(self.marker_pattern, "", chunk).strip()
                    self.status = self.PipeStatus.COMPLETED
                    yield {
                        "type": "completion",
                        "content": cleaned_chunk,
                        "command_marker_id": self.marker
                    }
                elif chunk:
                    for line in str(chunk).splitlines():
                        matches = re.findall(self.marker_pattern, line)
                        cleaned_line = re.sub(self.echo_marker_patterns, "", line).strip()
                        cleaned_line = re.sub(self.marker_pattern, "", cleaned_line).strip()
                        yield {
                            "type": "partial_output",
                            "content": cleaned_line,
                            "marker_id": matches[0] if matches else self.marker
                        }
            except queue.Empty:
                if not self._reader_thread.is_alive():
                    break

    def stream_output(self, timeout:Optional[float] = None, overall_timeout=5) -> Generator[dict, None, None]:
        """Generator yielding chunks as they arrive (for Redis/pub-sub)."""
        timeout = timeout or 0.2
        start_time = time.time()
        now = time.time()
        while now - start_time < overall_timeout:
            now = time.time()
            try:
                chunk = self._output_queue.get(timeout=timeout)
                if self.marker and self.marker in chunk:
                    cleaned_chunk = re.sub(self.echo_marker_patterns, "", chunk).strip()
                    cleaned_chunk = re.sub(self.marker_pattern, "", cleaned_chunk).strip()
                    self.status = self.PipeStatus.COMPLETED
                    yield {
                        "type": "completion",
                        "content": cleaned_chunk,
                        "command_marker_id": self.marker
                    }
                    # break
                elif chunk:
                    for line in str(chunk).splitlines():
                        matches = re.findall(self.marker_pattern, line)
                        cleaned_line = re.sub(self.echo_marker_patterns, "", line).strip()
                        cleaned_line = re.sub(self.marker_pattern, "", cleaned_line).strip()
                        yield {
                            "type": "partial_output",
                            "content": cleaned_line,
                            "marker_id": matches[0] if matches else self.marker
                        }
            except queue.Empty:
                if not self._reader_thread.is_alive():
                    break
    
    # ----------------------
    # Blocking read until marker appears
    # ----------------------
    def read_until_marker(self, overall_timeout: Optional[float] = None, include_past = False):
        start_time = time.time()
        buffer_snapshot = ""
        already_yielded = ""
        while True:
            # with self._buffer_lock:
            if include_past:
                buffer_snapshot = self._output_buffer 
            else: 
                buffer_snapshot = self._output_buffer[self._read_cursor:]
            to_yield = buffer_snapshot[len(already_yielded):]
            clean_to_yield = re.sub(self.echo_marker_patterns, "", to_yield).strip()
            clean_to_yield = re.sub(self.marker_pattern, "", clean_to_yield).strip()
            already_yielded += to_yield
            if self.marker and self.marker in buffer_snapshot:
                self._read_cursor += len(to_yield)
                yield clean_to_yield

            if overall_timeout and (time.time() - start_time) > overall_timeout:
                self._read_cursor += len(buffer_snapshot)
                cleaned_buffer = re.sub(self.echo_marker_patterns, "", buffer_snapshot).strip()
                cleaned_buffer = re.sub(self.marker_pattern, "", cleaned_buffer).strip()
                return cleaned_buffer.strip()

            time.sleep(0.05)
            
    # ----------------------
    # Interrupt / cancel command
    # ----------------------
    def interrupt(self):
        try:
            self.child.kill(signal.SIGINT)
        except Exception as e:
            print(f"Interrupt failed: {e}")

    # ----------------------
    # Close session
    # ----------------------
    def close(self):
        self._stop_reader.set()
        try:
            self.child.sendline("exit")
            self.child.kill(signal.SIGTERM)
        except Exception:
            self.child.kill(signal.SIGTERM)
        # with PXPIPE_REGISTRY_LOCK:
        PXPIPE_REGISTRY.pop(self.id, None)

    def __del__(self):
        """
        Destructor to ensure the child process is cleaned up.
        Note: __del__ is not guaranteed to run immediately, so it's a safety net,
        not a replacement for explicitly calling close().
        """
        try:
            if hasattr(self, "child"):
                self.close()
        except Exception:
            # Suppress all exceptions during GC cleanup
            pass



class CMDTools:
    @staticmethod
    def create_shell(cmd: str, timeout=5) -> str:
        """
        Create a new interactive shell session.

        This initializes a persistent command execution environment (like Bash or PowerShell)
        and returns a unique session ID (`pipe_id`) used for all subsequent command calls.

        Args:
            cmd (str): The command used to launch the shell.
                Examples:
                - "bash"
                - "powershell"
                - "mysql"
                - "docker exec -it my_container bash"
            timeout (float, optional): Maximum time (in seconds) to wait for the shell to initialize.
                Default is 5.

        Returns:
            str: A unique `pipe_id` identifying the new shell session.

        Example:
            ```python
            pipe_id = create_shell("bash")
            ```
        """
        pipe = PExpectPipe(cmd, timeout=timeout)
        return pipe.id
    
    @staticmethod
    def run_command(pipe_id: str, command, shell_type=ShellTypes.BASH) -> bool:
        """
        Execute a command within an existing interactive shell session.

        Args:
            pipe_id (str): Unique session identifier returned by `create_shell`.
            command (str): The shell command to execute.
            shell_type (str, optional): The type of shell in which the command
                should run. This affects how command completion markers are appended.
                Supported values include:
                - "BASH"
                - "POWERSHELL"
                - "POSTGRESQL"
                - "MYSQL"
                - "REDIS"
                - "MONGO"
                - "PYTHON"
                Default is "BASH".

        Returns:
            bool: True if the command was successfully sent to the shell.
                Note: This only indicates the command was dispatched; it does not
                guarantee that the command executed successfully.

        Raises:
            ValueError: If the session with `pipe_id` does not exist.

        Example:
            ```python
            # Run a bash command
            run_command(pipe_id, "echo hello world")

            # Run a command in PowerShell
            run_command(pipe_id, "Get-Process", shell_type="POWERSHELL")
            ```
        """
        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        pipe.write(command=command, shell_type=shell_type)
        return True
    
    @staticmethod
    def read_output_from_queue(pipe_id: str, timeout=5) -> str:
        """
        Read buffered queued output from a shell session after a command has run,
        returning all collected stdout as a single string.

        The method collects available stdout text chunks from the specified shell
        until the command completion marker is detected or the timeout is reached.

        Args:
            pipe_id (str): The ID of the shell session.
            timeout (float, optional): Maximum time (in seconds) to wait for output.
                Default is 5.

        Returns:
            str: Concatenated stdout text collected from the shell session.
                Includes all partial output and the final command completion output.

        Raises:
            ValueError: If the session with `pipe_id` does not exist.

        Example:
            ```python
            output = read_output(pipe_id)
            print(output)
            ```
        """

        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        
        return "\n".join(
            str(item.get("content", ""))
            for item in pipe.stream_output(timeout=timeout)
        ).strip()
    
    @staticmethod
    def read_output(pipe_id: str, timeout=5, include_past=False) -> str:
        """
        Read buffered output from a shell session after a command has run,
        returning all collected stdout as a single string.

        The method collects available stdout text chunks from the specified shell
        until the command completion marker is detected or the timeout is reached.

        Args:
            pipe_id (str): The ID of the shell session.
            timeout (float, optional): Maximum time (in seconds) to wait for output.
                Default is 5.

        Returns:
            str: Concatenated stdout text collected from the shell session.
                Includes all partial output and the final command completion output.

        Raises:
            ValueError: If the session with `pipe_id` does not exist.

        Example:
            ```python
            output = read_output(pipe_id)
            print(output)
            ```
        """

        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        
        return "\n".join(
            pipe.read_until_marker(
                overall_timeout=timeout,
                include_past=include_past
            )
        ).strip()
    
    @staticmethod
    def read_output_streaming(pipe_id: str, timeout=5) -> Generator:
        """
        Stream command output from a shell session in real time (synchronous mode).

        Args:
            pipe_id (str): The ID of the target shell session.
            timeout (float, optional): Maximum wait time between chunks. Default is 5 seconds.

        Yields:
            dict: Structured output messages in the form:
            ```json
            {
                "type": "partial_output" | "completion",
                "content": "<stdout text>",
                "marker_id": "<unique command marker>"
            }
            ```

        Example:
            ```python
            for chunk in read_output_streaming(pipe_id):
                print(chunk["content"])
            ```
        """
        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        yield pipe.stream_output(timeout=timeout)
    
    @staticmethod
    async def aread_output_streaming(pipe_id: str, timeout=5) -> AsyncGenerator:
        """
        Asynchronously stream command output from a shell session in real time.

        Args:
            pipe_id (str): The ID of the target shell session.
            timeout (float, optional): Maximum wait time between output chunks. Default is 5 seconds.

        Yields:
            dict: Structured output messages in the form:
            ```json
            {
                "type": "partial_output" | "completion",
                "content": "<stdout text>",
                "marker_id": "<unique command marker>"
            }
            ```

        Example:
            ```python
            async for chunk in aread_output_streaming(pipe_id):
                print(chunk["content"])
            ```
        """
        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        yield pipe.astream_output(timeout=timeout)
        
    @staticmethod
    def check_pipe_status(pipe_id:str) -> str:
        """
        Check the current execution status of a shell session.

        Args:
            pipe_id (str): The ID of the target shell session.

        Returns:
            str: Current session status. Possible values:
                - "READY": Shell is initialized and idle.
                - "PROCESSING": A command is currently executing.
                - "COMPLETED": The last command finished.
                - "FAILED": The session or command failed.
                - "TIMED OUT": A command timed out.

        Example:
            ```python
            status = check_pipe_status(pipe_id)
            print(status)
            ```
        """
        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        return pipe.status
        
    @staticmethod
    def interrupt_pipe_execution(pipe_id:str) -> None:
        """
        Interrupt the currently running command in a shell session.

        This sends a SIGINT (Ctrl+C equivalent) signal to the process.

        Args:
            pipe_id (str): The ID of the target shell session.

        Returns:
            None

        Example:
            ```python
            interrupt_pipe_execution(pipe_id)
            ```
        """
        pipe = PXPIPE_REGISTRY.get(pipe_id)
        if not pipe:
            raise ValueError(f"pipe with {pipe_id=} not found!")
        return pipe.interrupt()
        
    @staticmethod
    def detect_os(pipe_id:str) -> str:
        """
        Detect the operating system running inside the active shell session.

        This executes several standard OS detection commands:
        - Linux: `cat /etc/os-release`
        - Windows: `ver`
        - macOS: `uname -s`

        Args:
            pipe_id (str): The ID of the shell session.

        Returns:
            str: Detected OS name (e.g. "ubuntu", "debian", "alpine",
                "windows", "darwin") or "unknown:<error>" if detection fails.

        Example:
            ```python
            os_name = detect_os(pipe_id)
            print(f"Remote OS: {os_name}")
            ```
        """
        try:
            pipe = PXPIPE_REGISTRY.get(pipe_id)
            if not pipe:
                raise ValueError("pxpipe with this id has not registered or deleted")
            # Linux check
            pipe.write("cat /etc/os-release", shell_type=ShellTypes.BASH)
            output = "\n".join(pipe.read_until_marker())
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
            return "\n".join(pipe.read_until_marker()).strip()

        except Exception as e:
            return f"unknown: {e}"
