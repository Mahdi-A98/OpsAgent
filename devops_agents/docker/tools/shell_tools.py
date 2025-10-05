from devops_agents.docker.utils import CMDTools
from core.utils import create_structured_tool, printers


cmd_tools_functions = [
    tool for name, tool in
    CMDTools.__dict__.items()
    if not str(name).startswith("__")
]

shell_tools_map = dict(
    (
        tool.__name__,
        create_structured_tool(
            func=tool,
            name="shell_tool__" + tool.__name__,
            description=tool.__doc__,
            log_printer=printers["bg_black"]["gold"]["bold"]["italic"]
        )
    ) for tool in cmd_tools_functions
)
all_shell_tools = list(shell_tools_map.values())