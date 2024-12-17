from typing import Dict

class TaskManager:
    def __init__(self, neo4j_manager, retriever_manager):
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager

    def create_task(self, name: str, description: str, tool_name: str) -> Dict:
        """Create a new task and associate with tool
        
        Args:
            name: Task name
            description: Task description
            tool_name: Tool name
        """
        with self.neo4j_manager.get_session() as session:
            # Check if task exists
            existing_task = session.run("""
                MATCH (task:Task {name: $name})-[:USES]->(tool:Tool)
                RETURN task, tool
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_task:
                return existing_task["task"]
            
            # Check if tool exists
            tool = session.run("""
                MATCH (tool:Tool {name: $tool_name})
                RETURN tool
                LIMIT 1
                """,
                tool_name=tool_name
            ).single()
            
            if not tool:
                raise ValueError(f"Tool '{tool_name}' does not exist")
            
            # Create embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
            
            # Create new task and associate with tool
            result = session.run("""
                MATCH (tool:Tool {name: $tool_name})
                CREATE (task:Task {
                    name: $name,
                    description: $description,
                    embedding: $embedding
                })
                CREATE (task)-[:USES]->(tool)
                RETURN task
                LIMIT 1
                """,
                name=name,
                description=description,
                tool_name=tool_name,
                embedding=embedding
            )
            
            record = result.single()
            return record["task"] if record else None

    def update_task(self, name: str, description: str = None, tool_name: str = None) -> Dict:
        """Update existing task properties and tool association
        
        Args:
            name: Task name
            description: Task description
            tool_name: Tool name
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
            
            # If new tool specified, check if it exists
            if tool_name:
                tool = session.run("""
                    MATCH (tool:Tool {name: $tool_name})
                    RETURN tool
                    LIMIT 1
                    """,
                    tool_name=tool_name
                ).single()
                
                if not tool:
                    raise ValueError(f"Tool '{tool_name}' does not exist")
            
            # Create new embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description if description else ''}")
            
            # Update task properties and tool association
            result = session.run("""
                MATCH (task:Task {name: $name})
                SET task.embedding = $embedding
                SET task.description = CASE WHEN $description IS NULL THEN task.description ELSE $description END
                
                WITH task
                OPTIONAL MATCH (task)-[r:USES]->(:Tool)
                WHERE $tool_name IS NOT NULL
                DELETE r
                
                WITH task
                MATCH (tool:Tool {name: CASE WHEN $tool_name IS NULL THEN task.tool_name ELSE $tool_name END})
                MERGE (task)-[:USES]->(tool)
                
                RETURN task
                LIMIT 1
                """,
                name=name,
                description=description,
                tool_name=tool_name,
                embedding=embedding
            )
            
            record = result.single()
            return record["task"] if record else None

    def get_task(self, task_name: str) -> Dict:
        """Get task details"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task {name: $task_name})-[:USES]->(tool:Tool)
                RETURN task, tool
                LIMIT 1
                """,
                task_name=task_name
            ).single()
            
            if not result:
                return None
                
            task = result["task"]
            task["tool"] = result["tool"]["name"]
            return task

    def list_tasks(self) -> list:
        """List all tasks"""
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (task:Task)-[:USES]->(tool:Tool)
                RETURN task, tool
                ORDER BY task.name
                """)
            
            tasks = []
            for record in result:
                task = record["task"]
                task["tool"] = record["tool"]["name"]
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
