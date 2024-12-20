from typing import Dict, List, Any, Union
import importlib
import inspect

class TaskManager:
    def __init__(self, neo4j_manager, retriever_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager

    def create_task(self, name: str, description: str, tool_names: List[str], 
                   input_params: List[str] = None, output_params: List[str] = None) -> Dict:
        """Create a new task and associate with tools
        
        Args:
            name: Task name
            description: Task description
            tool_names: List of tool names
            input_params: List of required input parameter names
            output_params: List of output parameter names to return
        """
        if input_params is None:
            input_params = []
        if output_params is None:
            output_params = []
            
        with self.neo4j_manager.get_session() as session:
            # Check if task exists
            existing_task = session.run("""
                MATCH (task:Task {name: $name})-[:USES]->(tool:Tool)
                WITH task, tool ORDER BY tool.order
                WITH task, collect(tool) as tools
                RETURN task, tools
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
                    embedding: $embedding,
                    input_params: $input_params,
                    output_params: $output_params
                })
                WITH task
                UNWIND $tool_names as tool_name
                MATCH (tool:Tool {name: tool_name})
                CREATE (task)-[:USES {order: index(tool_name)}]->(tool)
                
                WITH task
                MATCH (task)-[r:USES]->(tool:Tool)
                WITH task, tool ORDER BY r.order
                WITH task, collect(tool) as tools
                RETURN task, tools
                LIMIT 1
                """,
                name=name,
                description=description,
                tool_names=tool_names,
                embedding=embedding,
                input_params=input_params,
                output_params=output_params
            )
            
            record = result.single()
            if record:
                task = record["task"]
                task["tools"] = record["tools"]
                return task
            return None

    def update_task(self, name: str, description: str = None, tool_names: List[str] = None,
                   input_params: List[str] = None, output_params: List[str] = None) -> Dict:
        """Update existing task properties and tool associations
        
        Args:
            name: Task name
            description: Task description
            tool_names: List of tool names
            input_params: List of required input parameter names
            output_params: List of output parameter names to return
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
                    SET task.input_params = CASE WHEN $input_params IS NULL THEN task.input_params ELSE $input_params END
                    SET task.output_params = CASE WHEN $output_params IS NULL THEN task.output_params ELSE $output_params END
                    
                    WITH task
                    OPTIONAL MATCH (task)-[r:USES]->(:Tool)
                    DELETE r
                    
                    WITH task
                    UNWIND $tool_names as tool_name
                    MATCH (tool:Tool {name: tool_name})
                    CREATE (task)-[:USES {order: index(tool_name)}]->(tool)
                    
                    WITH task
                    MATCH (task)-[r:USES]->(tool:Tool)
                    WITH task, tool ORDER BY r.order
                    WITH task, collect(tool) as tools
                    RETURN task, tools
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    tool_names=tool_names,
                    embedding=embedding,
                    input_params=input_params,
                    output_params=output_params
                )
            else:
                result = session.run("""
                    MATCH (task:Task {name: $name})
                    SET task.embedding = $embedding
                    SET task.description = CASE WHEN $description IS NULL THEN task.description ELSE $description END
                    SET task.input_params = CASE WHEN $input_params IS NULL THEN task.input_params ELSE $input_params END
                    SET task.output_params = CASE WHEN $output_params IS NULL THEN task.output_params ELSE $output_params END
                    
                    WITH task
                    MATCH (task)-[r:USES]->(tool:Tool)
                    WITH task, tool ORDER BY r.order
                    WITH task, collect(tool) as tools
                    RETURN task, tools
                    LIMIT 1
                    """,
                    name=name,
                    description=description,
                    embedding=embedding,
                    input_params=input_params,
                    output_params=output_params
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
            Dict[str, Any]: Task execution results containing:
                - results: All tool execution results
                - outputs: Specified output parameters
                - context_variables: Updated context variables
        """
        if context_variables is None:
            context_variables = {}
            
        with self.neo4j_manager.get_session() as session:
            # Get task and its tools in order
            result = session.run("""
                MATCH (task:Task {name: $task_name})-[r:USES]->(tool:Tool)
                WITH task, tool ORDER BY r.order
                WITH task, collect(tool) as tools
                RETURN task, tools
                LIMIT 1
                """,
                task_name=task_name
            ).single()
            
            if not result:
                raise ValueError(f"Task '{task_name}' not found")
                
            task = result["task"]
            tools = result["tools"]
            
            if not tools:
                raise ValueError(f"Task '{task_name}' has no associated tools")
            
            # Validate required input parameters
            input_params = task.get("input_params", [])
            missing_inputs = [param for param in input_params if param not in context_variables]
            if missing_inputs:
                raise ValueError(f"Missing required task input parameters: {', '.join(missing_inputs)}")
            
            # Execute tools in order
            results = {}
            for tool in tools:
                try:
                    # Import tool module dynamically
                    module_path = f"aflow.tools.{tool['category']}.{tool['name']}"
                    module = importlib.import_module(module_path)
                    
                    # Get tool function
                    tool_function = getattr(module, tool["name"])
                    
                    # Get function parameters
                    sig = inspect.signature(tool_function)
                    tool_params = {}
                    
                    # Check for required parameters and build tool_params
                    missing_params = []
                    for param_name, param in sig.parameters.items():
                        if param_name in context_variables:
                            tool_params[param_name] = context_variables[param_name]
                        elif param.default == param.empty:  # Parameter is required
                            missing_params.append(param_name)
                    
                    if missing_params:
                        raise ValueError(f"Missing required parameters for tool '{tool['name']}': {', '.join(missing_params)}")
                    
                    # Execute tool function with matched parameters
                    result = tool_function(**tool_params)
                    results[tool["name"]] = result
                    
                    # Update context variables if result is a dictionary
                    if isinstance(result, dict):
                        context_variables.update(result)
                        
                except ImportError:
                    raise ImportError(f"Tool module '{module_path}' not found")
                except AttributeError:
                    raise AttributeError(f"Tool function '{tool['name']}' not found in module '{module_path}'")
                except Exception as e:
                    raise RuntimeError(f"Error executing tool '{tool['name']}': {str(e)}")
            
            # Extract specified output parameters
            output_params = task.get("output_params", [])
            missing_outputs = [param for param in output_params if param not in context_variables]
            if missing_outputs:
                raise ValueError(f"Required output parameters not found in results: {', '.join(missing_outputs)}")
                
            outputs = {param: context_variables[param] 
                      for param in output_params 
                      if param in context_variables}
            
            return {
                "results": results,
                "outputs": outputs,
                "context_variables": context_variables
            }

    def get_task(self, task_name: str) -> Dict:
        """Get task details"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task {name: $task_name})-[r:USES]->(tool:Tool)
                WITH task, tool ORDER BY r.order
                WITH task, collect(tool) as tools
                RETURN task, tools
                LIMIT 1
                """,
                task_name=task_name
            ).single()
            
            if not result:
                return None
                
            task = result["task"]
            task["tools"] = result["tools"]
            return task

    def get_task_parameters(self, task_name: str) -> Dict[str, List[str]]:
        """Get task's defined input and output parameters
        
        Args:
            task_name: Task name
            
        Returns:
            Dict containing:
                - input_params: List of required input parameter names
                - output_params: List of output parameter names
        """
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task {name: $task_name})
                RETURN task
                LIMIT 1
                """,
                task_name=task_name
            ).single()
            
            if not result:
                raise ValueError(f"Task '{task_name}' not found")
                
            task = result["task"]
            return {
                "input_params": task.get("input_params", []),
                "output_params": task.get("output_params", [])
            }

    def list_tasks(self) -> list:
        """List all tasks"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task)-[r:USES]->(tool:Tool)
                WITH task, tool ORDER BY r.order
                WITH task, collect(tool) as tools
                RETURN task, tools
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
