from google.generativeai.protos import Tool, FunctionDeclaration, Schema, Type

def create_file(path, content=""):
    try:
        with open(path, "w+", newline="\n") as f:
            content = content.replace(r'\n', '\n')
            f.write(content)
        return f"File created: {path}"
    except Exception as e:
        return f"Error creating file: {str(e)}"


    
tool_list = [Tool(
   function_declarations=[
     FunctionDeclaration(
       name='create_file',
       description="Create a new file at the specified path with optional content. Use this when you need to create a new file in the project structure.",
       parameters=Schema(
           type= Type.OBJECT,
           properties={
               "path": Schema(type=Type.STRING),
               "content": Schema(type=Type.STRING)
           },
           required=["path","content"]
       ) 
     )
   ]
)]


def execute_tool(tool_name, tool_input):
    if tool_name == "create_file":
        return create_file(tool_input["path"], tool_input.get("content", ""))
    else:
        return f"Unknown tool: {tool_name}"


