from typing import Dict
from .merkle_tree import MerkleTree, MerkleNode
import os
import ast
import time
import json
import importlib
import sys

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
        category_name, tool_file = category.split('.')
        category_dir = os.path.join(self.tools_dir, category_name)
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

    def get_tool_function(self, tool_name: str):
        """Get tool function by name
        
        Args:
            tool_name: Name of the tool function
            
        Returns:
            Function object
        """
        # Get tool info from database
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool {name: $name})
                RETURN tool
                """,
                name=tool_name
            ).single()
            
            if not result:
                raise ValueError(f"Tool '{tool_name}' not found in database")
                
            tool = result['tool']
            category = tool['category']
            
            # Split category to get directory and file names
            category_name, module_name = category.split('.')
            
            # Construct module path
            module_path = os.path.join(self.tools_dir, category_name, f"{module_name}.py")
            module_path = os.path.normpath(module_path)
            
            if not os.path.exists(module_path):
                raise ImportError(f"Tool module not found at {module_path}")
                
            # Import module
            module_name = f"{category_name}.{module_name}"
            if module_name in sys.modules:
                module = sys.modules[module_name]
            else:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if not spec:
                    raise ImportError(f"Failed to create module spec for {module_path}")
                    
                module = importlib.util.module_from_spec(spec)
                if not module:
                    raise ImportError(f"Failed to create module from spec for {module_path}")
                    
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            
            # Get and return function
            if not hasattr(module, tool_name):
                raise AttributeError(f"Tool function '{tool_name}' not found in module {module_path}")
                
            return getattr(module, tool_name)

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
        
        # 获取发生变化的函数信息
        changed_functions = getattr(self.merkle_tree, 'changed_functions', {})
        print(f"Changed functions: {changed_functions}")
        # Process changed files
        for file_path in changes['added'] | changes['modified']:
            print(f"Processing file: {file_path}")
            
            # 获取要删除的函数
            if file_path in changed_functions:
                # 从previous_root中获取文件的旧状态
                rel_path = os.path.relpath(file_path, self.tools_dir)
                old_node = self.merkle_tree.previous_root
                for part in rel_path.split(os.sep):
                    old_node = old_node.children.get(part) if old_node else None
                
                # 获取旧状态中的函数
                old_funcs = set()
                if old_node:
                    old_funcs = {name for name, node in old_node.children.items() 
                               if node.is_function}
                
                # 获取新状态中的函数
                new_node = self.merkle_tree.root
                for part in rel_path.split(os.sep):
                    new_node = new_node.children.get(part) if new_node else None
                new_funcs = set()
                if new_node:
                    new_funcs = {name for name, node in new_node.children.items() 
                               if node.is_function}
                
                # 找出被删除的函数
                deleted_funcs = old_funcs - new_funcs
                if deleted_funcs:
                    print(f"Functions to delete: {deleted_funcs}")
                    for func_name in deleted_funcs:
                        self._remove_tool(func_name)
            
            # 处理新增或修改的函数
            self._process_tool_file(file_path, changed_functions.get(file_path, set()))
            
        # Remove deleted files
        for file_path in changes['removed']:
            print(f"Removing file: {file_path}")
            self._remove_tool_file(file_path)
            
        # Save updated Merkle tree state
        self._save_merkle_state()

    def _remove_tool(self, tool_name: str):
        """Remove a specific tool from database
        
        Args:
            tool_name: Name of the tool to remove
        """
        print(f"Removing tool: {tool_name}")
        with self.neo4j_manager.get_session() as session:
            session.run("""
                MATCH (tool:Tool {name: $name})
                DELETE tool
                """,
                name=tool_name
            )

    def _process_tool_file(self, file_path: str, changed_functions: set = None):
        """Process a tool file and update database
        
        Args:
            file_path: Path to the tool file
            changed_functions: Set of function names that have changed
        """
        # Get file's relative path for category
        rel_path = os.path.relpath(file_path, self.tools_dir)
        category = os.path.splitext(rel_path)[0].replace(os.sep, '.')

        # Parse file and extract tool info
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)
                tools_info = self._extract_tool_info(file_path, tree)
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            return

        # Get current functions from Merkle tree
        current_node = self.merkle_tree.root
        for part in rel_path.split(os.sep):
            current_node = current_node.children.get(part)
            if not current_node:
                print(f"File not found in Merkle tree: {file_path}")
                return

        print(f"\nProcessing file: {file_path}")
        print(f"Found {len(tools_info)} functions")
        
        # Process each function
        for func_name, info in tools_info.items():
            print(f"Processing function: {func_name}")
            # Skip if we're only processing changed functions
            if changed_functions is not None and func_name not in changed_functions:
                print(f"Function not changed: {func_name}")
                continue
            
            tool_name = info['name']
            description = info['docstring']
            
            # Check if tool exists
            with self.neo4j_manager.get_session() as session:
                exists = session.run("""
                    MATCH (tool:Tool {name: $name})
                    RETURN count(tool) > 0 as exists
                    """,
                    name=tool_name
                ).single()["exists"]
            
            try:
                if exists:
                    print(f"Updating tool: {tool_name}")
                    self.update_tool(
                        name=tool_name,
                        description=description,
                        category=category
                    )
                else:
                    print(f"Creating new tool: {tool_name} in category {category}")
                    self.create_tool(
                        name=tool_name,
                        description=description,
                        category=category
                    )
            except Exception as e:
                print(f"Error processing tool {tool_name}: {e}")

    def _extract_tool_info(self, file_path: str, tree: ast.AST) -> dict:
        """Extract tool information from AST
        
        Args:
            file_path: Path to the tool file
            tree: AST of the file
        
        Returns:
            Dict mapping function names to their info (name, docstring)
        """
        tools_info = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Get docstring if it exists
                docstring = ast.get_docstring(node) or ""
                
                tools_info[node.name] = {
                    'name': node.name,
                    'docstring': docstring
                }
                
        return tools_info

    def _remove_tool_file(self, file_path: str):
        """Remove tools from database when their file is deleted
        
        Args:
            file_path: Path to the deleted tool file
        """
        # 从previous_root中查找被删除的文件节点
        rel_path = os.path.relpath(file_path, self.tools_dir)
        current_node = self.merkle_tree.previous_root
        for part in rel_path.split(os.sep):
            current_node = current_node.children.get(part) if current_node else None
            if not current_node:
                return
        
        # 删除文件中的所有函数对应的工具
        for func_name, func_node in current_node.children.items():
            if not func_node.is_function:
                continue
                
            tool_name = func_node.function_name
            with self.neo4j_manager.get_session() as session:
                session.run("""
                    MATCH (tool:Tool {name: $name})
                    DELETE tool
                    """,
                    name=tool_name
                )
                print(f"Removed tool: {tool_name}")

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

    def sync_tools(self):
        """同步工具目录和数据库
        
        扫描tools_dir下的所有工具，对比数据库中相同category下的工具，
        以扫描的工具为准，更新、添加或删除数据库中的工具。
        
        Returns:
            Dict: 包含同步结果的字典，格式为：
                {
                    'added': [{'name': str, 'category': str}],
                    'updated': [{'name': str, 'category': str}],
                    'removed': [{'name': str, 'category': str}]
                }
        """
        print(f"Synchronizing tools from {self.tools_dir}")
        
        # 跟踪同步操作
        sync_result = {
            'added': [],
            'updated': [],
            'removed': []
        }
        
        # 1. 获取文件系统中的所有工具
        fs_tools = {}  # {category: {name: (description, node)}}
        
        def scan_tools_dir(node: MerkleNode):
            if node.is_function:
                # 获取category（从文件路径）
                file_path = node.path.split('::')[0]
                rel_path = os.path.relpath(file_path, self.tools_dir)
                category = os.path.splitext(rel_path)[0].replace(os.sep, '.')
                
                # 存储工具信息
                if category not in fs_tools:
                    fs_tools[category] = {}
                fs_tools[category][node.function_name] = (node.function_doc or "", node)
            else:
                # 递归处理子节点
                for child in node.children.values():
                    scan_tools_dir(child)
        
        # 构建新的Merkle树并扫描工具
        self.merkle_tree.root = self.merkle_tree._build_tree(self.tools_dir)
        scan_tools_dir(self.merkle_tree.root)
        
        # 2. 获取数据库中的所有工具
        with self.neo4j_manager.get_session() as session:
            result = session.run("""
                MATCH (tool:Tool)
                RETURN tool.name as name, tool.description as description, 
                       tool.category as category
            """)
            db_tools = {}  # {category: {name: description}}
            for record in result:
                category = record['category']
                if category not in db_tools:
                    db_tools[category] = {}
                db_tools[category][record['name']] = record['description']
        
        # 3. 对比并同步
        # 3.1 处理每个category
        all_categories = set(fs_tools.keys()) | set(db_tools.keys())
        for category in all_categories:
            fs_category_tools = fs_tools.get(category, {})
            db_category_tools = db_tools.get(category, {})
            
            # 3.2 找出需要添加、更新和删除的工具
            all_tools = set(fs_category_tools.keys()) | set(db_category_tools.keys())
            for tool_name in all_tools:
                if tool_name in fs_category_tools:
                    description, node = fs_category_tools[tool_name]
                    if tool_name not in db_category_tools:
                        # 添加新工具
                        print(f"Adding tool: {tool_name} in {category}")
                        self.create_tool(tool_name, description, category)
                        sync_result['added'].append({
                            'name': tool_name,
                            'category': category
                        })
                    elif db_category_tools[tool_name] != description:
                        # 更新已有工具
                        print(f"Updating tool: {tool_name} in {category}")
                        self.update_tool(tool_name, description, category)
                        sync_result['updated'].append({
                            'name': tool_name,
                            'category': category
                        })
                else:
                    # 删除不存在的工具
                    print(f"Removing tool: {tool_name} from {category}")
                    self._remove_tool(tool_name)
                    sync_result['removed'].append({
                        'name': tool_name,
                        'category': category
                    })
        
        print("Tool synchronization completed")
        return sync_result

    def cleanup(self):
        """Clean up resources"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
