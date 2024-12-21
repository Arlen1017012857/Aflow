# -*- coding: utf-8 -*-
import os
from aflow import AflowManager

# Set tools directory before initializing
os.environ['TOOLS_DIR'] = 'tests/test_tools'
aflow_manager = AflowManager()
# sync_tools_result = aflow_manager.sync_tools()
# print("Sync tools result:", sync_tools_result)

# # Create we_media workflow task
# task = aflow_manager.update_task(
#     name="we_media_workflow",
#     description="Workflow for we-media content publishing",
#     tool_names=[
#         "get_hot_news",
#         "select_topic",
#         "generate_content", 
#         "generate_image",
#         "search_image",
#         "auto_layout",
#         "publish_to_social_media"
#     ],
#     input_params=["user_need", "system_config"],
#     output_params=["formatted_content", "publish_result"]
# )

# print("\nCreated task:", task)

# Test workflow execution
result = aflow_manager.execute_task(
    "we_media_workflow",
    context_variables={
        "user_need": "Tech news",
        "system_config": {"platform": "哔哩哔哩"}
    }
)

# 美化输出
import json

print("\nWorkflow Execution Result:")
print(json.dumps(result, ensure_ascii=False, indent=4))