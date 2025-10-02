import functools
from typing import Optional, Callable
from langchain.tools import StructuredTool


printers = {
    "warm_yellow": lambda text: print("\033[38;5;220m{text}\033[0m".format(text=text)),
    "warm_blue": lambda text: print("\033[38;5;117m{text}\033[0m".format(text=text)),
    "orange": lambda text: print("\033[38;5;208m{text}\033[0m".format(text=text)),
    "purple": lambda text: print("\033[38;5;129m{text}\033[0m".format(text=text)),
    "white": lambda text: print("\033[38;5;15m{text}\033[0m".format(text=text)),
    "red": lambda text: print("\033[38;5;196m{text}\033[0m".format(text=text)),
    None: print,
}

def log_wrapper(func, log_colour:Optional[str]="warm_yellow"):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        log = kwargs.pop("log", True)  # extract `log` if passed
        result = func(*args, **kwargs)
        if log:
            printers[log_colour](
                f"[LOG] Using {func.__name__}"
                f"with args: {args}, kwargs: {kwargs}\n---> result: {result}"
            )
        return result
    return wrapper


def create_structured_tool(func, name, description=None, args_schema=None, log=True, log_colour="warm_yellow"):
    func = log_wrapper(func, log_colour) if log else func
    tool = ToolWrapper.from_function(
        func=func,
        name=name,
        description=description,
        args_schema=args_schema,
    )
    tool.base_func = func
    return tool


class ToolWrapper(StructuredTool):
    last_func: Optional[Callable] = None
    base_func: Optional[Callable] = None
    
    def change_log_colour(self, log_colour=None):
        self.base = log_wrapper(self.base_func, log_colour)

    def add_wrapper(self, wrapper):
        self.fun = wrapper(self.fun)
        
    
        
class ToolColourChanger(object):
    tool_mapping = {}
    
    @staticmethod
    def change_tool_colour(tool_name:str, new_colour:str) -> str:
        """
        Changes tool log colour
        """
        if not new_colour in printers.keys():
            return "colour not found in printers"
        if tool := ToolColourChanger.tool_mapping.get(tool_name):
            tool.change_log_colour(new_colour)
            return f"{tool.name} log colour changed to {new_colour} successfully"
        return f"{tool_name} not found"
        
        