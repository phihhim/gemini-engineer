from google.api_core.exceptions import ResourceExhausted, GoogleAPIError
import os
import json
from google.generativeai.protos import ToolConfig, FunctionCallingConfig, FunctionResponse, Part
from tools import tool_list, execute_tool

import asyncio
import aiohttp

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
async def get_user_input(prompt="You: "):
    style = Style.from_dict({
        'prompt': 'cyan bold',
    })
    session = PromptSession(style=style)
    return await session.prompt_async(prompt, multiline=False)
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import datetime
import time
from datetime import datetime

from config import *

def save_chat():
    # Generate filename
    now = datetime.now()
    filename = f"Chat_{now.strftime('%H%M')}.md"
    
    # Format conversation history
    formatted_chat = "# Gemini Engineer Chat Log\n\n"
    for message in conversation_history:
        if message['role'] == 'user':
            formatted_chat += f"## User\n\n{message['parts']}\n\n"
        elif message['role'] == 'model':
            if isinstance(message['parts'], str):
                formatted_chat += f"## Gemini\n\n{message['parts']}\n\n"
            elif isinstance(message['parts'], list):
                for content in message['parts']:
                    if content['type'] == 'function_call':
                        formatted_chat += f"### Tool Use: {content['name']}\n\n```json\n{json.dumps(content['input'], indent=2)}\n```\n\n"
                    elif content['type'] == 'text':
                        formatted_chat += f"## Gemini\n\n{content['text']}\n\n"
        elif message['role'] == 'user' and isinstance(message['parts'], list):
            for content in message['parts']:
                if content['type'] == 'function_call':
                    formatted_chat += f"### Tool Result\n\n```\n{content['parts']}\n```\n\n"
    
    # Save to file
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(formatted_chat)
    
    return filename

def reset_code_editor_memory():
    global code_editor_memory
    code_editor_memory = []
    console.print(Panel("Code editor memory has been reset.", title="Reset", style="bold green"))

def reset_conversation():
    global conversation_history, main_model_tokens, tool_checker_tokens, code_editor_tokens, code_execution_tokens, file_contents, code_editor_files
    conversation_history = []
    main_model_tokens = {'input': 0, 'output': 0}
    tool_checker_tokens = {'input': 0, 'output': 0}
    code_editor_tokens = {'input': 0, 'output': 0}
    code_execution_tokens = {'input': 0, 'output': 0}
    file_contents = {}
    code_editor_files = set()
    reset_code_editor_memory()
    console.print(Panel("Conversation history, token counts, file contents, code editor memory, and code editor files have been reset.", title="Reset", style="bold green"))
    display_token_usage()

def upload_image_to_gemini(image_path):
    try:
        image_file = genai.upload_file(path=image_path, display_name="Upload image")
        return image_file

    except Exception:
        console.print(Panel(f"Error encoding image: {image_path}", title="Error", style="bold red"))

def display_token_usage():
    from rich.table import Table
    from rich.panel import Panel
    from rich.box import ROUNDED

    table = Table(box=ROUNDED)
    table.add_column("Model", style="cyan")
    table.add_column("Input", style="magenta")
    table.add_column("Output", style="magenta")
    table.add_column("Total", style="green")
    table.add_column(f"% of Context ({MAX_CONTEXT_TOKENS:,})", style="yellow")
#    table.add_column("Cost ($)", style="red")

    model_costs = {
        "Main Model": {"input": 3.00, "output": 15.00, "has_context": True},
        "Tool Checker": {"input": 3.00, "output": 15.00, "has_context": False},
        "Code Editor": {"input": 3.00, "output": 15.00, "has_context": True},
        "Code Execution": {"input": 3.00, "output": 15.00, "has_context": False}
    }

    total_input = 0
    total_output = 0
    total_cost = 0
    total_context_tokens = 0

    for model, tokens in [("Main Model", main_model_tokens),
                          ("Tool Checker", tool_checker_tokens),
                          ("Code Editor", code_editor_tokens),
                          ("Code Execution", code_execution_tokens)]:
        input_tokens = tokens['input']
        output_tokens = tokens['output']
        total_tokens = input_tokens + output_tokens

        total_input += input_tokens
        total_output += output_tokens

        input_cost = (input_tokens / 1_000_000) * model_costs[model]["input"]
        output_cost = (output_tokens / 1_000_000) * model_costs[model]["output"]
        model_cost = input_cost + output_cost
        total_cost += model_cost

        if model_costs[model]["has_context"]:
            total_context_tokens += total_tokens
            percentage = (total_tokens / MAX_CONTEXT_TOKENS) * 100
        else:
            percentage = 0

        table.add_row(
            model,
            f"{input_tokens:,}",
            f"{output_tokens:,}",
            f"{total_tokens:,}",
            f"{percentage:.2f}%" if model_costs[model]["has_context"] else "Doesn't save context",
 #           f"${model_cost:.3f}"
        )

    grand_total = total_input + total_output
    total_percentage = (total_context_tokens / MAX_CONTEXT_TOKENS) * 100

    table.add_row(
        "Total",
        f"{total_input:,}",
        f"{total_output:,}",
        f"{grand_total:,}",
        "",  # Empty string for the "% of Context" column
#        f"${total_cost:.3f}",
        style="bold"
    )

    console.print(table)        
           
            
async def chat_with_gemini(user_input, image_path=None, current_iteration=None, max_iterations=None):
    global conversation_history, automode, main_model_tokens

    # This function uses MAINMODEL, which maintains context across calls
    current_conversation = []

    if image_path:
        console.print(Panel(f"Processing image at path: {image_path}", title_align="left", title="Image Processing", expand=False, style="yellow"))
        image_upload = upload_image_to_gemini(image_path)

        if type(image_upload) == str:
            return "I'm sorry, there was an error processing the image. Please try again.", False   
        request_content = [user_input, image_upload]
        
        console.print(Panel("Image message added to conversation history", title_align="left", title="Image Added", style="green"))
    else:
        request_content = user_input
        
    current_conversation.append({
        "role": "user",
        "parts": request_content
    })
        
    
    # Filter conversation history to maintain context
    filtered_conversation_history = []
    for message in conversation_history:
        if isinstance(message['parts'], list):
            filtered_content = [
                content for content in message['parts']
                if content.get('type') != 'tool_result' or (
                    content.get('type') == 'tool_result' and
                    not any(keyword in content.get('output', '') for keyword in [
                        "File contents updated in system prompt",
                        "File created and added to system prompt",
                        "has been read and stored in the system prompt"
                    ])
                )
            ]
            if filtered_content:
                filtered_conversation_history.append({**message, 'parts': filtered_content})
        else:
            filtered_conversation_history.append(message)

    # Combine filtered history with current conversation to maintain context
    messages = filtered_conversation_history + current_conversation
    try:
    
        # MAINMODEL call, which maintains context
        response = main_model.generate_content(
            contents =messages,
            tool_config= ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfig.Mode.AUTO)
            ),
            tools= tool_list
        )
        # Update token usage for MAINMODEL
        main_model_tokens['input'] += response.usage_metadata.prompt_token_count
        main_model_tokens['output'] += response.usage_metadata.candidates_token_count
        
    except ResourceExhausted as e:
        console.print(Panel("Rate limit exceeded. Retrying after a short delay...", title="API Error", style="bold yellow"))
        time.sleep(5)
        return await chat_with_gemini(user_input, image_path, current_iteration, max_iterations)
    # except GoogleAPIError as e:
    #     console.print(Panel(f"API Error: {str(e)}", title="API Error", style="bold red"))
    #     return "I'm sorry, there was an error communicating with the AI. Please try again.", False

    assistant_response = ""
    exit_continuation = False
    tool_uses = []

    for content_block in response.candidates[0].content.parts:
        if content_block.text:
            assistant_response += content_block.text + "\n"
            if CONTINUATION_EXIT_PHRASE in content_block.text:
                exit_continuation = True
        elif content_block.function_call:
            tool_uses.append(content_block)

    console.print(Panel(Markdown(assistant_response), title="Gemini's Response", title_align="left", border_style="blue", expand=False))

    # Display files in context
    if file_contents:
        files_in_context = "\n".join(file_contents.keys())
    else:
        files_in_context = "No files in context. Read, create, or edit files to add."
    console.print(Panel(files_in_context, title="Files in Context", title_align="left", border_style="white", expand=False))

    for tool_use in tool_uses:
        tool_name = tool_use.function_call.name
        tool_input = {key: value for key, value in tool_use.function_call.args.items()}
        

        console.print(Panel(f"Tool Used: {tool_name}", style="green"))
        console.print(Panel(f"Tool Input: {json.dumps(tool_input, indent=2)}", style="green"))

        tool_result = await execute_tool(tool_name, tool_input)
                
        if tool_result["is_error"]:
            console.print(Panel(tool_result["content"], title="Tool Execution Error", style="bold red"))
        else:
            console.print(Panel(tool_result["content"], title_align="left", title="Tool Result", style="green"))

        current_conversation.append({
            "role": "model",
            "parts": [tool_use]
        })

        current_conversation.append({
            "role": "user",
            "parts": [Part(function_response= FunctionResponse(name=tool_name, response={"result": tool_result}))]
        })

        # Update the file_contents dictionary if applicable
        if tool_name in ['create_file', 'edit_and_apply', 'read_file'] and not tool_result["is_error"]:
            if 'path' in tool_input:
                file_path = tool_input['path']
                if "File contents updated in system prompt" in tool_result["content"] or \
                   "File created and added to system prompt" in tool_result["content"] or \
                   "has been read and stored in the system prompt" in tool_result["content"]:
                    # The file_contents dictionary is already updated in the tool function
                    pass

        messages = filtered_conversation_history + current_conversation

        try:
            tool_response = main_model.generate_content(
                contents =messages,
                tool_config= ToolConfig(
                    function_calling_config=FunctionCallingConfig(
                        mode=FunctionCallingConfig.Mode.AUTO)
                ),
                tools= tool_list
            )
            # Update token usage for tool checker
            tool_checker_tokens['input'] += tool_response.usage_metadata.prompt_token_count
            tool_checker_tokens['output'] += tool_response.usage_metadata.candidates_token_count
            
            tool_checker_response = ""
            for tool_content_block in tool_response.candidates[0].content.parts:
                if tool_content_block.text:
                    tool_checker_response += tool_content_block.text
            console.print(Panel(Markdown(tool_checker_response), title="Gemini's Response to Tool Result",  title_align="left", border_style="blue", expand=False))
            assistant_response += "\n\n" + tool_checker_response
        except GoogleAPIError as e:
            error_message = f"Error in tool response: {str(e)}"
            console.print(Panel(error_message, title="Error", style="bold red"))
            assistant_response += f"\n\n{error_message}"

    if assistant_response:
        current_conversation.append({"role": "model", "parts": assistant_response})

    conversation_history = messages + [{"role": "model", "parts": assistant_response}]

    # Display token usage at the end
    display_token_usage()

    return assistant_response, exit_continuation
    
async def main():
    console.print(Panel("Welcome to the Gemini Engineer Chat with Multi-Agent and Image Support!", title="Welcome", style="bold green"))
    console.print("Type 'exit' to end the conversation.")
    console.print("Type 'image' to include an image in your message.")
    console.print("Type 'automode [number]' to enter Autonomous mode with a specific number of iterations.")
    console.print("Type 'reset' to clear the conversation history.")
    console.print("Type 'save chat' to save the conversation to a Markdown file.")
    console.print("While in automode, press Ctrl+C at any time to exit the automode to return to regular chat.")  
    while True:
        user_input = await get_user_input()
        
        if user_input.lower() == 'exit':
            console.print(Panel("Thank you for chatting. Goodbye!", title_align="left", title="Goodbye", style="bold green"))
            break

        if user_input.lower() == 'reset':
            reset_conversation()
            continue

        if user_input.lower() == 'save chat':
            filename = save_chat()
            console.print(Panel(f"Chat saved to {filename}", title="Chat Saved", style="bold green"))
            continue
        
        if user_input.lower() == 'image':
            image_path = (await get_user_input("Drag and drop your image here, then press enter: ")).strip().replace("'", "")
            
            if os.path.isfile(image_path):
                user_input = await get_user_input("You (prompt for image): ")
                response, _ = await chat_with_gemini(user_input, image_path)
            else:
                console.print(Panel("Invalid image path. Please try again.", title="Error", style="bold red"))
                continue
        elif user_input.lower().startswith('automode'):
            try:
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    max_iterations = int(parts[1])
                else:
                    max_iterations = MAX_CONTINUATION_ITERATIONS
                
                automode = True
                console.print(Panel(f"Entering automode with {max_iterations} iterations. Please provide the goal of the automode.", title_align="left", title="Automode", style="bold yellow"))
                console.print(Panel("Press Ctrl+C at any time to exit the automode loop.", style="bold yellow"))
                user_input = await get_user_input()
                
                iteration_count = 0
                try:
                    while automode and iteration_count < max_iterations:
                        response, exit_continuation = await chat_with_gemini(user_input, current_iteration=iteration_count+1, max_iterations=max_iterations)
                        
                        if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                            console.print(Panel("Automode completed.", title_align="left", title="Automode", style="green"))
                            automode = False
                        else:
                            console.print(Panel(f"Continuation iteration {iteration_count + 1} completed. Press Ctrl+C to exit automode. ", title_align="left", title="Automode", style="yellow"))
                            user_input = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."                        
                        iteration_count += 1
                        
                        if iteration_count >= max_iterations:
                            console.print(Panel("Max iterations reached. Exiting automode.", title_align="left", title="Automode", style="bold red"))
                            automode = False
                except KeyboardInterrupt:
                    console.print(Panel("\nAutomode interrupted by user. Exiting automode.", title_align="left", title="Automode", style="bold red"))
                    automode = False
                    # Ensure the conversation history ends with an assistant message
                    if conversation_history and conversation_history[-1]["role"] == "user":
                        conversation_history.append({"role": "model", "content": "Automode interrupted. How can I assist you further?"})
            except KeyboardInterrupt:
                console.print(Panel("\nAutomode interrupted by user. Exiting automode.", title_align="left", title="Automode", style="bold red"))
                automode = False
                # Ensure the conversation history ends with an assistant message
                if conversation_history and conversation_history[-1]["role"] == "user":
                    conversation_history.append({"role": "assistant", "content": "Automode interrupted. How can I assist you further?"})
            
            console.print(Panel("Exited automode. Returning to regular chat.", style="green"))
        else:
            response, _ = await chat_with_gemini(user_input)
            
if __name__ == "__main__":
    asyncio.run(main())
    
