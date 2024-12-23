from typing import Dict, List
from neo4j_graphrag.retrievers import HybridCypherRetriever
from neo4j_graphrag.embeddings.openai import OpenAIEmbeddings


class RetrieverManager:
    def __init__(self, neo4j_manager, embedder_config):
        """Initialize retriever manager with configuration
        
        Args:
            neo4j_manager: Neo4j database manager
            embedder_config: Embedder configuration dictionary containing api_key, base_url, and model
        """
        self.neo4j_manager = neo4j_manager
        self.embedder = OpenAIEmbeddings(
            base_url=embedder_config['base_url'],
            api_key=embedder_config['api_key'],
            model=embedder_config['model']
        )
        
        self.workflow_retriever = self._create_workflow_retriever()
        self.task_retriever = self._create_task_retriever()
        self.tool_retriever = self._create_tool_retriever()

    def _create_workflow_retriever(self):
        return HybridCypherRetriever(
            driver=self.neo4j_manager.driver,
            vector_index_name="workflowEmbedding",
            fulltext_index_name="workflowFulltext",
            embedder=self.embedder,
            retrieval_query="""
            MATCH (node)
            WHERE node:Workflow
            OPTIONAL MATCH (node)-[r:CONTAINS]->(task:Task)-[:USES]->(tool:Tool)
            WITH node, task, tool, r.order as task_order, score
            ORDER BY node.name, task_order
            RETURN 
                node.name as workflow_name,
                node.description as workflow_description,
                score as similarity_score,
                collect({
                    name: task.name,
                    description: task.description,
                    order: task_order,
                    tool: tool.name
                }) as tasks
            """,
            neo4j_database=self.neo4j_manager.database
        )

    def _create_task_retriever(self):
        return HybridCypherRetriever(
            driver=self.neo4j_manager.driver,
            vector_index_name="taskEmbedding",
            fulltext_index_name="taskFulltext",
            embedder=self.embedder,
            retrieval_query="""
            MATCH (node)
            WHERE node:Task
            OPTIONAL MATCH (node)-[:USES]->(tool:Tool)
            OPTIONAL MATCH (workflow:Workflow)-[r:CONTAINS]->(node)
            WITH node, tool, workflow, r.order as task_order, score
            RETURN 
                node.name as task_name,
                node.description as task_description,
                score as similarity_score,
                tool.name as tool_name,
                collect({
                    name: workflow.name,
                    order: task_order
                }) as workflows
            """,
            neo4j_database=self.neo4j_manager.database
        )

    def _create_tool_retriever(self):
        return HybridCypherRetriever(
            driver=self.neo4j_manager.driver,
            vector_index_name="toolEmbedding",
            fulltext_index_name="toolFulltext",
            embedder=self.embedder,
            retrieval_query="""
            MATCH (node)
            WHERE node:Tool
            OPTIONAL MATCH (task:Task)-[:USES]->(node)
            WITH node, collect(task.name) as used_by_tasks, score
            RETURN 
                node.name as tool_name,
                node.description as tool_description,
                score as similarity_score,
                used_by_tasks
            """,
            neo4j_database=self.neo4j_manager.database
        )

    def search_workflows(self, query: str, top_k: int = 5):
        """Search workflows using hybrid retrieval"""
        results = self.workflow_retriever.search(query_text=query, top_k=top_k)
        return self.parse_search_results(results, "workflow")

    def search_tasks(self, query: str, top_k: int = 5):
        """Search tasks using hybrid retrieval"""
        results = self.task_retriever.search(query_text=query, top_k=top_k)
        return self.parse_search_results(results, "task")

    def search_tools(self, query: str, top_k: int = 5):
        """Search tools using hybrid retrieval"""
        results = self.tool_retriever.search(query_text=query, top_k=top_k)
        return self.parse_search_results(results, "tool")

    def parse_search_results(self, results, result_type: str = "workflow") -> List[Dict]:
        """Parse search results into dictionary format"""
        parsed_results = []
        
        for item in results.items:
            content = item.content
            result_dict = {}
            
            if result_type == "workflow":
                # Parse workflow search results
                workflow_name = content.split("workflow_name='")[1].split("'")[0]
                workflow_desc = content.split("workflow_description='")[1].split("'")[0]
                similarity = float(content.split("similarity_score=")[1].split(" ")[0])
                tasks_str = content.split("tasks=")[1].strip(">").strip()
                tasks = eval(tasks_str)
                
                result_dict = {
                    "name": workflow_name,
                    "description": workflow_desc,
                    "similarity_score": similarity,
                    "tasks": tasks
                }
                
            elif result_type == "task":
                # Parse task search results
                task_name = content.split("task_name='")[1].split("'")[0]
                task_desc = content.split("task_description='")[1].split("'")[0]
                similarity = float(content.split("similarity_score=")[1].split(" ")[0])
                tool_name = content.split("tool_name='")[1].split("'")[0]
                workflows_str = content.split("workflows=")[1].strip(">").strip()
                workflows = eval(workflows_str)
                
                result_dict = {
                    "name": task_name,
                    "description": task_desc,
                    "similarity_score": similarity,
                    "tool": tool_name,
                    "workflows": workflows
                }
                
            elif result_type == "tool":
                # Parse tool search results
                tool_name = content.split("tool_name='")[1].split("'")[0]
                tool_desc = content.split("tool_description='")[1].split("'")[0]
                similarity = float(content.split("similarity_score=")[1].split(" ")[0])
                used_by_tasks_str = content.split("used_by_tasks=")[1].strip(">").strip()
                used_by_tasks = eval(used_by_tasks_str)
                
                result_dict = {
                    "name": tool_name,
                    "description": tool_desc,
                    "similarity_score": similarity,
                    "used_by_tasks": used_by_tasks
                }
            
            parsed_results.append(result_dict)
        
        return parsed_results
