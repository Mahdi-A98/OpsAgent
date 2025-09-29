from .container_tools import all_container_tools, all_container_tools_mapping
from core.utils import create_structured_tool, ToolColourChanger


change_tools_colour_tool = create_structured_tool(
    func=ToolColourChanger.change_tool_colour,
    name="change_tools_colour_tool",
    description="changes tools log colour",
    log=True,
    log_colour="white",
)
all_container_tools_mapping.update(
    {change_tools_colour_tool.name: change_tools_colour_tool}
)
ToolColourChanger.tool_mapping.update(all_container_tools_mapping)
all_container_tools.append(change_tools_colour_tool)




