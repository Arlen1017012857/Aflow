from typing import Dict, List, Any, Union
import importlib
import inspect
import os
import sys
import importlib.util

class TaskManager:
    def __init__(self, neo4j_manager, retriever_manager, tool_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager
        self.tool_manager = tool_manager

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
                MATCH (task:Task {name: $name})
                RETURN task
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_task:
                return self._filter_node_info(existing_task["task"])
            
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
                UNWIND range(0, size($tool_names)-1) as idx
                WITH task, $tool_names[idx] as tool_name, idx
                MATCH (tool:Tool {name: tool_name})
                MERGE (task)-[:USES {order: idx}]->(tool)
                RETURN task
                """,
                name=name,
                description=description,
                tool_names=tool_names,
                embedding=embedding,
                input_params=input_params,
                output_params=output_params
            )
            
            record = result.single()
            return self._filter_node_info(record["task"]) if record else None

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
                raise ValueError(f"Task {name} does not exist")
            
            # Check if all tools exist if tool_names provided
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
            
            # Update task properties
            update_query = """
                MATCH (task:Task {name: $name})
            """
            
            if description or tool_names or input_params is not None or output_params is not None:
                update_query += "SET "
                updates = []
                
                if description:
                    updates.append("task.description = $description")
                    # Update embedding if description changes
                    embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
                    updates.append("task.embedding = $embedding")
                
                if input_params is not None:
                    updates.append("task.input_params = $input_params")
                
                if output_params is not None:
                    updates.append("task.output_params = $output_params")
                
                update_query += ", ".join(updates)
            
            if tool_names:
                update_query += """
                WITH task
                MATCH (task)-[r:USES]->(:Tool)
                DELETE r
                WITH task
                UNWIND range(0, size($tool_names)-1) as idx
                WITH task, $tool_names[idx] as tool_name, idx
                MATCH (tool:Tool {name: tool_name})
                MERGE (task)-[:USES {order: idx}]->(tool)
                """
            
            update_query += " RETURN task"
            
            result = session.run(
                update_query,
                name=name,
                description=description,
                tool_names=tool_names,
                input_params=input_params,
                output_params=output_params,
                embedding=embedding if description else None
            )
            
            record = result.single()
            return self._filter_node_info(record["task"]) if record else None

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
            context_variables = context_variables or {}
            
            for tool in tools:
                try:
                    # Get tool category and name
                    category = tool['category']
                    tool_name = tool['name']
                    
                    # Get tool function from tool manager
                    tool_function = self.tool_manager.get_tool_function(tool_name)
                    
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
                        raise ValueError(f"Missing required parameters for tool '{tool_name}': {', '.join(missing_params)}")
                    
                    # Execute tool function with matched parameters
                    print(f"Executing {category}: {tool_name} with params: {tool_params}")  # Debug output
                    result = tool_function(**tool_params)
                    results[tool_name] = result
                    
                    # Update context variables for next tool
                    if isinstance(result, dict):
                        context_variables.update(result)
                    else:
                        # If result is not a dict, store it with the tool name as key
                        context_variables[tool_name] = result
                        
                        # Get the return annotation from the function if available
                        return_annotation = inspect.signature(tool_function).return_annotation
                        if return_annotation != inspect.Signature.empty:
                            # If the return annotation is a string, use it as the variable name
                            if isinstance(return_annotation, str):
                                context_variables[return_annotation] = result
                        
                        # If no return annotation, try to infer from docstring
                        docstring = inspect.getdoc(tool_function)
                        if docstring:
                            # Look for "Returns:" section in docstring
                            lines = docstring.split('\n')
                            for i, line in enumerate(lines):
                                if 'Returns:' in line and i + 1 < len(lines):
                                    # Next line might contain the return variable name
                                    return_desc = lines[i + 1].strip()
                                    # Try to extract variable name from description
                                    if ':' in return_desc:
                                        var_name = return_desc.split(':')[0].strip()
                                        context_variables[var_name] = result
                                    break
                        
                    print(f"Updated context: {context_variables}")  # Debug output
                        
                except Exception as e:
                    print(f"Error executing {tool_name}: {str(e)}")  # Debug output
                    raise RuntimeError(f"Error executing tool '{tool_name}': {str(e)}")
            
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
            return self._filter_node_info(task)

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
                tasks.append(self._filter_node_info(task))
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

    def _filter_node_info(self, node_info):
        """Filter out embedding from node info for display purposes"""
        if not node_info:
            return None
        if isinstance(node_info, list):
            return [{k: v for k, v in node.items() if k != 'embedding'} for node in node_info]
        return {k: v for k, v in node_info.items() if k != 'embedding'}
