from google.generativeai.protos import Tool, FunctionDeclaration, Schema, Type, ToolConfig, FunctionCallingConfig
import os
import difflib
import subprocess
import platform
import shutil
import shlex
import asyncio
from config import *
import json
import re
import sys
import signal
import venv

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

def highlight_diff(diff_text):
    return Syntax(diff_text, "diff", theme="monokai", line_numbers=True)

def generate_diff(original, new, path):
    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3
    ))

    diff_text = ''.join(diff)
    highlighted_diff = highlight_diff(diff_text)

    return highlighted_diff

def parse_search_replace_blocks(response_text):
    blocks = []
    pattern = r'<SEARCH>\n(.*?)\n</SEARCH>\n<REPLACE>\n(.*?)\n</REPLACE>'
    matches = re.findall(pattern, response_text, re.DOTALL)
    
    for search, replace in matches:
        blocks.append({
            'search': search.strip(),
            'replace': replace.strip()
        })
    
    return json.dumps(blocks)  # Keep returning JSON string


async def generate_edit_instructions(file_path, file_content, instructions, project_context, full_file_contents):
    global code_editor_tokens, code_editor_memory, code_editor_files
    try:
        # Prepare memory context (this is the only part that maintains some context between calls)
        memory_context = "\n".join([f"Memory {i+1}:\n{mem}" for i, mem in enumerate(code_editor_memory)])

        # Prepare full file contents context, excluding the file being edited if it's already in code_editor_files
        full_file_contents_context = "\n\n".join([
            f"--- {path} ---\n{content}" for path, content in full_file_contents.items()
            if path != file_path or path not in code_editor_files
        ])

        system_prompt = f"""
        You are an AI coding agent that generates edit instructions for code files. Your task is to analyze the provided code and generate SEARCH/REPLACE blocks for necessary changes. Follow these steps:

        1. Review the entire file content to understand the context:
        {file_content}

        2. Carefully analyze the specific instructions:
        {instructions}

        3. Take into account the overall project context:
        {project_context}

        4. Consider the memory of previous edits:
        {memory_context}

        5. Consider the full context of all files in the project:
        {full_file_contents_context}

        6. Generate SEARCH/REPLACE blocks for each necessary change. Each block should:
           - Include enough context to uniquely identify the code to be changed
           - Provide the exact replacement code, maintaining correct indentation and formatting
           - Focus on specific, targeted changes rather than large, sweeping modifications

        7. Ensure that your SEARCH/REPLACE blocks:
           - Address all relevant aspects of the instructions
           - Maintain or enhance code readability and efficiency
           - Consider the overall structure and purpose of the code
           - Follow best practices and coding standards for the language
           - Maintain consistency with the project context and previous edits
           - Take into account the full context of all files in the project

        IMPORTANT: RETURN ONLY THE SEARCH/REPLACE BLOCKS. NO EXPLANATIONS OR COMMENTS.
        USE THE FOLLOWING FORMAT FOR EACH BLOCK:

        <SEARCH>
        Code to be replaced
        </SEARCH>
        <REPLACE>
        New code to insert
        </REPLACE>

        If no changes are needed, return an empty list.
        """

        # Make the API call to CODEEDITORMODEL (context is not maintained except for code_editor_memory)
        code_edit_model = genai.GenerativeModel(
            model_name=CODEEDITORMODEL,
            generation_config=generation_config,
            system_instruction=system_prompt,
        )
        response = main_model.generate_content(
            contents =[
                {"role": "user", "content": "Generate SEARCH/REPLACE blocks for the necessary changes."}
            ]
        )
        # Update token usage for code editor
        code_editor_tokens['input'] += response.usage_metadata.prompt_token_count
        code_editor_tokens['output'] += response.usage_metadata.candidates_token_count

        # Parse the response to extract SEARCH/REPLACE blocks
        edit_instructions = parse_search_replace_blocks(response.text)

        # Update code editor memory (this is the only part that maintains some context between calls)
        code_editor_memory.append(f"Edit Instructions for {file_path}:\n{response.text}")

        # Add the file to code_editor_files set
        code_editor_files.add(file_path)

        return edit_instructions

    except Exception as e:
        console.print(f"Error in generating edit instructions: {str(e)}", style="bold red")
        return []  # Return empty list if any exception occurs

async def apply_edits(file_path, edit_instructions, original_content):
    changes_made = False
    edited_content = original_content
    total_edits = len(edit_instructions)
    failed_edits = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        edit_task = progress.add_task("[cyan]Applying edits...", total=total_edits)

        for i, edit in enumerate(edit_instructions, 1):
            search_content = edit['search'].strip()
            replace_content = edit['replace'].strip()
            
            # Use regex to find the content, ignoring leading/trailing whitespace
            pattern = re.compile(re.escape(search_content), re.DOTALL)
            match = pattern.search(edited_content)
            
            if match:
                # Replace the content, preserving the original whitespace
                start, end = match.span()
                # Strip <SEARCH> and <REPLACE> tags from replace_content
                replace_content_cleaned = re.sub(r'</?SEARCH>|</?REPLACE>', '', replace_content)
                edited_content = edited_content[:start] + replace_content_cleaned + edited_content[end:]
                changes_made = True
                
                # Display the diff for this edit
                diff_result = generate_diff(search_content, replace_content, file_path)
                console.print(Panel(diff_result, title=f"Changes in {file_path} ({i}/{total_edits})", style="cyan"))
            else:
                console.print(Panel(f"Edit {i}/{total_edits} not applied: content not found", style="yellow"))
                failed_edits.append(f"Edit {i}: {search_content}")

            progress.update(edit_task, advance=1)

    if not changes_made:
        console.print(Panel("No changes were applied. The file content already matches the desired state.", style="green"))
    else:
        # Write the changes to the file
        with open(file_path, 'w') as file:
            file.write(edited_content)
        console.print(Panel(f"Changes have been written to {file_path}", style="green"))

    return edited_content, changes_made, "\n".join(failed_edits)
    
def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Folder created: {path}"
    except Exception as e:
        return f"Error creating folder: {str(e)}"


def create_file(path, content=""):
    try:
        with open(path, "w", newline='\n', encoding="utf-8") as f:
            content = content.replace(r'\n', '\n')
            f.write(content)
        file_contents[path] = content
        return f"File created: {path}"
    except Exception as e:
        return f"Error creating file: {str(e)}"

async def edit_and_apply(path, instructions, project_context, is_automode=False, max_retries=3):
    global file_contents
    try:
        original_content = file_contents.get(path, "")
        if not original_content:
            with open(path, 'r') as file:
                original_content = file.read()
            file_contents[path] = original_content

        for attempt in range(max_retries):
            edit_instructions_json = await generate_edit_instructions(path, original_content, instructions, project_context, file_contents)
            
            if edit_instructions_json:
                edit_instructions = json.loads(edit_instructions_json)  # Parse JSON here
                console.print(Panel(f"Attempt {attempt + 1}/{max_retries}: The following SEARCH/REPLACE blocks have been generated:", title="Edit Instructions", style="cyan"))
                for i, block in enumerate(edit_instructions, 1):
                    console.print(f"Block {i}:")
                    console.print(Panel(f"SEARCH:\n{block['search']}\n\nREPLACE:\n{block['replace']}", expand=False))

                edited_content, changes_made, failed_edits = await apply_edits(path, edit_instructions, original_content)

                if changes_made:
                    file_contents[path] = edited_content  # Update the file_contents with the new content
                    console.print(Panel(f"File contents updated in system prompt: {path}", style="green"))
                    
                    if failed_edits:
                        console.print(Panel(f"Some edits could not be applied. Retrying...", style="yellow"))
                        instructions += f"\n\nPlease retry the following edits that could not be applied:\n{failed_edits}"
                        original_content = edited_content
                        continue
                    
                    return f"Changes applied to {path}"
                elif attempt == max_retries - 1:
                    return f"No changes could be applied to {path} after {max_retries} attempts. Please review the edit instructions and try again."
                else:
                    console.print(Panel(f"No changes could be applied in attempt {attempt + 1}. Retrying...", style="yellow"))
            else:
                return f"No changes suggested for {path}"
        
        return f"Failed to apply changes to {path} after {max_retries} attempts."
    except Exception as e:
        return f"Error editing/applying to file: {str(e)}"


def read_multiple_files(paths):
    global file_contents
    results = []
    for path in paths:
        try:
            with open(path, 'r') as f:
                content = f.read()
            file_contents[path] = content
            results.append(f"File '{path}' has been read and stored in the system prompt.")
        except Exception as e:
            results.append(f"Error reading file '{path}': {str(e)}")
    return "\n".join(results)

def stop_process(process_id):
    global running_processes
    if process_id in running_processes:
        process = running_processes[process_id]
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        del running_processes[process_id]
        return f"Process {process_id} has been stopped."
    else:
        return f"No running process found with ID {process_id}."


def setup_virtual_environment():
    venv_name = "code_execution_env"
    venv_path = os.path.join(os.getcwd(), venv_name)
    try:
        if not os.path.exists(venv_path):
            venv.create(venv_path, with_pip=True)
        
        # Activate the virtual environment
        if sys.platform == "win32":
            activate_script = os.path.join(venv_path, "Scripts", "activate.bat")
        else:
            activate_script = os.path.join(venv_path, "bin", "activate")
        
        return venv_path, activate_script
    except Exception as e:
        print(f"Error setting up virtual environment: {str(e)}")
        raise    

async def send_to_ai_for_executing(code, execution_result):
    global code_execution_tokens

    try:
        system_prompt = f"""
        You are an AI code execution agent. Your task is to analyze the provided code and its execution result from the 'code_execution_env' virtual environment, then provide a concise summary of what worked, what didn't work, and any important observations. Follow these steps:

        1. Review the code that was executed in the 'code_execution_env' virtual environment:
        {code}

        2. Analyze the execution result from the 'code_execution_env' virtual environment:
        {execution_result}

        3. Provide a brief summary of:
           - What parts of the code executed successfully in the virtual environment
           - Any errors or unexpected behavior encountered in the virtual environment
           - Potential improvements or fixes for issues, considering the isolated nature of the environment
           - Any important observations about the code's performance or output within the virtual environment
           - If the execution timed out, explain what this might mean (e.g., long-running process, infinite loop)

        Be concise and focus on the most important aspects of the code execution within the 'code_execution_env' virtual environment.

        IMPORTANT: PROVIDE ONLY YOUR ANALYSIS AND OBSERVATIONS. DO NOT INCLUDE ANY PREFACING STATEMENTS OR EXPLANATIONS OF YOUR ROLE.
        """
        code_execution_model = genai.GenerativeModel(
            model_name=CODEEXECUTIONMODEL,
            generation_config=generation_config,
            system_instruction=system_prompt,
        )
        response = code_execution_model.generate_content(
            contents =[
                {"role": "user", "parts": f"Analyze this code execution from the 'code_execution_env' virtual environment:\n\nCode:\n{code}\n\nExecution Result:\n{execution_result}"}
            ]
        )
        
        # Update token usage for code execution
        code_execution_tokens['input'] += response.usage_metadata.prompt_token_count
        code_execution_tokens['output'] += response.usage_metadata.candidates_token_count

        analysis = response.text

        return analysis

    except Exception as e:
        console.print(f"Error in AI code execution analysis: {str(e)}", style="bold red")
        return f"Error analyzing code execution from 'code_execution_env': {str(e)}"    
    
async def execute_code(code, timeout=10):
    global running_processes
    venv_path, activate_script = setup_virtual_environment()
    
    # Generate a unique identifier for this process
    process_id = f"process_{len(running_processes)}"
    
    # Write the code to a temporary file
    with open(f"{process_id}.py", "w") as f:
        f.write(code)
    
    # Prepare the command to run the code
    if sys.platform == "win32":
        command = f'"{activate_script}" && python3 {process_id}.py'
    else:
        command = f'source "{activate_script}" && python3 {process_id}.py'
    
    # Create a process to run the command
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        shell=True,
        preexec_fn=None if sys.platform == "win32" else os.setsid
    )
    
    # Store the process in our global dictionary
    running_processes[process_id] = process
    
    try:
        # Wait for initial output or timeout
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        stdout = stdout.decode()
        stderr = stderr.decode()
        return_code = process.returncode
    except asyncio.TimeoutError:
        # If we timeout, it means the process is still running
        stdout = "Process started and running in the background."
        stderr = ""
        return_code = "Running"
    
    execution_result = f"Process ID: {process_id}\n\nStdout:\n{stdout}\n\nStderr:\n{stderr}\n\nReturn Code: {return_code}"
    return process_id, execution_result    
    
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
        with open(path, 'w', newline='\n', encoding="utf-8") as f:
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
            with open(path, 'w', newline='\n', encoding="utf-8") as f:
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

def is_command_available(command):
    return shutil.which(command) is not None
    
def run_command(command):
    try:
        cmd = command.split()[0]
        if not is_command_available(cmd):
            return f"Error: Command '{cmd}' is not available on this system."
        
        if platform.system().lower() == "windows":
            process = subprocess.Popen(f'cmd.exe /c {command}', stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
        else:
            args = shlex.split(command)
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        stdout, stderr = process.communicate()
        return_code = process.returncode
        
        print(f"Command: {command}\n")
        print( f"Return Code: {return_code}\n")
        print(f"STDOUT:\n{stdout}\n")
        print(f"STDERR:\n{stderr}\n")
        if stderr:
            return stderr
        if stdout:
            return stdout
    except Exception as e:
        return f"Error executing command: {str(e)}"   
    
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
                name='edit_and_apply',
                description= "Apply AI-powered improvements to a file based on specific instructions and detailed project context. This function reads the file, processes it in batches using AI with conversation history and comprehensive code-related project context. It generates a diff and allows the user to confirm changes before applying them. The goal is to maintain consistency and prevent breaking connections between files. This tool should be used for complex code modifications that require understanding of the broader project context.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "path": Schema(type=Type.STRING),
                        "instructions": Schema(type=Type.STRING),
                        "project_context": Schema(type=Type.STRING),
                        },
                    required=["path", "instructions", "project_context"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='execute_code',
                description="Execute Python code in the 'code_execution_env' virtual environment and return the output. This tool should be used when you need to run code and see its output or check for errors. All code execution happens exclusively in this isolated environment. The tool will return the standard output, standard error, and return code of the executed code. Long-running processes will return a process ID for later management.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "code": Schema(type=Type.STRING),
                        },
                    description = "The Python code to execute in the 'code_execution_env' virtual environment. Include all necessary imports and ensure the code is complete and self-contained.",
                    required=["code"]
                ) 
            )
        ]
    ),
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name="stop_process",
                description="Stop a running process by its ID. This tool should be used to terminate long-running processes that were started by the execute_code tool. It will attempt to stop the process gracefully, but may force termination if necessary. The tool will return a success message if the process is stopped, and an error message if the process doesn't exist or can't be stopped.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "process_id": Schema(type=Type.STRING),
                        },
                    required=["process_id"]
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
                name="read_multiple_files",
                description= "Read the contents of multiple files at the specified paths. This tool should be used when you need to examine the contents of multiple existing files at once. It will return the status of reading each file, and store the contents of successfully read files in the system prompt. If a file doesn't exist or can't be read, an appropriate error message will be returned for that file.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "paths": Schema(
                            type=Type.ARRAY,
                            items= Schema(type= Type.STRING)
                        ),
                        },
                    description = "An array of absolute or relative paths of the files to read. Use forward slashes (/) for path separation, even on Windows systems.",
                    required=["paths"]
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
    Tool(
        function_declarations=[
            FunctionDeclaration(
                name='run_command',
                description= "Execute a local command and return the result. Use this to run system commands or start processes.",
                parameters=Schema(
                    type= Type.OBJECT,
                    properties={
                        "command": Schema(type=Type.STRING),
                        },
                    required=["command"]
                ) 
            )
        ]
    ),
    
    
]


async def execute_tool(tool_name, tool_input):
    try:
        result = None
        is_error = False
        
        if tool_name == "create_folder":
            result = create_folder(tool_input["path"])
        elif tool_name == "create_file":
            result = create_file(tool_input["path"], tool_input.get("content", ""))
        elif tool_name == "edit_and_apply":
            result = await edit_and_apply(
                tool_input["path"],
                tool_input["instructions"],
                tool_input["project_context"],
                is_automode=automode
            )
        elif tool_name == "read_file":
            result = read_file(tool_input["path"])
        elif tool_name == "read_multiple_files":
            result = read_multiple_files(tool_input["paths"])
        elif tool_name == "list_files":
            result = list_files(tool_input.get("path", "."))
        elif tool_name == "stop_process":
            result = stop_process(tool_input["process_id"])
        elif tool_name == "execute_code":
            process_id, execution_result = await execute_code(tool_input["code"])
            analysis_task = asyncio.create_task(send_to_ai_for_executing(tool_input["code"], execution_result))
            analysis = await analysis_task
            result = f"{execution_result}\n\nAnalysis:\n{analysis}"
            if process_id in running_processes:
                result += "\n\nNote: The process is still running in the background."
        elif tool_name == "run_command":
            result = run_command(tool_input["command"])
        else:
            is_error = True
            result = f"Unknown tool: {tool_name}"
        return {
            "content": result,
            "is_error": is_error
        }
    except KeyError as e:
        return {
            "content": f"Error: Missing required parameter {str(e)} for tool {tool_name}",
            "is_error": True
        }
    except Exception as e:
        return {
            "content": f"Error executing tool {tool_name}: {str(e)}",
            "is_error": True
        }


