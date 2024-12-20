# -*- coding: utf-8 -*-
import sys
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

from re import search
from aflow import AflowManager
import os
import shutil
import ast

if __name__ == "__main__":
    # Set tools directory before initializing
    os.environ['TOOLS_DIR'] = 'tests/test_tools'
    
    aflow_manager = AflowManager()
    # sync_tools_result = aflow_manager.sync_tools()
    # print("Sync tools result:", sync_tools_result)
    
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

    # search_query = "文件管理"
    # search_results = aflow_manager.search_tools(search_query)
    # print("\nSearch results:", search_results)

    # 展示工具目录的Merkle树结构
    print("\n=== Current Merkle Tree ===")
    tools_merkle_tree = aflow_manager.tool_manager.merkle_tree
    tools_merkle_tree.visualize()

    # 添加一个测试文件来演示差异
    test_file_content = '''def test_function():
    """This is a test function"""
    return "Hello, World!"
'''
    os.makedirs(os.path.dirname('tests/test_tools/test_add_dir/test_add.py'), exist_ok=True)
    with open('tests/test_tools/test_add_dir/test_add.py', 'w') as f:
        f.write(test_file_content)

    # 更新Merkle树并显示差异
    print("\n=== Merkle Tree Changes ===")
    tools_merkle_tree.update()
    tools_merkle_tree.visualize_diff()

    # 清理测试文件
    os.remove('tests/test_tools/test_add_dir/test_add.py')
    if len(os.listdir('tests/test_tools/test_add_dir')) == 0:
        os.rmdir('tests/test_tools/test_add_dir')
