from google import genai
from google.genai import types
from chromadb import EmbeddingFunction
import os
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, task_type="retrieval_document"):
        self.task_type = task_type
        self.model = 'models/text-embedding-004'

    def __call__(self, input):
        out = genai.embed_content(model=self.model,
                                  content=input,
                                  task_type=self.task_type)
        return out.embedding