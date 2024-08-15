from flask import Flask, request, jsonify
from pymongo import MongoClient
from flask_cors import CORS
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_cohere import CohereEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Cohere
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document
import certifi
app = Flask(__name__)
CORS(app)

CONNECTION_STRING = "Your value"
DB_NAME = "Your value"
COLLECTION_NAME = "chunks"
persist_directory = 'docs/chroma/'

client = MongoClient(CONNECTION_STRING, tlsCAFile=certifi.where())
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

os.environ['COHERE_API_KEY'] = 'Your value'

@app.route('/')
def home():
    return "Hello, Heroku!"
@app.route('/upload', methods=['POST'])
def upload_pdf():
    files = request.files.getlist('files')
    upload_folder = './uploads'
    file_paths = []

    # Create the uploads directory if it doesn't exist
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    for file in files:
        file_path = os.path.join(upload_folder, file.filename)
        file.save(file_path)
        file_paths.append(file_path)

    splits = load_and_split_pdfs(file_paths)
    # embeddings = generate_embeddings(splits)
    embeddings,texts = generate_embeddings(splits)
    store_chunks(splits, texts, collection)
    # store_embeddings(splits, embeddings, collection)

    return jsonify({"message": "Files processed and embeddings stored. Please ask your question."})

def load_and_split_pdfs(files, chunk_size=2000, chunk_overlap=100):
    loaders = [PyPDFLoader(file) for file in files]
    docs = []
    for loader in loaders:
        docs.extend(loader.load())
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    splits = text_splitter.split_documents(docs)
    return splits

def store_chunks(splits, texts, collection):
    docs_for_db = [
        {
            "text": splits[i].page_content,
            "chunk": texts[i]
        }
        for i in range(len(splits))
    ]
    collection.insert_many(docs_for_db)


def generate_embeddings(splits):
    user_agent = "contextual_knowledge_search/1.0"
    # Initialize the embedding model
    embedding = CohereEmbeddings(model="embed-multilingual-v2.0", user_agent=user_agent)
    texts = [chunk.page_content for chunk in splits]
    embeddings = embedding.embed(texts)
    return embeddings,texts
def store_embeddings(splits, embeddings, collection):
    docs_for_db = [
        {
            "text": splits[i].page_content,
            "embedding": embeddings[i]
        }
        for i in range(len(splits))
    ]
    collection.insert_many(docs_for_db)

@app.route('/query', methods=['POST'])
def query():
    question = request.json.get('question')
    langchain_documents = fetch_documents(collection)
    vectordb = Chroma.from_documents(
        documents=langchain_documents,
        embedding=CohereEmbeddings(model="embed-multilingual-v2.0", user_agent="contextual_knowledge_search/1.0"),
        persist_directory=persist_directory
    )
    qa_chain = create_qa_chain(vectordb)
    answer = process_query(question, qa_chain)
    return jsonify({"answer": answer})

def fetch_documents(collection):
    documents = list(collection.find({}))
    return [
        Document(page_content=doc['text'], metadata={})
        for doc in documents
    ]

def create_qa_chain(vectordb):
    llm = Cohere(model="command", temperature=0)
    template = """Use the following pieces of context to answer the question:
    {context}
    Question: {question}
    Helpful Answer:"""
    QA_CHAIN_PROMPT = PromptTemplate(input_variables=["context", "question"], template=template)
    qa_chain = RetrievalQA.from_chain_type(llm, retriever=vectordb.as_retriever(), return_source_documents=True, chain_type_kwargs={"prompt": QA_CHAIN_PROMPT})
    return qa_chain

def process_query(question, qa_chain):
    result = qa_chain({"query": question})
    return result['result']

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5000,debug=True)
 