import os
from pymongo import MongoClient
from pymongo.database import Database

class MongoDBManager:
    _client = None
    _db = None

    @classmethod
    def get_database(cls) -> Database:
        if cls._db is None:
            mongo_uri = os.getenv("MONGO_URI")
            db_name = os.getenv("MONGO_DB_NAME", "pintaebook_nosql")
            
            if not mongo_uri:
                raise ValueError("Variable de entorno MONGO_URI no configurada.")
            
            # Conexión persistente con timeout de 5 segundos
            cls._client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            cls._db = cls._client[db_name]
        return cls._db

    @classmethod
    def close_connection(cls):
        if cls._client:
            cls._client.close()
            cls._client = None
            cls._db = None

def get_mongo_db() -> Database:
    """Función helper para inyectar la base documental en los servicios."""
    return MongoDBManager.get_database()