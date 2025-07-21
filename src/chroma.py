import chromadb
import os
import logging
from chromadb.utils import embedding_functions
from typing import Any, Union

chromadb_client = chromadb.PersistentClient("./chroma_db")
embedding_func = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
        api_key=os.environ["GEMINI_API_KEY"], task_type="RETRIEVAL_DOCUMENT")

def get_or_create_chroma_db(documents_to_embed: Union[None, Any], collection_name: str, metadata: Union[None, Any] = None, db_ids: Union[None, Any] = None, embed_function = embedding_func):
    collection = chromadb_client.get_or_create_collection(
        name=collection_name, 
        embedding_function=embed_function
    )

    if not documents_to_embed:
        logging.warning("No documents provided to embed.")
        return collection

    collection.upsert(
        documents=documents_to_embed,
        metadatas=metadata,
        ids=db_ids
    )
    
    return collection