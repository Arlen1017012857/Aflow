from re import search
from aflow import AflowManager
import os
import shutil
import ast

if __name__ == "__main__":
    # Set tools directory before initializing
    os.environ['TOOLS_DIR'] = 'tests/test_tools'
    
    # Clear any existing Merkle tree state
    merkle_state_dir = '.merkle'
    if os.path.exists(merkle_state_dir):
        shutil.rmtree(merkle_state_dir)
    
    aflow_manager = AflowManager()
    
    # Clear database
    # with aflow_manager.neo4j_manager.get_session() as session:
    #     session.run("MATCH (n) DETACH DELETE n")
    
    # Force process all Python files
    # for root, _, files in os.walk(os.environ['TOOLS_DIR']):
    #     for file in files:
    #         if file.endswith('.py') and file != '__init__.py':
    #             file_path = os.path.join(root, file)
    #             print(f"\nProcessing tool file: {file_path}")
    #             with open(file_path, 'r') as f:
    #                 content = f.read()
    #                 tree = ast.parse(content)
    #                 name = os.path.splitext(file)[0]
    #                 aflow_manager.tool_manager._extract_tool_info(file_path, tree)
    
    # Print all tools to verify scanning
    # tools = aflow_manager.list_tools()
    # print("\nFound tools:", tools)

    # search_query = "我想计算两数之和"
    # search_results = aflow_manager.search_tools(search_query)
    # print("\nSearch results:", search_results)
