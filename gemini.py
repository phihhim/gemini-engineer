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
from google.generativeai.protos import ToolConfig, FunctionCallingConfig
from tools import tool_list, execute_tool

# automode flag
automode = False

USER_COLOR = Fore.WHITE
CLAUDE_COLOR = Fore.BLUE
TOOL_COLOR = Fore.YELLOW
RESULT_COLOR = Fore.GREEN

#Configure the API key directly in the script
API_KEY = 'Your API key'
genai.configure(api_key=API_KEY)
# Model name
MODEL_NAME = "gemini-1.5-flash-latest"

# Generation configuration
generation_config = genai.types.GenerationConfig(
    temperature=0,
    top_k= 64,
    top_p= 0.95,
    max_output_tokens=5000,
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
            

def encode_image_to_base64(image_path):
    try:
        with Image.open(image_path) as img:
            max_size = (1024, 1024)
            img.thumbnail(max_size, Image.DEFAULT_STRATEGY)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
            return base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
    except Exception as e:
        return f"Error encoding image: {str(e)}"
            
def chat_with_gemini(user_input, image_path=None, current_iteration=None, max_iterations=None):
    global chat_history, automode
    
    chat_history.append({
        "role": "user",
        "parts": [user_input]
    })
    
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
            assistant_response += "Auto mode activated\n"
            fn_name = content_block.function_call.name
            params = {key: value for key, value in content_block.function_call.args.items()}
            execute_tool(fn_name, params)
        if content_block.text:
            assistant_response += content_block.text + "\n"
        
    chat_history.append({
        "role": "model",
        "parts": [assistant_response]
    })
    
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
        else:
            response, _ = chat_with_gemini(user_input)
            process_and_display_response(response)

if __name__ == "__main__":
    main()
