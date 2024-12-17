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
        results = self.workflow_retriever.retrieve(query, top_k)
        return self.parse_search_results(results, "workflow")

    def search_tasks(self, query: str, top_k: int = 5):
        """Search tasks using hybrid retrieval"""
        results = self.task_retriever.retrieve(query, top_k)
        return self.parse_search_results(results, "task")

    def search_tools(self, query: str, top_k: int = 5):
        """Search tools using hybrid retrieval"""
        results = self.tool_retriever.retrieve(query, top_k)
        return self.parse_search_results(results, "tool")

    def parse_search_results(self, results, result_type: str = "workflow") -> List[Dict]:
        """Parse search results into dictionary format"""
        parsed_results = []
        
        for result in results:
            if result_type == "workflow":
                parsed_results.append({
                    "name": result["workflow_name"],
                    "description": result["workflow_description"],
                    "similarity_score": result["similarity_score"],
                    "tasks": result["tasks"]
                })
            elif result_type == "task":
                parsed_results.append({
                    "name": result["task_name"],
                    "description": result["task_description"],
                    "similarity_score": result["similarity_score"],
                    "tool": result["tool_name"],
                    "workflows": result["workflows"]
                })
            elif result_type == "tool":
                parsed_results.append({
                    "name": result["tool_name"],
                    "description": result["tool_description"],
                    "similarity_score": result["similarity_score"],
                    "used_by_tasks": result["used_by_tasks"]
                })
                
        return parsed_results
