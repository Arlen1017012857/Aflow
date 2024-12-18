"""File management tool for testing

This tool demonstrates file system operations.。。。

Category: system_tools
Tools: file_manager
"""

import os
import shutil
from typing import List, Dict

class FileManager:
    """File management tool for testing
    
    This tool demonstrates file system operations.
    """
    
    def list_files(self, directory: str) -> List[str]:
        """List all files in a directory
        
        Args:
            directory: Path to directory
            
        Returns:
            List of file names in the directory
        """
        return os.listdir(directory)
    
    def get_file_info(self, file_path: str) -> Dict:
        """Get information about a file
        
        Args:
            file_path: Path to file
            
        Returns:
            Dict containing file information
        """
        stat = os.stat(file_path)
        return {
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "is_file": os.path.isfile(file_path),
            "is_dir": os.path.isdir(file_path)
        }
    
    def copy_file(self, src: str, dst: str) -> bool:
        """Copy a file
        
        Args:
            src: Source file path
            dst: Destination file path
            
        Returns:
            True if successful, False otherwise
        """
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            print(f"Error copying file: {e}")
            return False
    
    def delete_file(self, file_path: str) -> bool:
        """Delete a file
        
        Args:
            file_path: Path to file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
            return True
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
