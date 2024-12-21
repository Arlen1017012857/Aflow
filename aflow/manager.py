from typing import Dict, List, Union, Any
from .database import Neo4jManager, IndexManager
from .retrieval import RetrieverManager
from .models import ToolManager, TaskManager, WorkflowManager
from .config import load_config

class AflowManager:
    def __init__(self):
        """Initialize workflow manager using configuration from .env file"""
        # Load configuration
        config = load_config()
        
        # Initialize database connection
        self.neo4j_manager = Neo4jManager(
            uri=config['neo4j']['uri'],
            user=config['neo4j']['user'],
            password=config['neo4j']['password'],
            database=config['neo4j']['database']
        )
        
        # Initialize index manager and create indexes
        self.index_manager = IndexManager(self.neo4j_manager)
        self.index_manager.init_indexes()
        
        # Initialize retriever manager
        self.retriever_manager = RetrieverManager(
            neo4j_manager=self.neo4j_manager,
            embedder_config=config['embedder']
        )
        
        # Initialize model managers
        self.tool_manager = ToolManager(self.neo4j_manager, self.retriever_manager, config['tools_dir'])
        self.task_manager = TaskManager(self.neo4j_manager, self.retriever_manager, self.tool_manager)
        self.workflow_manager = WorkflowManager(self.neo4j_manager, self.retriever_manager, self.task_manager)

    def create_tool(self, name: str, description: str, category: str = 'uncategorized') -> Dict:
        """Create a new tool or return existing one"""
        return self.tool_manager.create_tool(name, description, category)

    def update_tool(self, name: str, description: str = None, category: str = None) -> Dict:
        """Update existing tool properties"""
        return self.tool_manager.update_tool(name, description, category)
    
    def get_tool(self, tool_name: str) -> Dict:
        """Get tool details"""
        return self.tool_manager.get_tool(tool_name)

    def list_tools(self) -> list:
        """List all tools"""
        return self.tool_manager.list_tools()

    def scan_tools(self):
        """Scan tools directory for new tools"""
        return self.tool_manager.scan_tools()

    def sync_tools(self):
        """Sync tools directory and database"""
        return self.tool_manager.sync_tools()


    def create_task(self, name: str, description: str, tool_names: List[str], input_params: List[str], output_params: List[str]) -> Dict:
        """Create a new task and associate with tool"""
        return self.task_manager.create_task(name, description, tool_names, input_params, output_params)

    def update_task(self, name: str, description: str = None, tool_names: List[str] = None, input_params: List[str] = None, output_params: List[str] = None) -> Dict:
        """Update existing task properties and tool association"""
        return self.task_manager.update_task(name, description, tool_names, input_params, output_params)

    def execute_task(self, task_name: str, context_variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute task with given parameters"""
        return self.task_manager.execute_task(task_name, context_variables)

    def get_task(self, task_name: str) -> Dict:
        """Get task details"""
        return self.task_manager.get_task(task_name)

    def list_tasks(self) -> list:
        """List all tasks"""
        return self.task_manager.list_tasks()

    def delete_task(self, task_name: str):
        """Delete unused task"""
        self.task_manager.delete_task(task_name)

    def create_workflow(self, name: str, description: str, tasks: List[Dict[str, Union[str, int]]]) -> Dict:
        """Create new workflow and add tasks"""
        return self.workflow_manager.create_workflow(name, description, tasks)

    def update_workflow(self, name: str, description: str = None, tasks: List[Dict[str, Union[str, int]]] = None) -> Dict:
        """Update existing workflow properties and tasks"""
        return self.workflow_manager.update_workflow(name, description, tasks)

    def search_workflows(self, query: str, top_k: int = 5):
        """Search workflows using hybrid retrieval"""
        return self.retriever_manager.search_workflows(query, top_k)

    def search_tasks(self, query: str, top_k: int = 5):
        """Search tasks using hybrid retrieval"""
        return self.retriever_manager.search_tasks(query, top_k)

    def search_tools(self, query: str, top_k: int = 5):
        """Search tools using hybrid retrieval"""
        return self.retriever_manager.search_tools(query, top_k)

    def execute_workflow(self, workflow_name: str, context_variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute workflow"""
        return self.workflow_manager.execute_workflow(workflow_name, context_variables)

    def close(self):
        """Close database connection"""
        self.neo4j_manager.close()
