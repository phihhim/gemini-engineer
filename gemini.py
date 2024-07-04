from typing_extensions import assert_never
import google.generativeai as genai
from colorama import init, Fore, Style
import os
from datetime import datetime
import json
from colorama import init, Fore, Style
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import TerminalFormatter
import pygments.util
import base64
from PIL import Image
import re
import io
import google.generativeai as genai
from system_prompt import update_system_prompt
from google.generativeai.protos import ToolConfig, FunctionCallingConfig, FunctionResponse, Part
from tools import tool_list, execute_tool
from google.generativeai.types import content_types
automode = False
MAX_CONTINUATION_ITERATIONS = 25
CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"
USER_COLOR = Fore.WHITE
CLAUDE_COLOR = Fore.BLUE
TOOL_COLOR = Fore.YELLOW
RESULT_COLOR = Fore.GREEN

#Configure the API key directly in the script
API_KEY = ''
genai.configure(api_key=API_KEY)
# Model name
MODEL_NAME = "gemini-1.5-flash-latest"

# Generation configuration
generation_config = genai.types.GenerationConfig(
    temperature=0,
    top_k= 64,
    top_p= 0.95,
    max_output_tokens=10000,
    candidate_count=1
)

# Create the model
model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    generation_config=generation_config,
    system_instruction=update_system_prompt(),
)

chat_history = []

def print_colored(text, color):
    print(f"{color}{text}{Style.RESET_ALL}")

def print_code(code, language):
    try:
        lexer = get_lexer_by_name(language, stripall=True)
        formatted_code = highlight(code, lexer, TerminalFormatter())
        print(formatted_code)
    except pygments.util.ClassNotFound:
        print_colored(f"Code (language: {language}):\n{code}", CLAUDE_COLOR)

def process_and_display_response(response):
    if response.startswith("Error") or response.startswith("I'm sorry"):
        print_colored(response, TOOL_COLOR)
    else:
        if "```" in response:
            parts = response.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    print_colored(part, CLAUDE_COLOR)
                else:
                    lines = part.split('\n')
                    language = lines[0].strip() if lines else ""
                    code = '\n'.join(lines[1:]) if len(lines) > 1 else ""
                    
                    if language and code:
                        print_code(code, language)
                    elif code:
                        print_colored(f"Code:\n{code}", CLAUDE_COLOR)
                    else:
                        print_colored(part, CLAUDE_COLOR)
        else:
            print_colored(f"\nGemini: {response}", CLAUDE_COLOR)
            

def upload_image_to_gemini(image_path):
    try:
        image_file = genai.upload_file(path=image_path, display_name="Upload image")
        return image_file

    except Exception as e:
        return f"Error processing image: {str(e)}"
            
def chat_with_gemini(user_input, image_path=None, current_iteration=None, max_iterations=None):
    global chat_history, automode
    request_content = []

    if image_path:
        print_colored(f"Processing image at path: {image_path}", TOOL_COLOR)
        image = upload_image_to_gemini(image_path)
        request_content = [user_input, image]
        if type(image) == str:
            print_colored(f"Error encoding image: {image_path}", TOOL_COLOR)
            return "I'm sorry, there was an error processing the image. Please try again.", False

    else:
        request_content = [user_input]
    
    chat_history.append({
        "role": "user",
        "parts": request_content
    })
    model._system_instruction = content_types.to_content(update_system_prompt(automode, current_iteration, max_iterations))

    response = model.generate_content(
        contents =chat_history,
        tool_config= ToolConfig(
            function_calling_config=FunctionCallingConfig(
                mode=FunctionCallingConfig.Mode.AUTO)
            ),
        tools= tool_list
    )
    
    assistant_response = ""
    exit_continuation = False
    
    for content_block in response.candidates[0].content.parts:
        if content_block.function_call:
            fn_name = content_block.function_call.name
            params = {key: value for key, value in content_block.function_call.args.items()}
            print_colored(f"\nTool Used: {fn_name}", TOOL_COLOR)
            print_colored(f"Tool Input: {json.dumps(params)}", TOOL_COLOR)
            tool_result = execute_tool(fn_name, params)
            print_colored(f"Tool Result: {tool_result}", RESULT_COLOR)
            chat_history.append(
                {
                    "role": "user",
                    "parts": [content_block]
                }
            )
            chat_history.append(
                {
                    "role": "user",
                    "parts": [Part(function_response= FunctionResponse(name=fn_name, response={"result": tool_result}))]
                }
            )
            tool_report = model.generate_content(
                contents =chat_history,
                tool_config= ToolConfig(
                    function_calling_config=FunctionCallingConfig(
                        mode=FunctionCallingConfig.Mode.AUTO)
                ),
                tools= tool_list
            )
            for tool_report_block in tool_report.candidates[0].content.parts:
                if tool_report_block.text:
                    assistant_response += tool_report_block.text
#                    print_colored(f"\nGemini: {tool_report_block.text}", CLAUDE_COLOR)
            
        if content_block.text:
            assistant_response += content_block.text + "\n"
#            print_colored(f"\nGemini: {content_block.text}", CLAUDE_COLOR)
            if CONTINUATION_EXIT_PHRASE in content_block.text:
                exit_continuation = True
                
    if assistant_response:
        chat_history.append(
            {
                "role": "model",
                "parts": [assistant_response]
            }
        )
                
    return assistant_response, exit_continuation
            
    
def main():
    print_colored("Welcome to the Gemini Chat with Image Support!", CLAUDE_COLOR)
    print_colored("Type 'exit' to end the conversation.", CLAUDE_COLOR)
    print_colored("Type 'image' to include an image in your message.", CLAUDE_COLOR)
    print_colored("Type 'automode [number]' to enter Autonomous mode with a specific number of iterations.", CLAUDE_COLOR)
    print_colored("While in automode, press Ctrl+C at any time to exit the automode to return to regular chat.", CLAUDE_COLOR)    
    while True:
        user_input = input(f"\n{USER_COLOR}You: {Style.RESET_ALL}")
        
        if user_input.lower() == 'exit':
            print_colored("Thank you for chatting. Goodbye!", CLAUDE_COLOR)
            break
        
        if user_input.lower() == 'image':
            image_path = input(f"{USER_COLOR}Drag and drop your image here: {Style.RESET_ALL}").strip().replace("'", "")
            
            if os.path.isfile(image_path):
                user_input = input(f"{USER_COLOR}You (prompt for image): {Style.RESET_ALL}")
                response, _ = chat_with_gemini(user_input, image_path)
                process_and_display_response(response)
            else:
                print_colored("Invalid image path. Please try again.", CLAUDE_COLOR)
                continue
        elif user_input.lower().startswith('automode'):
            try:
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    max_iterations = int(parts[1])
                else:
                    max_iterations = MAX_CONTINUATION_ITERATIONS
                
                automode = True
                print_colored(f"Entering automode with {max_iterations} iterations. Press Ctrl+C to exit automode at any time.", TOOL_COLOR)
                print_colored("Press Ctrl+C at any time to exit the automode loop.", TOOL_COLOR)
                user_input = input(f"\n{USER_COLOR}You: {Style.RESET_ALL}")
                
                iteration_count = 0
                try:
                    while automode and iteration_count < max_iterations:
                        response, exit_continuation = chat_with_gemini(user_input, current_iteration=iteration_count+1, max_iterations=max_iterations)
                        process_and_display_response(response)
                        
                        if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                            print_colored("Automode completed.", TOOL_COLOR)
                            automode = False
                        else:
                            print_colored(f"Continuation iteration {iteration_count + 1} completed.", TOOL_COLOR)
                            print_colored("Press Ctrl+C to exit automode.", TOOL_COLOR)
                            user_input = "Continue with the next step."
                        
                        iteration_count += 1
                        
                        if iteration_count >= max_iterations:
                            print_colored("Max iterations reached. Exiting automode.", TOOL_COLOR)
                            automode = False
                except KeyboardInterrupt:
                    print_colored("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR)
                    automode = False
                    # Ensure the conversation history ends with an assistant message
                    if chat_history and chat_history[-1]["role"] == "user":
                        chat_history.append({"role": "model", "content": "Automode interrupted. How can I assist you further?"})
            except KeyboardInterrupt:
                print_colored("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR)
                automode = False
                # Ensure the conversation history ends with an assistant message
                if chat_history and chat_history[-1]["role"] == "user":
                    chat_history.append({"role": "assistant", "content": "Automode interrupted. How can I assist you further?"})
            
            print_colored("Exited automode. Returning to regular chat.", TOOL_COLOR)
        else:
            response, _ = chat_with_gemini(user_input)
            process_and_display_response(response)

if __name__ == "__main__":
    if API_KEY:
        main()
    else:
        print_colored("API key not found. Please set API key in gemini.py!!", TOOL_COLOR)
