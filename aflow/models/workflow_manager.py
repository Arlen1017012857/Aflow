from typing import Dict, List, Union, Any
import importlib

class WorkflowManager:
    def __init__(self, neo4j_manager, retriever_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager

    def create_workflow(self, name: str, description: str, tasks: List[Dict[str, Union[str, int]]]) -> Dict:
        """Create new workflow and add tasks
        
        Args:
            name: Workflow name
            description: Workflow description
            tasks: List of tasks, each containing name and order
        """
        with self.neo4j_manager.get_session() as session:
            # Check if workflow exists
            existing_workflow = session.run("""
                MATCH (w:Workflow {name: $name})
                RETURN w
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_workflow:
                return existing_workflow["w"]
            
            # Check if all tasks exist
            missing_tasks = []
            for task in tasks:
                task_exists = session.run("""
                    MATCH (t:Task {name: $task_name})
                    RETURN count(t) > 0 as exists
                    """,
                    task_name=task["name"]
                ).single()["exists"]
                
                if not task_exists:
                    missing_tasks.append(task["name"])
            
            if missing_tasks:
                raise ValueError(f"Cannot create workflow '{name}'. The following tasks do not exist: {', '.join(missing_tasks)}")
            
            # Create embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
            
            # Create new workflow and add tasks
            result = session.run("""
                CREATE (w:Workflow {
                    name: $name,
                    description: $description,
                    embedding: $embedding
                })
                
                WITH w
                UNWIND $tasks as task
                MATCH (t:Task {name: task.name})
                CREATE (w)-[r:CONTAINS {order: task.order}]->(t)
                
                RETURN w
                LIMIT 1
                """,
                name=name,
                description=description,
                tasks=tasks,
                embedding=embedding
            )
            
            record = result.single()
            return record["w"] if record else None

    def update_workflow(self, name: str, description: str = None, tasks: List[Dict[str, Union[str, int]]] = None) -> Dict:
        """Update existing workflow properties and tasks
        
        Args:
            name: Workflow name
            description: Workflow description
            tasks: List of tasks, each containing name and order
        """
        with self.neo4j_manager.get_session() as session:
            # Check if workflow exists
            exists = session.run("""
                MATCH (w:Workflow {name: $name})
                RETURN count(w) > 0 as exists
                """,
                name=name
            ).single()["exists"]
            
            if not exists:
                raise ValueError(f"Workflow '{name}' does not exist. Use create_workflow to create new workflows.")
            
            # If tasks specified, check if they all exist
            if tasks:
                missing_tasks = []
                for task in tasks:
                    task_exists = session.run("""
                        MATCH (t:Task {name: $task_name})
                        RETURN count(t) > 0 as exists
                        """,
                        task_name=task["name"]
                    ).single()["exists"]
                    
                    if not task_exists:
                        missing_tasks.append(task["name"])
                
                if missing_tasks:
                    raise ValueError(f"Cannot update workflow '{name}'. The following tasks do not exist: {', '.join(missing_tasks)}")
            
            # Create new embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description if description else ''}")
            
            # Update workflow properties and tasks
            if tasks:
                result = session.run("""
                    MATCH (w:Workflow {name: $name})
                    SET w.embedding = $embedding
                    SET w.description = CASE WHEN $description IS NULL THEN w.description ELSE $description END
                    
                    WITH w
                    OPTIONAL MATCH (w)-[r:CONTAINS]->(:Task)
                    DELETE r
                    
                    WITH w
                    UNWIND $tasks as task
                    MATCH (t:Task {name: task.name})
                    CREATE (w)-[r:CONTAINS {order: task.order}]->(t)
                    
                    RETURN w
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    tasks=tasks,
                    embedding=embedding
                )
            else:
                result = session.run("""
                    MATCH (w:Workflow {name: $name})
                    SET w.embedding = $embedding
                    SET w.description = CASE WHEN $description IS NULL THEN w.description ELSE $description END
                    RETURN w
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    embedding=embedding
                )
            
            record = result.single()
            return record["w"] if record else None

    def execute_tool(self, task: Dict, tool: Dict, context_variables: Dict[str, Any]):
        """Execute task using dynamic import"""
        try:
            # Import tool module dynamically
            module_path = f"aflow.tools.{tool['category']}.{tool['name']}"
            module = importlib.import_module(module_path)
            
            # Get tool function
            tool_function = getattr(module, tool["name"])
            
            # Execute tool function with context variables
            result = tool_function(**context_variables)
            return result
            
        except ImportError:
            raise ImportError(f"Tool module '{module_path}' not found")
        except AttributeError:
            raise AttributeError(f"Tool function '{tool['name']}' not found in module '{module_path}'")
        except Exception as e:
            raise Exception(f"Error executing tool '{tool['name']}': {str(e)}")

    def execute_workflow(self, workflow_name: str, context_variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute workflow
        
        Args:
            workflow_name: Workflow name
            context_variables: Context variables
            
        Returns:
            Dict[str, Any]: Execution results and context variables
        """
        if context_variables is None:
            context_variables = {}
            
        with self.neo4j_manager.get_session() as session:
            # Get workflow tasks in order
            result = session.run("""
                MATCH (w:Workflow {name: $workflow_name})-[r:CONTAINS]->(task:Task)-[:USES]->(tool:Tool)
                RETURN task, tool, r.order as task_order
                ORDER BY r.order
                """,
                workflow_name=workflow_name
            )
            
            tasks = []
            for record in result:
                tasks.append({
                    "task": record["task"],
                    "tool": record["tool"],
                    "order": record["task_order"]
                })
            
            if not tasks:
                raise ValueError(f"Workflow '{workflow_name}' not found or has no tasks")
            
            # Execute tasks in order
            results = {}
            for task_info in tasks:
                task = task_info["task"]
                tool = task_info["tool"]
                
                try:
                    # Execute tool and update context variables
                    result = self.execute_tool(task, tool, context_variables)
                    results[task["name"]] = result
                    
                    # Update context variables if result is a dictionary
                    if isinstance(result, dict):
                        context_variables.update(result)
                        
                except Exception as e:
                    raise Exception(f"Error executing task '{task['name']}': {str(e)}")
            
            return {
                "results": results,
                "context_variables": context_variables
            }
