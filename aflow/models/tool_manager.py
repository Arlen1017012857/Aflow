from typing import Dict
from merkle_tree import MerkleTree
import os
import ast
import time

class ToolManager:
    def __init__(self, neo4j_manager, retriever_manager, tools_dir: str):
        """Initialize ToolManager
        
        Args:
            neo4j_manager: Neo4j database manager
            retriever_manager: Retriever manager for embeddings
            tools_dir: Root directory containing tool files
        """
        self.neo4j_manager = neo4j_manager
        self.retriever_manager = retriever_manager
        self.tools_dir = tools_dir
        
        # Create tools directory if it doesn't exist
        os.makedirs(self.tools_dir, exist_ok=True)
        
        # Initialize Merkle tree for file tracking
        self.merkle_tree = MerkleTree(self.tools_dir)
        self._load_merkle_state()
        
        # Initialize watchdog observer and perform initial scan
        self.observer = None
        self._setup_file_watcher()
        self.scan_tools()  # Initial scan

    def create_tool(self, name: str, description: str, category: str = 'uncategorized') -> Dict:
        """Create a new tool or return existing one
        
        Args:
            name: Tool name
            description: Tool description
            category: Tool category (will be created if doesn't exist)
        """
        # Create category directory if it doesn't exist
        category_dir = os.path.join(self.tools_dir, category)
        os.makedirs(category_dir, exist_ok=True)
        
        with self.neo4j_manager.get_session() as session:
            # Check if tool exists
            existing_tool = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                LIMIT 1
                """,
                name=name
            ).single()
            
            if existing_tool:
                return existing_tool["tool"]
            
            # Create embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description}")
            
            # Create new tool
            result = session.run("""
                CREATE (tool:Tool {
                    name: $name,
                    description: $description,
                    category: $category,
                    embedding: $embedding
                })
                RETURN tool
                LIMIT 1
                """,
                name=name,
                description=description,
                category=category,
                embedding=embedding
            )
            
            record = result.single()
            return record["tool"] if record else None

    def update_tool(self, name: str, description: str = None, category: str = None) -> Dict:
        """Update existing tool properties
        
        Args:
            name: Tool name
            description: Tool description
            category: Tool category
        """
        with self.neo4j_manager.get_session() as session:
            # Check if tool exists
            exists = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN count(tool) > 0 as exists
                """,
                name=name
            ).single()["exists"]
            
            if not exists:
                raise ValueError(f"Tool '{name}' does not exist. Use create_tool to create new tools.")
            
            # Create new embedding vector
            embedding = self.retriever_manager.embedder.embed_query(f"{name} {description if description else ''}")
            
            # Update tool properties
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                SET tool.embedding = $embedding
                SET tool.description = CASE WHEN $description IS NULL THEN tool.description ELSE $description END
                SET tool.category = CASE WHEN $category IS NULL THEN tool.category ELSE $category END
                RETURN tool
                LIMIT 1
                """,
                name=name,
                description=description,
                category=category,
                embedding=embedding
            )
            
            record = result.single()
            return record["tool"] if record else None

    def _load_merkle_state(self):
        # Load Merkle tree state from database
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (merkle:FileMerkleTree)
                RETURN merkle.state as state
                LIMIT 1
                """)
            record = result.single()
            if record:
                self.merkle_tree.load_state(record["state"])

    def _setup_file_watcher(self):
        """Setup watchdog observer to monitor file changes"""
        import watchdog.observers
        from watchdog.events import FileSystemEventHandler
        
        class ToolFileHandler(FileSystemEventHandler):
            def __init__(self, tool_manager):
                self.tool_manager = tool_manager
                self._last_scan = 0
                self._scan_delay = 1  # Minimum seconds between scans
                
            def on_any_event(self, event):
                # Skip non-Python files
                if event.is_directory or not event.src_path.endswith('.py'):
                    return
                    
                # Debounce scanning to avoid too frequent updates
                current_time = time.time()
                if current_time - self._last_scan >= self._scan_delay:
                    self.tool_manager.scan_tools()
                    self._last_scan = current_time
        
        self.observer = watchdog.observers.Observer()
        self.observer.schedule(ToolFileHandler(self), self.tools_dir, recursive=True)
        self.observer.start()

    def scan_tools(self):
        """Scan tools directory for changes and update tools in database"""
        changes = self.merkle_tree.update()
        
        # Process changed files
        for file_path in changes['added'] | changes['modified']:
            self._process_tool_file(file_path)
            
        # Remove deleted tools
        for file_path in changes['removed']:
            self._remove_tool_file(file_path)
            
        # Save updated Merkle tree state
        self._save_merkle_state()

    def _process_tool_file(self, file_path: str):
        """Process a tool file and update database
        
        Args:
            file_path: Path to the tool file
        """
        try:
            # Read and parse file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)
            
            # Extract tool information
            tool_info = self._extract_tool_info(tree, file_path)
            if not tool_info:
                return
                
            # Create or update tool in database
            if tool_info['exists']:
                self.update_tool(
                    name=tool_info['name'],
                    description=tool_info['description'],
                    category=tool_info['category']
                )
            else:
                self.create_tool(
                    name=tool_info['name'],
                    description=tool_info['description'],
                    category=tool_info['category']
                )
                
        except Exception as e:
            print(f"Error processing tool file {file_path}: {e}")

    def _extract_tool_info(self, tree: ast.AST, file_path: str) -> Dict:
        """Extract tool information from AST
        
        Args:
            tree: AST of the tool file
            file_path: Path to the tool file
            
        Returns:
            Dict containing tool information or None if not a valid tool
        """
        # Get tool category from directory structure
        rel_path = os.path.relpath(file_path, self.tools_dir)
        parts = rel_path.split(os.sep)
        if len(parts) < 2:
            return None
            
        category = parts[0]
        
        # Find tool class definition
        tool_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                tool_class = node
                break
                
        if not tool_class:
            return None
            
        # Extract tool information
        name = tool_class.name
        description = ast.get_docstring(tool_class) or f"Tool from {os.path.basename(file_path)}"
        
        # Check if tool exists
        with self.neo4j_manager.get_session() as session:
            exists = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN count(tool) > 0 as exists
                """,
                name=name
            ).single()["exists"]
            
        return {
            'name': name,
            'description': description,
            'category': category,
            'exists': exists
        }

    def _remove_tool_file(self, file_path: str):
        """Remove a tool from database when its file is deleted
        
        Args:
            file_path: Path to the deleted tool file
        """
        rel_path = os.path.relpath(file_path, self.tools_dir)
        parts = rel_path.split(os.sep)
        if len(parts) >= 2:
            tool_name = os.path.splitext(parts[1])[0]
            with self.neo4j_manager.get_session() as session:
                session.run("""
                    MATCH (tool:Tool {name: $name})
                    DELETE tool
                    """,
                    name=tool_name
                )

    def _save_merkle_state(self):
        # Save updated Merkle tree state in database
        with self.neo4j_manager.get_session() as session:
            session.run("""
                MERGE (merkle:FileMerkleTree)
                SET merkle.state = $state
                """,
                state=self.merkle_tree.get_state())

    def search_tools(self, query: str, limit: int = 10) -> list:
        """Search for tools using hybrid search (vector + text)
        
        Args:
            query: Search query
            limit: Maximum number of results to return
            
        Returns:
            List of matching tools
        """
        # Get query embedding
        embedding = self.retriever_manager.embedder.embed_query(query)
        
        # Perform hybrid search
        with self.neo4j_manager.get_session() as session:
            results = session.run("""
                MATCH (tool:Tool)
                WITH tool, 
                     gds.similarity.cosine(tool.embedding, $embedding) as vector_score,
                     apoc.text.score(tool.description, $query) as text_score
                WITH tool, 
                     (vector_score + text_score) / 2 as hybrid_score
                ORDER BY hybrid_score DESC
                LIMIT $limit
                RETURN tool
                """,
                embedding=embedding,
                query=query,
                limit=limit
            )
            
            return [record["tool"] for record in results]

    def cleanup(self):
        """Clean up resources"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
