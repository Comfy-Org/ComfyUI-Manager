"""
Mock PromptServer for testing purposes
"""

class MockRoutes:
    """
    Mock routing class with method decorators
    """
    def __init__(self):
        self.routes = {}
        
    def get(self, path):
        """Decorator for GET routes"""
        def decorator(f):
            self.routes[('GET', path)] = f
            return f
        return decorator
        
    def post(self, path):
        """Decorator for POST routes"""
        def decorator(f):
            self.routes[('POST', path)] = f
            return f
        return decorator
        
    def put(self, path):
        """Decorator for PUT routes"""
        def decorator(f):
            self.routes[('PUT', path)] = f
            return f
        return decorator
        
    def delete(self, path):
        """Decorator for DELETE routes"""
        def decorator(f):
            self.routes[('DELETE', path)] = f
            return f
        return decorator


class PromptServer:
    """
    Mock implementation of the PromptServer class
    """
    instance = None
    inst = None
    
    def __init__(self):
        self.routes = MockRoutes()
        self.registered_paths = set()
        self.base_url = "http://127.0.0.1:8188"  # Assuming server is running on default port
        self.queue_lock = None
        
    def add_route(self, method, path, handler, *args, **kwargs):
        """
        Add a mock route to the server
        """
        self.routes.routes[(method.upper(), path)] = handler
        self.registered_paths.add(path)
        
    async def send_msg(self, message, data=None):
        """
        Mock send_msg method (does nothing in the mock)
        """
        pass
        
    def send_sync(self, message, data=None):
        """
        Mock send_sync method (does nothing in the mock)
        """
        pass