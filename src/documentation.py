from fastapi import FastAPI, HTTPException, UploadFile, BackgroundTasks
import os
import re
import redis
import chromadb
from slack import slack_client, get_or_create_chroma_db
from markdown import markdown
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter


app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
chromadb_client = chromadb.Client()

def parse_doc_docx(file_content):
    doc = Document(file_content)
    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
    return text, "docx"

def parse_md(file_content: bytes):
    content_str = file_content.decode()
    html = markdown(content_str, extensions=['fenced_code', 'tables'])
    soup = BeautifulSoup(html, 'html.parser')
    sections = []

    for header in soup.find_all(re.compile('^h[1-3]$')):
        section_content = []
        for sub_header in header.find_nexxt_siblings():
            if sub_header.name and re.match('^h[1-3]$', sub_header.name) and int(sub_header.name[1]) <= int(header.name[1]):
                break

            if sub_header.name:
                section_content.append(sub_header.get_text(seperator=" ", strip=True))
        
        sections.append({
            'header_level': int(header.name[1]),
            'header_text': header.get_text(strip=True),
            'content': '\n'.join(section_content)
        })

    return sections, "markdown"


def parse_pdf(file_content):
    pages = PdfReader(file_content)
    text = ""
    for page in pages.pages:
        text += page
    return text, "pdf"


def chuck_it_markdown(contents, max_chuck_size: int = 512, chunk_overlap: int = 50):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=max_chuck_size, chunk_overlap=chunk_overlap)
    texts = []
    for content in contents:
        if len(content["content"]) > max_chuck_size:
            sub_chunks = text_splitter.split_text(content["content"])
            for sub in sub_chunks:
                texts.append({
                    'metadata': {
                        'header_level': content['header_level'],
                        'header_text': content['header_text']
                    },
                    'text': sub
                })
        else:
            texts.append({
                'metadata': {
                    'header_level': content['header_level'],
                    'header_text': content['header_text']
                },
                'text': content['content']
            })

    return texts

def chuck_it_pdf(content):
    pass

def chuck_it_docx(content):
    pass


def run_workflow(filename, document, doc_type):
    pass

 

@app.post("/upload_doc")
async def upload_document(file: UploadFile, background: BackgroundTasks):

    mime_type = file.content_type
                
    content = await file.read()
    type = None
    match (mime_type):
        case "text/markdown":
            parsed, type = parse_md(content)
        case "application/pdf":
            parsed, type = parse_pdf(content)
        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            parsed, type = parse_doc_docx(content)
        case _:
            raise HTTPException(status_code=404, detail="File not supported, must be a txt, md, pdf or docx file")
    
    redis_client.set(f"Documentation: {file.filename}", parsed)
    background.add_task(run_workflow, file.filename, content, type)

    
    
        


    


