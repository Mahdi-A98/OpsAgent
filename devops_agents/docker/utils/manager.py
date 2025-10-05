import io
import sys
import uuid
import time
import queue
import docker
import signal
import platform
import subprocess
import threading
from enum import StrEnum
from docker.errors import DockerException
from typing import List, Dict, Optional
from core.schemas import TaskOutput



# Thread-safe dictionary for storing runners
# ToDo cache and clean after a time and empty_log
RUNNER_REGISTRY: Dict[str, "DockerTaskRunner"] = {}


class TaskStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    FAILED = "FAILED"
    DONE = "DONE"
    PROCESSING = "PROCESSING"

class DockerTaskRunner:    
    
    def __init__(self, container_name: str, command: List[str], use_sdk: bool = True):
        self.container_name = container_name
        self.command = command
        self.use_sdk = use_sdk
        self._stop_flag = False
        self.thread = None
        self.status: TaskStatus = TaskStatus.NOT_STARTED
        self.id = str(uuid.uuid4())
        
        self.sub_commands = []
        if not isinstance(command, list):
            self.sub_commands = self.command.split()
        else:
            for sb in self.command:
                self.sub_commands.extend(sb.split())
        
        if self.use_sdk:
            if platform.system() == "Windows":
                base_url = "npipe:////./pipe/docker_engine"
            else:
                base_url = "unix://var/run/docker.sock"

            self.client = docker.DockerClient(base_url=base_url)
            self.api_client = docker.APIClient(base_url=base_url)
            
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
        while finished < 2:  # wait for both stdout and stderr
            try:
                line = q.get(timeout=5)
                if line is None:
                    finished += 1
                else:
                    yield line
            except queue.Empty:
                # timeout reached, no more lines
                break

    def start(self):
        """Start the task and stream logs."""
        if self.use_sdk:
            container = self.client.containers.get(self.container_name)
            self.exec_id = self.api_client.exec_create(
                container.id, cmd=self.sub_commands, tty=True
            )['Id']
            self.thread = threading.Thread(target=self.stream_sdk_logs)
            self.thread.start()
            self.status = TaskStatus.PROCESSING
            self.thread.join()
            self.status = TaskStatus.DONE
        else:
            cmd = ["docker", "exec", "-it", self.container_name] + self.sub_commands
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.status = TaskStatus.PROCESSING
            # self.stream_subprocess_logs()
            status_code = self.proc.wait()
            self.status = TaskStatus.DONE if status_code ==0 else TaskStatus.FAILED
            
    def get_output(self):
        streamer = self.stream_sdk_logs if self.use_sdk else self.stream_subprocess_logs
        return "".join(list(streamer()))            


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
    _client = None
    
    @classmethod
    def _get_docker_client(cls):
        if cls._client:
            return cls._client
        try:
            cls._client = docker.from_env()
            return cls._client
        except DockerException:
            raise Exception("Cannot connect to docker may docker engine is not running!")        

    @staticmethod
    def run_container(
                    image: str,
                    name: str | None = None,
                    ports: dict | None = None,
                    env: dict[str, str] | list[str] | None = None,
                    volumes: list[str] | None = None,
                    detach: bool = True,
                ) -> TaskOutput:
        """Run a new container based on ContainerSpec."""
        try:
            container = DockerManager._get_docker_client().containers.run(
                image=image,
                name=name,
                ports=ports,
                environment=env,
                volumes=volumes,
                detach=True,
            )
            return TaskOutput(success=True, output=f"Container {container.name} started")
        except Exception as e:
            return TaskOutput(success=False, output="", error=str(e))

    @staticmethod
    def list_available_containers(all: bool = True) -> TaskOutput:
        """List all containers."""
        try:
            containers = DockerManager._get_docker_client().containers.list(all=all)
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
        runner_id = runner.id
        RUNNER_REGISTRY[runner_id] = runner
        threading.Thread(target=runner.start, args=(), daemon=True).start()
        return runner_id
    
    @staticmethod
    def get_task_runner_output(runner_id: str):
        """
        return task output of runner with given runner_id
        """
        runner = RUNNER_REGISTRY.get(runner_id)
        if not runner:
            raise ValueError(f"Runner {runner_id} not found")
        return runner.get_output()
    
    @staticmethod
    def get_task_runner_status(runner_id: str):
        """
        return task output of runner with given runner_id
        """
        runner = RUNNER_REGISTRY.get(runner_id)
        if not runner:
            raise ValueError(f"Runner {runner_id} not found")
        return runner.status
    
        
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
        return DockerManager._get_docker_client().containers.create(image=image, name=name, *args, **kwargs)
    
    @staticmethod
    def docker_pull_image(image: str) -> str:
        """
        Pull a Docker image from a registry.

        Args:
            image (str): Docker image name, e.g., 'nginx:latest'.

        Returns:
            str: Status of the pull operation.
        """
        try:
            pulled_image = DockerManager._get_docker_client().images.pull(image)
            return f"✅ Successfully pulled image: {pulled_image.tags}"
        except Exception as e:
            return f"❌ Failed to pull image '{image}': {str(e)}"
        
    @staticmethod
    def get_list_of_images(repository_name:Optional[str]=None, all=True):
        """
        gets list of images. if repository_name is specified it is used as a filter
        """
        try:
            images = DockerManager.client.images.list(name=repository_name, all=all)
            return f"✅ Successfully list of images: {[str(images)]}"
        except Exception as e:
            return f"❌ Failed to fetch images lists': {str(e)}"
