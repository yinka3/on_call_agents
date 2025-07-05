from fastapi import FastAPI, HTTPException, UploadFile, BackgroundTasks
import os
import redis
import chromadb
from markdown import markdown
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
chromadb_client = chromadb.Client()

def parse_doc_docx(file_content):
    doc = Document(file_content)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    return text

def parse_md(file_content):
    html = markdown.markdown(file_content)
    text = ''.join(BeautifulSoup(html).findAll(text=True))
    return text

def parse_pdf(file_content):
    pages = PdfReader(file_content)
    text = ""
    for page in pages.pages:
        text += page
    return text

def run_workflow(filename, document):
    # store in chromadb, create collection, put it into chuck, embed it and store in vector DB
    pass
    

@app.post("/upload_doc")
async def upload_document(file: UploadFile, background: BackgroundTasks):

    mime_type = file.content_type
                
    content = await file.read()

    match (mime_type):
        case "text/plain":
            parsed = content.decode('utf-8')
        case "text/markdown":
            parsed = parse_md(content)
        case "application/pdf":
            parsed = parse_pdf(content)
        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            parsed = parse_doc_docx(content)
        case _:
            raise HTTPException(status_code=404, detail="File not supported, must be a txt, md, pdf or docx file")
    
    redis_client.set(f"Documentation: {file.filename}", parsed)
    background.add_task(run_workflow, file.filename, content)

    
    
        


    


