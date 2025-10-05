import functools
from typing import Optional, Callable
from langchain.tools import StructuredTool

class StyledPrinter:
    """
    Chainable ANSI printer for colors, background highlights, and styles.
    
    Example usage:
        printer = StyledPrinter()
        printer["blue"]("Blue text")
        printer["italic"]["red"]("Italic red text")
        printer["blue"]["bg_red"]["bold"]["underline"]("Styled text")
    """
    def __init__(self, codes=None):
        self.codes = codes or []

    def __getitem__(self, key):
        # ANSI style codes
        styles = {
            "bold": "1",
            "underline": "4",
            "reverse": "7",
            "italic": "3",
        }
        
        # Foreground colors (your extended 256-color list)
        fg_colors = {
            "warm_yellow": "220", "yellow": "226", "orange": "208",
            "red": "196", "light_red": "203", "green": "82", "light_green": "120",
            "cyan": "51", "light_cyan": "159", "blue": "33", "light_blue": "75",
            "purple": "129", "magenta": "201", "pink": "205", "gray": "245",
            "dark_gray": "240", "light_gray": "250", "white": "15", "black": "16",
            "gold": "220", "teal": "37", "olive": "142", "brown": "94",
            "maroon": "124", "navy": "18", "violet": "135", "turquoise": "80",
            "lime": "118", "dark_green": "22", "sky": "153", "warm_blue": "117"
        }

        # Background colors
        bg_colors = dict(("bg_" + color_name, code) for color_name, code in fg_colors.items())

        code = None
        if key in styles:
            code = styles[key]
        elif key in fg_colors:
            code = f"38;5;{fg_colors[key]}"
        elif key in bg_colors:
            code = f"48;5;{bg_colors[key]}"
        else:
            raise KeyError(f"Style or color '{key}' not defined.")

        # Return a new instance with combined codes
        return StyledPrinter(self.codes + [code])

    def __call__(self, text):
        if not self.codes:
            print(text)
        else:
            print(f"\033[{';'.join(self.codes)}m{text}\033[0m")


# Create the printer instance
printers = StyledPrinter()


def log_wrapper(func, log_colour:Optional[str]="warm_yellow", printer=None):
    printer = printer or printers[log_colour]
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        log = kwargs.pop("log", True)  # extract `log` if passed
        result = func(*args, **kwargs)
        if log:
            printer(
                f"[LOG] Using {func.__name__}"
                f"with args: {args}, kwargs: {kwargs}\n---> result: {result}"
            )
        return result
    return wrapper


def create_structured_tool(
                    func,
                    name,
                    description=None,
                    args_schema=None,
                    log=True,
                    log_colour="warm_yellow",
                    log_printer=None):
    func = log_wrapper(func, log_colour, printer=log_printer) if log else func
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
        
        