import io
import sys
import uuid
import time
import queue
import docker
import signal
import subprocess
import threading
from typing import List, Dict, Optional, Generator
from core.schemas import TaskOutput
from devops_agents.docker.schemas import ContainerSpec



# Thread-safe dictionary for storing runners
RUNNER_REGISTRY: Dict[str, "DockerTaskRunner"] = {}


class DockerTaskRunner:
    def __init__(self, container_name: str, command: List[str], use_sdk: bool = True):
        self.container_name = container_name
        self.command = command
        self.use_sdk = use_sdk
        self._stop_flag = False
        self.thread = None

        if self.use_sdk:
            self.client = docker.from_env()
            self.api_client = docker.APIClient(base_url='unix://var/run/docker.sock')
            self.exec_id = None
        else:
            self.proc: Optional[subprocess.Popen] = None

    def stream_sdk_logs(self):
        logs = self.api_client.exec_start(self.exec_id, stream=True, demux=True)
        for stdout, stderr in logs:
            if self._stop_flag:
                break
            if stdout:
                yield stdout.decode()
            if stderr:
                yield stderr.decode()

    def stream_subprocess_logs(self):
        """
        Stream both stdout and stderr from subprocess concurrently,
        yielding lines as they arrive for UI streaming.
        """
        q = queue.Queue()
        
        def enqueue_logs(pipe: io.TextIOBase, prefix="") -> None:
            for line in iter(pipe.readline, ''):
                if self._stop_flag:
                    break
                q.put(f"{prefix}{line}")
            q.put(None) # signal EOF for this pipe
        if self.proc:
            threading.Thread(target=enqueue_logs, args=(self.proc.stdout, "")).start()
            threading.Thread(target=enqueue_logs, args=(self.proc.stderr, "ERROR")).start()
        
        finished = 0
        while finished <= 2:
            for line in q.get():
                yield line
            finished += 1

    def start(self, runner_id):
        """Start the task and stream logs."""
        if self.use_sdk:
            container = self.client.containers.get(self.container_name)
            self.exec_id = self.api_client.exec_create(
                container.id, cmd=self.command, tty=True
            )['Id']
            self.thread = threading.Thread(target=self.stream_sdk_logs)
            self.thread.start()
            self.thread.join()
        else:
            cmd = ["docker", "exec", "-it", self.container_name] + self.command
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.stream_subprocess_logs()
            self.proc.wait()
            
        RUNNER_REGISTRY.pop(runner_id, None)


    def interrupt(self, force_timeout: int = 3):
        """Interrupt the running task with graceful stop, then optional force kill."""
        self._stop_flag = True
        stopped = True
        if self.use_sdk and self.exec_id:
            print("⛔ Sending SIGINT to SDK exec...")
            try:
                # Graceful stop
                self.api_client._post(f"/exec/{self.exec_id}/kill", data={"signal": "SIGINT"})

                # Wait for process to exit
                start = time.time()
                while time.time() - start < force_timeout:
                    # Check if exec is still running
                    exec_inspect = self.api_client.exec_inspect(self.exec_id)
                    if not exec_inspect['Running']:
                        print("✅ Process exited after SIGINT")
                        return stopped
                    time.sleep(0.1)

                # Force kill if still running
                print("💀 SIGINT did not stop the process, sending SIGKILL...")
                self.api_client._post(f"/exec/{self.exec_id}/kill", data={"signal": "SIGKILL"})
            except Exception as e:
                stopped = False
                print("Error interrupting exec:", e)

        elif self.proc:
            print("⛔ Sending SIGINT to subprocess...")
            try:
                self.proc.send_signal(signal.SIGINT)
                try:
                    self.proc.wait(timeout=force_timeout)
                    print("✅ Subprocess exited after SIGINT")
                except subprocess.TimeoutExpired:
                    if self.proc.poll() is None:
                        print("💀 Subprocess did not exit, force killing...")
                        self.proc.kill()
            except Exception as e:
                stopped = False
                print("Error interrupting subprocess:", e)
        return stopped



class DockerManager:
    client = docker.from_env()

    @staticmethod
    def run_container(spec: ContainerSpec) -> TaskOutput:
        """Run a new container based on ContainerSpec."""
        try:
            container = DockerManager.client.containers.run(
                image=spec.image,
                name=spec.name,
                ports=spec.ports,
                environment=spec.env,
                volumes=spec.volumes,
                detach=True,
            )
            return TaskOutput(success=True, output=f"Container {container.name} started")
        except Exception as e:
            return TaskOutput(success=False, output="", error=str(e))

    @staticmethod
    def list_available_containers(all: bool = True) -> TaskOutput:
        """List all containers."""
        try:
            containers = DockerManager.client.containers.list(all=all)
            output = [
                {"id": c.short_id, "name": c.name, "status": c.status, "image": c.image.tags}
                for c in containers
            ]
            return TaskOutput(success=True, output=str(output))
        except Exception as e:
            return TaskOutput(success=False, output="", error=str(e))

    @staticmethod
    def run_task(container_name: str, command: List[str], use_sdk: bool = True) -> str:
        """
        Run a long task inside a container with live logs and interrupt.
        Returns the DockerTaskRunner instance so UI can call .interrupt()
        """
        runner = DockerTaskRunner(container_name, command, use_sdk=use_sdk)
        runner_id = str(uuid.uuid4())
        RUNNER_REGISTRY[runner_id] = runner
        threading.Thread(target=runner.start, args=(runner_id,), daemon=True).start()
        return runner_id
    
    @staticmethod
    def stop_runner(runner_id: str):
        """
        stops task runner with given runner_id and return the status of interruption
        """
        runner = RUNNER_REGISTRY.get(runner_id)
        if not runner:
            raise ValueError(f"Runner {runner_id} not found")
        stopped = runner.interrupt()
        if stopped:
            return f"runner \"{runner_id}\" stopped successfully"
        return f"failed to stop runner \"{runner_id}\""
        
    @staticmethod
    def create_container(image, name, *args, **kwargs):
        return DockerManager.client.containers.create(image=image, name=name, *args, **kwargs)

