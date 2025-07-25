import os
from typing import Optional
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile, status
from gemini import GeminiEmbeddingFunction
from chroma import get_or_create_chroma_db
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
app = FastAPI()


def search_codebase(search_query, results = 3):
    pass

def get_langchain_language_from_extension(extension: str) -> Optional[Language]:

    normalized_extension = extension.lstrip('.').lower()

    extension_to_language_map = {
        'cpp': 'cpp', 'cc': 'cpp', 'cxx': 'cpp', 'hpp': 'cpp', 'hxx': 'cpp',
        'go': 'go',
        'java': 'java',
        'kt': 'kotlin', 'kts': 'kotlin',
        'js': 'js', 'jsx': 'js',
        'ts': 'ts', 'tsx': 'ts',
        'php': 'php',
        'proto': 'proto',
        'py': 'python',
        'rst': 'rst',
        'rb': 'ruby',
        'rs': 'rust',
        'scala': 'scala', 'sc': 'scala',
        'swift': 'swift',
        'md': 'markdown', 'markdown': 'markdown',
        'tex': 'latex',
        'html': 'html', 'htm': 'html',
        'sol': 'sol',
        'cs': 'csharp',
        'cbl': 'cobol', 'cob': 'cobol',
        'c': 'c', 'h': 'c',
        'lua': 'lua',
        'pl': 'perl', 'pm': 'perl',
        'hs': 'haskell', 'lhs': 'haskell',
        'ex': 'elixir', 'exs': 'elixir',
        'ps1': 'powershell', 'psm1': 'powershell', 'psd1': 'powershell',
        'bas': 'visualbasic6', 'vb': 'visualbasic6'
    }

    language_string = extension_to_language_map.get(normalized_extension)

    if language_string:
        return language_string
    else:
        return None

def chunk_it(file, file_name, extention):
    ext = get_langchain_language_from_extension(extension=extention)
    if ext is None:
        raise ValueError()
    chunk = RecursiveCharacterTextSplitter.from_language(language=Language(ext))
    ids = [f"{file_name}_chunk_{i}" for i in range(len(file))]
    metadatas = [
        {"source_file": file_name, "chunk_index": i, "language": extention}
        for i in range(len(chunk))
    ]
    get_or_create_chroma_db(chunk, "code collection", metadata=metadatas, db_ids=ids)


@app.post()
async def upload_code(codebase: UploadFile, backgroundtask: BackgroundTasks):

    if not codebase.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    try:
        code_bytes = await codebase.read()
        decode = code_bytes.decode()
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    file_name = os.path.basename(codebase.filename)
    _, extention = os.path.splitext(codebase.filename)

    if extention == "":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    backgroundtask.add_task(chunk_it, decode, file_name, extention)




