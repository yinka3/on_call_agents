import logging
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException, UploadFile, BackgroundTasks
import os
import re
import redis
import chromadb
from slack import slack_client, get_or_create_chroma_db
from markdown import markdown
from bs4 import BeautifulSoup, ResultSet
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter


app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
chromadb_client = chromadb.Client()


def parse_md(file_content: bytes):
    content_str = file_content.decode()
    html = markdown(content_str, extensions=['fenced_code', 'tables'])
    soup: BeautifulSoup = BeautifulSoup(html, 'html.parser')
    sections = []
    results: ResultSet[Any] = soup.find_all(re.compile('^h[1-3]$'))
    for header in results:
        section_content = []
        for sub_header in header.find_next_siblings():
            if sub_header.name and re.match('^h[1-3]$', sub_header.name) and int(sub_header.name[1]) <= int(header.name[1]):
                break

            if sub_header.name:
                section_content.append(sub_header.get_text(separator=" ", strip=True))
        
        sections.append({
            'header_level': int(header.name[1]),
            'header_text': header.get_text(strip=True),
            'content': '\n'.join(section_content)
        })

    return sections


def parse_pdf(file_content):
    pages = PdfReader(file_content)
    return pages


def chuck_it_markdown(contents: List[Dict], max_chuck_size: int = 512, chunk_overlap: int = 50, snippet: int = 75):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=max_chuck_size, chunk_overlap=chunk_overlap)
    texts = []
    for content in contents:
        if len(content["content"]) > max_chuck_size:
            sub_chunks = text_splitter.split_text(content["content"])
            for sub in sub_chunks:
                texts.append({
                    'metadata': {
                        'header_level': content['header_level'],
                        'header_text': content['header_text'],
                        "preview": sub[:snippet]
                    },
                    'text': sub
                })
        else:
            texts.append({
                'metadata': {
                    'header_level': content['header_level'],
                    'header_text': content['header_text'],
                    "preview": content["content"][:snippet]
                },
                'text': content['content']
            })

    return texts

def chuck_it_pdf(content: PdfReader, max_chuck_size = 1024, chunk_overlap = 120, snippet: int = 75):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=max_chuck_size, chunk_overlap=chunk_overlap)
    texts = []

    for i, page in enumerate(content.pages):
        if len(page.extract_text()) > max_chuck_size:
            sub_texts = text_splitter.split_text(page.extract_text())
            for sub in sub_texts:
                texts.append(
                    {
                        "text": sub,
                        "metadata" : {
                            "preview": sub[:snippet],
                            "page_num": i + 1
                        }
                    })
        else:
            texts.append({
                "metadata": {
                    "page_num": i + 1,
                    "preview": page.extract_text()[:snippet]
                },
                "text": page.extract_text()
            })

    return texts


def run_workflow(filename, filecontent, doc_type):
    chunks = None
    if doc_type == "markdown":
        try:
            parsed = parse_md(file_content=filecontent)
            chunks = chuck_it_markdown(parsed)
        except Exception as e:
            logging.error(f"something went wrong with {filename}, its content type is {doc_type}, error: {e}")

    elif doc_type == "pdf":
        try:
            parsed = parse_pdf(file_content=filecontent)
            chunks = chuck_it_pdf(parsed)
        except Exception as e:
            logging.error(f"something went wrong with {filename}, its content type is {doc_type}, error: {e}")
    
    if chunks:
        documents_to_embed = [chunk['text'] for chunk in chunks]
        metadatas_to_store = [chunk['metadata'] for chunk in chunks]
        ids_for_db = [f"{filename}-{i}" for i in range(len(chunks))]

        try:
            get_or_create_chroma_db(
                documents_to_embed=documents_to_embed,
                collection_name="client_documentation",
                metadata=metadatas_to_store,
                db_ids=ids_for_db
            )
            logging.info(f"Successfully stored {len(chunks)} chunks for {filename}.")
        except Exception as e:
            logging.error(f"Failed to store chunks for {filename} in ChromaDB: {e}")


    # searching into database next
@app.post("/upload_doc")
async def upload_document(file: UploadFile, background: BackgroundTasks):

    mime_type = file.content_type
                
    content = await file.read()
    type = None
    if mime_type == "text/markdown":
        type = "markdown"
    elif mime_type == "application/pdf":
        type = "pdf"
    else:
        raise HTTPException(status_code=404, detail="File not supported, must be a md or pdf file")
    
    background.add_task(run_workflow, file.filename, content, type)

    
    
        


    


