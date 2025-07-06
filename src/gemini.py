from google import genai
from google.genai import types
from chromadb import EmbeddingFunction
import os
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input):
        embedded_model = 'models/gemini-embedding-exp-03-07'
        out = gemini.models.embed_content(model=embedded_model, contents=input, 
                                          config=types.EmbedContentConfig(task_type="semantic_similarity"))

        return out.embeddings