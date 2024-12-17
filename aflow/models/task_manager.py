from typing import Dict, List, Any, Union
import importlib

class TaskManager:
    def __init__(self, neo4j_manager, retriever_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager

    def create_task(self, name: str, description: str, tool_names: List[str]) -> Dict:
        """Create a new task and associate with tools
        
        Args:
            name: Task name
            description: Task description
            tool_names: List of tool names
        """
        with self.neo4j_manager.get_session() as session:
            # Check if task exists
            existing_task = session.run("""
                MATCH (task:Task {name: $name})-[:USES]->(tool:Tool)
                RETURN task, collect(tool.name) as tools
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_task:
                task = existing_task["task"]
                task["tools"] = existing_task["tools"]
                return task
            
            # Check if all tools exist
            missing_tools = []
            for tool_name in tool_names:
                tool_exists = session.run("""
                    MATCH (tool:Tool {name: $tool_name})
                    RETURN count(tool) > 0 as exists
                    """,
                    tool_name=tool_name
                ).single()["exists"]
                
                if not tool_exists:
                    missing_tools.append(tool_name)
            
            if missing_tools:
                raise ValueError(f"The following tools do not exist: {', '.join(missing_tools)}")
            
            # Create embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
            
            # Create new task and associate with tools
            result = session.run("""
                CREATE (task:Task {
                    name: $name,
                    description: $description,
                    embedding: $embedding
                })
                WITH task
                UNWIND $tool_names as tool_name
                MATCH (tool:Tool {name: tool_name})
                CREATE (task)-[:USES {order: index(tool_name)}]->(tool)
                RETURN task, collect(tool.name) as tools
                LIMIT 1
                """,
                name=name,
                description=description,
                tool_names=tool_names,
                embedding=embedding
            )
            
            record = result.single()
            if record:
                task = record["task"]
                task["tools"] = record["tools"]
                return task
            return None

    def update_task(self, name: str, description: str = None, tool_names: List[str] = None) -> Dict:
        """Update existing task properties and tool associations
        
        Args:
            name: Task name
            description: Task description
            tool_names: List of tool names
        """
        with self.neo4j_manager.get_session() as session:
            # Check if task exists
            exists = session.run("""
                MATCH (task:Task {name: $name})
                RETURN count(task) > 0 as exists
                """,
                name=name
            ).single()["exists"]
            
            if not exists:
                raise ValueError(f"Task '{name}' does not exist. Use create_task to create new tasks.")
            
            # If new tools specified, check if they all exist
            if tool_names:
                missing_tools = []
                for tool_name in tool_names:
                    tool_exists = session.run("""
                        MATCH (tool:Tool {name: $tool_name})
                        RETURN count(tool) > 0 as exists
                        """,
                        tool_name=tool_name
                    ).single()["exists"]
                    
                    if not tool_exists:
                        missing_tools.append(tool_name)
                
                if missing_tools:
                    raise ValueError(f"The following tools do not exist: {', '.join(missing_tools)}")
            
            # Create new embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description if description else ''}")
            
            # Update task properties and tool associations
            if tool_names:
                result = session.run("""
                    MATCH (task:Task {name: $name})
                    SET task.embedding = $embedding
                    SET task.description = CASE WHEN $description IS NULL THEN task.description ELSE $description END
                    
                    WITH task
                    OPTIONAL MATCH (task)-[r:USES]->(:Tool)
                    DELETE r
                    
                    WITH task
                    UNWIND $tool_names as tool_name
                    MATCH (tool:Tool {name: tool_name})
                    CREATE (task)-[:USES {order: index(tool_name)}]->(tool)
                    
                    RETURN task, collect(tool.name) as tools
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    tool_names=tool_names,
                    embedding=embedding
                )
            else:
                result = session.run("""
                    MATCH (task:Task {name: $name})
                    SET task.embedding = $embedding
                    SET task.description = CASE WHEN $description IS NULL THEN task.description ELSE $description END
                    
                    WITH task
                    MATCH (task)-[:USES]->(tool:Tool)
                    
                    RETURN task, collect(tool.name) as tools
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    embedding=embedding
                )
            
            record = result.single()
            if record:
                task = record["task"]
                task["tools"] = record["tools"]
                return task
            return None

    def execute_task(self, task_name: str, context_variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute task by running all associated tools in order
        
        Args:
            task_name: Task name
            context_variables: Context variables
            
        Returns:
            Dict[str, Any]: Execution results and context variables
        """
        if context_variables is None:
            context_variables = {}
            
        with self.neo4j_manager.get_session() as session:
            # Get task tools in order
            result = session.run("""
                MATCH (task:Task {name: $task_name})-[r:USES]->(tool:Tool)
                RETURN task, tool
                ORDER BY r.order
                """,
                task_name=task_name
            )
            
            tools = []
            for record in result:
                tools.append(record["tool"])
            
            if not tools:
                raise ValueError(f"Task '{task_name}' not found or has no tools")
            
            # Execute tools in order
            results = {}
            for tool in tools:
                try:
                    # Import tool module dynamically
                    module_path = f"aflow.tools.{tool['category']}.{tool['name']}"
                    module = importlib.import_module(module_path)
                    
                    # Get tool function
                    tool_function = getattr(module, tool["name"])
                    
                    # Execute tool function with context variables
                    result = tool_function(**context_variables)
                    results[tool["name"]] = result
                    
                    # Update context variables if result is a dictionary
                    if isinstance(result, dict):
                        context_variables.update(result)
                        
                except ImportError:
                    raise ImportError(f"Tool module '{module_path}' not found")
                except AttributeError:
                    raise AttributeError(f"Tool function '{tool['name']}' not found in module '{module_path}'")
                except Exception as e:
                    raise Exception(f"Error executing tool '{tool['name']}': {str(e)}")
            
            return {
                "results": results,
                "context_variables": context_variables
            }

    def get_task(self, task_name: str) -> Dict:
        """Get task details"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task {name: $task_name})-[r:USES]->(tool:Tool)
                RETURN task, collect(tool.name) as tools
                LIMIT 1
                """,
                task_name=task_name
            ).single()
            
            if not result:
                return None
                
            task = result["task"]
            task["tools"] = result["tools"]
            return task

    def list_tasks(self) -> list:
        """List all tasks"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task)-[:USES]->(tool:Tool)
                RETURN task, collect(tool.name) as tools
                ORDER BY task.name
                """)
            
            tasks = []
            for record in result:
                task = record["task"]
                task["tools"] = record["tools"]
                tasks.append(task)
            return tasks

    def delete_task(self, task_name: str):
        """Delete unused task"""
        with self.neo4j_manager.get_session() as session:
            # Check if task is used in any workflow
            used = session.run("""
                MATCH (w:Workflow)-[:CONTAINS]->(t:Task {name: $task_name})
                RETURN count(w) > 0 as used
                """,
                task_name=task_name
            ).single()["used"]
            
            if used:
                raise ValueError(f"Cannot delete task '{task_name}' as it is used in one or more workflows")
            
            # Delete task if not used
            session.run("""
                MATCH (t:Task {name: $task_name})
                DETACH DELETE t
                """,
                task_name=task_name
            )
