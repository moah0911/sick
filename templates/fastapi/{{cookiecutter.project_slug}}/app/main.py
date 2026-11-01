from fastapi import FastAPI
app = FastAPI()
@app.get("/health")
def health():
    return {"status": "ok", "project": "{{cookiecutter.project_slug}}"}
