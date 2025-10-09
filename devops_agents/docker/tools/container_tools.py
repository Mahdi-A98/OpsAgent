from devops_agents.docker.utils.manager import DockerManager
from core.utils import create_structured_tool
from devops_agents.docker.schemas import ContainerSpec, ContainerTask


run_container_tool = create_structured_tool(
    func = DockerManager.run_container,
    name = "run_container",
    description="runs docker containers with specified parameter",
    args_schema=ContainerSpec,
    log=True,
    log_colour="orange"
)

run_task_on_container_tool = create_structured_tool(
    func = DockerManager.run_task,
    name = "run_task_container",
    description="""
    runs commands on docker containers and creates a runner object that executes asynchronously.
    returns runner_id so can check status and logs of task using this runner id.
    """,
    args_schema=ContainerTask,
    log=True,
    log_colour="white"
)

get_task_runner_output_tool = create_structured_tool(
    func = DockerManager.get_task_runner_output,
    name = "get_task_runner_output",
    description="""output result of task runner with given runner_id""",
    log=True,
    log_colour="white"
)

check_task_runner_status_tool = create_structured_tool(
    func = DockerManager.get_task_runner_status,
    name = "check_task_runner_status",
    description="""returns the status of task runner with given runner_id""",
    log=True,
    log_colour="white"
)

stop_task_runner_tool = create_structured_tool(
    func = DockerManager.stop_runner,
    name = "stop_task_runner",
    description="""stops task runner with given runner_id
    and return the status of interruption""",
    log=True,
    log_colour="red"
)

get_list_of_containers_tool = create_structured_tool(
    func = DockerManager.list_available_containers,
    name = "list_available_containers",
    description="""lists all container""",
    log=True,
    log_colour="purple"
)

get_list_of_images_tool = create_structured_tool(
    func = DockerManager.get_list_of_images,
    name = "get_list_of_docker_images",
    log=True,
    log_colour="purple"
)

start_docket_container_tool = create_structured_tool(
    func = DockerManager.start_container,
    name = "start_docker_container",
    log=True,
    log_colour="purple"
)

stop_docker_container_tool = create_structured_tool(
    func = DockerManager.stop_container,
    name = "stop_docker_container_tool",
    log=True,
    log_colour="purple"
)

pull_docker_image_tool = create_structured_tool(
    func = DockerManager.docker_pull_image,
    name = "pull_docker_image",
    log=True,
    log_colour="purple"
)


all_container_tools = [
    run_container_tool,
    run_task_on_container_tool,
    stop_task_runner_tool,
    get_list_of_containers_tool,
    get_list_of_images_tool,
    pull_docker_image_tool,
    get_task_runner_output_tool,
    check_task_runner_status_tool,
    start_docket_container_tool,
    stop_docker_container_tool
]

all_container_tools_mapping = { 
    tool.name: tool for tool in all_container_tools if hasattr(tool, "name")
}