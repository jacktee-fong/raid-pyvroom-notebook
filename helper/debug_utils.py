import os
from typing import Any
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def debug_print(*args: Any, **kwargs: Any) -> None:
    """
    Print debug information if DEBUG environment variable is set to True
    
    Args:
        *args: Variables to print
        **kwargs: Additional parameters for print function
            prefix: Optional prefix for the debug message
            show_time: Boolean to indicate if timestamp should be included (default: True)
    """
    if os.getenv('DEBUG', 'False').lower() == 'true':
        prefix = kwargs.pop('prefix', 'DEBUG')
        show_time = kwargs.pop('show_time', True)
        
        # Prepare the timestamp
        timestamp = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] " if show_time else ""
        
        # Prepare the prefix
        prefix_str = f"[{prefix}] " if prefix else ""
        
        # Combine all args into a single string
        message = " ".join(str(arg) for arg in args)
        
        # Print with timestamp and prefix
        print(f"{timestamp}{prefix_str}{message}", **kwargs) 