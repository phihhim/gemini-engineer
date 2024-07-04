from google.generativeai.protos import Tool, FunctionDeclaration, Schema, Type
import os
import difflib

def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Folder created: {path}"
    except Exception as e:
        return f"Error creating folder: {str(e)}"


def create_file(path, content=""):
    try:
        with open(path, "w") as f:
            content = content.replace(r'\n', '\n')
            f.write(content)
        return f"File created: {path}"
    except Exception as e:
        return f"Error creating file: {str(e)}"

 
def generate_and_apply_diff(original_content, new_content, path):
    diff = list(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3
    ))
    
    if not diff:
        return "No changes detected."
    
    try:
        with open(path, 'w') as f:
            content = new_content.replace(r'\n', '\n')
            f.writelines(content)
        return f"Changes applied to {path}:\n" + ''.join(diff)
    except Exception as e:
        return f"Error applying changes: {str(e)}"

def write_to_file(path, content):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                original_content = f.read()
            result = generate_and_apply_diff(original_content, content, path)
        else:
            with open(path, 'w') as f:
                content = content.replace(r'\n', '\n')
                f.write(content)
            result = f"New file created and content written to: {path}"
        return result
    except Exception as e:
        return f"Error writing to file: {str(e)}"

def read_file(path):
    try:
        with open(path, 'r') as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

def list_files(path="."):
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"Error listing files: {str(e)}"    
    
tool_list = [
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='create_file',
                description="Create a new file at the specified path with optional content. Use this when you need to create a new file in the project structure.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING)
                        },
                    required=["path"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='create_folder',
                description="Create a new folder at the specified path. Use this when you need to create a new directory in the project structure.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING)
                    },
                    required=["path"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='write_to_file',
                description="Write content to a file at the specified path. If the file exists, only the necessary changes will be applied. If the file doesn't exist, it will be created. Always provide the full intended content of the file.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING),
                        "content": Schema(type=Type.STRING)
                    },
                    required=["path"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='read_file',
                description="Read the contents of a file at the specified path. Use this when you need to examine the contents of an existing file.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING),
                        },
                    required=["path"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='list_files',
                description="List all files and directories in the root folder where the script is running. Use this when you need to see the contents of the current directory.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING),
                        },
                    required=["path"]
                ) 
            )
        ]
    ),
]


def execute_tool(tool_name, tool_input):
    if tool_name == "create_file":
        return create_file(tool_input["path"], tool_input.get("content", ""))
    if tool_name == "create_folder":
        return create_folder(tool_input["path"])
    if tool_name == "write_to_file":
        return write_to_file(tool_input["path"], tool_input.get("content", ""))
    if tool_name == "read_file":
        return read_file(tool_input["path"])
    if tool_name == "list_files":
        return list_files(tool_input["path"])    
    else:
        return f"Unknown tool: {tool_name}"


