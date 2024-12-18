from typing import Dict
from .merkle_tree import MerkleTree
import os
import ast
import time
import json

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
        print(f"Creating tool: {name} ({category})")
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
                MERGE (tool:Tool {name: $name})
                SET tool.description = $description,
                    tool.category = $category,
                    tool.embedding = $embedding
                RETURN tool
                """,
                name=name,
                description=description,
                category=category,
                embedding=embedding
            )
            
            record = result.single()
            
            # Print tool info without embedding for cleaner output
            tool_info = self._filter_tool_info(record['tool'] if record else None)
            print(f"Created tool: {tool_info}")
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

    def get_tool(self, name: str) -> Dict:
        """Get tool by name
        
        Args:
            name: Tool name
            
        Returns:
            Tool dictionary or None if not found
        """
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                LIMIT 1
            """, name=name)
            record = result.single()
            return record["tool"] if record else None

    def _load_merkle_state(self):
        with self.neo4j_manager.get_session() as session:
            # First, check if we have any state
            result = session.run("""
                MATCH (merkle:FileMerkleTree)
                RETURN count(merkle) as count
                """)
            if result.single()["count"] == 0:
                print("No previous Merkle tree state found")
                return

            # Load existing state
            result = session.run("""
                MATCH (merkle:FileMerkleTree)
                RETURN merkle.state as state
                LIMIT 1
                """)
            record = result.single()
            if record and record['state']:
                # Parse JSON string back to dict
                state_dict = json.loads(record['state'])
                self.merkle_tree.load_state(state_dict)

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
        print(f"Scanning tools directory: {self.tools_dir}")
        changes = self.merkle_tree.update()
        print(f"Found changes: {changes}")
        
        # Process changed files
        for file_path in changes['added'] | changes['modified']:
            print(f"Processing file: {file_path}")
            self._process_tool_file(file_path)
            
        # Remove deleted tools
        for file_path in changes['removed']:
            print(f"Removing file: {file_path}")
            self._remove_tool_file(file_path)
            
        # Save updated Merkle tree state
        self._save_merkle_state()

    def _process_tool_file(self, file_path: str):
        """Process a tool file and update database
        
        Args:
            file_path: Path to the tool file
        """
        try:
            print(f"Reading file: {file_path}")
            # Read and parse file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"File contents:\n{content}")
                tree = ast.parse(content)
            
            # Extract tool information
            tool_info = self._extract_tool_info(file_path, tree)
            print(f"Extracted tool info: {self._filter_tool_info(tool_info)}")
            if not tool_info:
                return
                
            # Create or update tools in database
            for info in tool_info:
                if info['exists']:
                    print(f"Updating tool: {info['name']}")
                    self.update_tool(
                        name=info['name'],
                        description=info['description'],
                        category=info['category']
                    )
                else:
                    print(f"Creating tool: {info['name']}")
                    self.create_tool(
                        name=info['name'],
                        description=info['description'],
                        category=info['category']
                    )
                
        except Exception as e:
            print(f"Error processing tool file {file_path}: {e}")

    def _extract_tool_info(self, file_path: str, tree: ast.AST) -> Dict:
        """Extract tool information from AST
        
        Args:
            file_path: Path to the tool file
            tree: AST of the tool file
            
        Returns:
            Dict containing tool information or None if not a valid tool
        """
        # Get module docstring for tool info
        module_doc = ast.get_docstring(tree)
        if not module_doc:
            # Try to get docstring from first class or function
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    module_doc = ast.get_docstring(node)
                    if module_doc:
                        break
            if not module_doc:
                return None

        # Extract category and tools from docstring
        category = 'uncategorized'
        tools = []
        docstring_lines = module_doc.split('\n')
        filtered_lines = []
        for line in docstring_lines:
            line = line.strip()
            lower_line = line.lower()
            if lower_line.startswith('category:'):
                category = line.split(':', 1)[1].strip()
            elif lower_line.startswith('tools:'):
                tools = [t.strip() for t in line.split(':', 1)[1].strip().split(',')]
            else:
                filtered_lines.append(line)
        
        if not tools:  # No tools specified
            return None
            
        module_doc = '\n'.join(filtered_lines)
        description = module_doc.strip()
        
        # Create/update each tool
        results = []
        for tool_name in tools:
            # Check if tool exists
            with self.neo4j_manager.get_session() as session:
                exists = session.run("""
                    MATCH (tool:Tool {name: $name})
                    RETURN count(tool) > 0 as exists
                    """,
                    name=tool_name
                ).single()["exists"]
                
            results.append({
                'name': tool_name,
                'description': description,
                'category': category,
                'exists': exists
            })
            
        return results

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
            # Convert state to JSON string before saving
            state_json = json.dumps(self.merkle_tree.get_state())
            session.run("""
                MERGE (merkle:FileMerkleTree)
                SET merkle.state = $state
                """,
                state=state_json)

    def _filter_tool_info(self, tool_info):
        """Filter out embedding from tool info for display purposes"""
        if not tool_info:
            return None
        if isinstance(tool_info, list):
            return [{k: v for k, v in tool.items() if k != 'embedding'} for tool in tool_info]
        return {k: v for k, v in tool_info.items() if k != 'embedding'}

    def list_tools(self) -> list:
        """List all tools in the database
        
        Returns:
            List of tool dictionaries
        """
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool)
                RETURN tool
            """)
            tools = [record["tool"] for record in result]
            return self._filter_tool_info(tools)

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
                     CASE 
                         WHEN tool.description CONTAINS $query_text THEN 1.0
                         WHEN tool.name CONTAINS $query_text THEN 0.8
                         ELSE 0.0 
                     END as text_score
                WITH tool, 
                     (vector_score + text_score) / 2 as hybrid_score
                ORDER BY hybrid_score DESC
                LIMIT $limit
                RETURN tool
                """,
                embedding=embedding,
                query_text=query,
                limit=limit
            )
            
            return [record["tool"] for record in results]

    def cleanup(self):
        """Clean up resources"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
